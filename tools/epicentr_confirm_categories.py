"""
tools/epicentr_confirm_categories.py
Інтерактивне підтвердження маппінгу TOPTUL → Єпіцентр категорій.

Клавіші:
  Enter  — підтвердити поточний маппінг
  1–5    — обрати альтернативу зі списку
  s      — пропустити (залишити unconfirmed)
  q      — вийти
"""
import os, sys, re
from difflib import SequenceMatcher

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection

# ── ANSI кольори ─────────────────────────────────────────────────────────────
RESET  = '\033[0m'
BOLD   = '\033[1m'
GREEN  = '\033[32m'
YELLOW = '\033[33m'
CYAN   = '\033[36m'
RED    = '\033[31m'
DIM    = '\033[2m'

def clr(text, *codes): return ''.join(codes) + str(text) + RESET
def score_color(s):
    if s >= 0.75: return GREEN
    if s >= 0.55: return YELLOW
    return RED


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_pending(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT toptul_id, toptul_name, epicentr_code, epicentr_name, score
        FROM toptul_epicentr_category_map
        WHERE score < 0.85 AND confirmed = false
        ORDER BY score DESC
    """)
    rows = list(cur.fetchall())
    cur.close()
    return rows


def count_pending(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM toptul_epicentr_category_map WHERE score < 0.85 AND confirmed = false")
    n = cur.fetchone()['count']
    cur.close()
    return n


def count_confirmed(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM toptul_epicentr_category_map WHERE confirmed = true")
    n = cur.fetchone()['count']
    cur.close()
    return n


def load_epicentr(conn) -> list:
    cur = conn.cursor()
    cur.execute("SELECT code, name_ua FROM epicentr_categories WHERE name_ua IS NOT NULL AND name_ua != ''")
    rows = [(r['code'], r['name_ua']) for r in cur.fetchall()]
    cur.close()
    return rows


def confirm_row(conn, toptul_id: str, epicentr_code: str, epicentr_name: str):
    cur = conn.cursor()
    cur.execute("""
        UPDATE toptul_epicentr_category_map
        SET confirmed=true, epicentr_code=%s, epicentr_name=%s,
            score = CASE WHEN epicentr_code != %s THEN 1.0 ELSE score END
        WHERE toptul_id=%s
    """, (epicentr_code, epicentr_name, epicentr_code, toptul_id))
    conn.commit()
    cur.close()


# ── fuzzy search ──────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    return re.sub(r'\s+', ' ', (text or '').lower().strip())


def top_alternatives(query: str, candidates: list, n: int = 5) -> list:
    q = normalize(query)
    scored = [
        (SequenceMatcher(None, q, normalize(name)).ratio(), code, name)
        for code, name in candidates
    ]
    scored.sort(reverse=True)
    return scored[:n]


# ── display ───────────────────────────────────────────────────────────────────

def clear_line():
    print('\033[2K\r', end='')


def print_header(done: int, total_pending: int, total: int):
    confirmed = total - total_pending
    bar_len = 40
    filled  = int(bar_len * confirmed / total) if total else 0
    bar     = clr('█' * filled, GREEN) + clr('░' * (bar_len - filled), DIM)
    pct     = confirmed / total * 100 if total else 0
    print(f"\n{clr('TOPTUL → Єпіцентр  Підтвердження категорій', BOLD, CYAN)}")
    print(f"[{bar}] {clr(f'{confirmed}/{total}', BOLD)} ({pct:.1f}%)")
    print(f"{clr(f'Залишилось: {total_pending}', YELLOW)}   "
          f"Enter=підтвердити  1-5=альтернатива  s=пропустити  q=вийти\n")


def print_row(idx: int, total_pending: int, toptul_name: str,
              epicentr_name: str, score: float):
    sc = f'{score:.3f}'
    print(clr(f'  [{idx}/{total_pending}]', DIM) +
          f'  {clr(toptul_name, BOLD)}')
    print(f"  {'→':>3}  {clr(epicentr_name, CYAN)}  "
          f"[{clr(sc, score_color(score))}]")


def print_alternatives(alts: list):
    print(f"\n  {clr('Альтернативи:', DIM)}")
    for i, (sc, code, name) in enumerate(alts, 1):
        sc_str = f'{sc:.3f}'
        print(f"  {clr(str(i), BOLD, YELLOW)}. {name:<50}  "
              f"[{clr(sc_str, score_color(sc))}]  {clr(code, DIM)}")


# ── main loop ─────────────────────────────────────────────────────────────────

def main():
    conn        = get_connection()
    epicentr    = load_epicentr(conn)
    total       = count_confirmed(conn) + count_pending(conn)
    pending     = get_pending(conn)
    total_pend  = len(pending)

    if not pending:
        print(clr('Всі записи вже підтверджені!', GREEN, BOLD))
        conn.close()
        return

    print_header(0, total_pend, total)

    done = 0
    i    = 0
    while i < len(pending):
        row  = pending[i]
        tid, tname, ecode, ename, score = (
            row['toptul_id'], row['toptul_name'],
            row['epicentr_code'], row['epicentr_name'], float(row['score'])
        )

        remaining = count_pending(conn)
        print_row(i + 1, total_pend, tname, ename, score)

        alts = top_alternatives(tname, epicentr, 5)
        print_alternatives(alts)
        print()

        try:
            raw = input(clr('  > ', BOLD)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw == 'q':
            break

        elif raw == 's':
            print(clr('  пропущено', DIM))
            i += 1
            print()
            continue

        elif raw == '':
            # підтвердити поточний
            confirm_row(conn, tid, ecode, ename)
            done += 1
            print(clr('  ✓ підтверджено', GREEN))

        elif raw in ('1', '2', '3', '4', '5'):
            idx_alt = int(raw) - 1
            if idx_alt < len(alts):
                _, new_code, new_name = alts[idx_alt]
                confirm_row(conn, tid, new_code, new_name)
                done += 1
                print(clr(f'  ✓ обрано: {new_name}', GREEN))
            else:
                print(clr('  невірний номер', RED))
                continue

        else:
            print(clr('  невідома команда (Enter/1-5/s/q)', RED))
            continue

        i += 1
        print()

    conn.close()
    print(clr(f'\nЗавершено. Підтверджено за сесію: {done}', BOLD))
    conn2 = get_connection()
    left  = count_pending(conn2)
    conf  = count_confirmed(conn2)
    conn2.close()
    print(f'Підтверджено всього: {clr(conf, GREEN, BOLD)} / {total}')
    print(f'Залишилось непідтверджених: {clr(left, YELLOW, BOLD)}\n')


if __name__ == '__main__':
    main()
