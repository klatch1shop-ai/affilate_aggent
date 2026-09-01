#!/usr/bin/env python3
"""Ручне перевизначення цін NOIRE для Rozetka.

Навіщо окремий шар, а не правка XML (як у Carvol-менеджера): наш фід
перезбирається з бази щогодини. Ціна, вписана прямо в XML, проживе до
наступної публікації й зникне. Тому перевизначення живе в базі, а генератор
питає її перед власним розрахунком.

Автоматична синхронізація з SexOpt цим не чіпається: `price_retail`
оновлюється як завжди, змінюється лише підсумкова ціна продажу — і лише
для тих SKU, які тут перелічені, і лише поки не мине `until`.

Два запобіжники діють завжди і вимкнути їх не можна:

  Анти-демпінг. Після утримання комісії Rozetka на руки має лишатись не
  менше за роздрібну ціну SexOpt. Це правило постачальника про мінімальну
  ціну на всіх каналах, і акція його не скасовує.

  Стрибок ціни. Rozetka робить позицію неактивною до ручного підтвердження,
  якщо ціна зросла втричі або впала вдвічі. Такі зміни вимагають --force,
  щоб це сталося усвідомлено, а не через помилку в проценті.

Приклади:
    # акція на категорію до конкретної дати
    noire_price_override.py --category "Еротична білизна" --percent -10 \\
        --until 2026-08-20 --reason "серпнева акція"

    # реакція на конкурента, точково
    noire_price_override.py --sku SO7368 --price 649 --reason "конкурент 679"

    # по бренду
    noire_price_override.py --vendor Obsessive --percent 5 --reason "маржа"

    # зняти
    noire_price_override.py --clear --category "Лубриканти"

    # подивитись чинні
    noire_price_override.py --list
"""
import argparse
import datetime
import os
import sys

import psycopg2.extras
from loguru import logger

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, 'tools'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE_DIR, '.env'))
from shared.utils.db import get_connection  # noqa: E402
from noire_rozetka_generator import (  # noqa: E402
    calc_price, load_tariffs, load_mapping, DEFAULT_COMMISSION)

# Пороги Rozetka, за якими позиція стає неактивною до ручного підтвердження
JUMP_UP = 3.0
JUMP_DOWN = 0.5


def ensure_table(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sexopt_price_override (
            sku          TEXT PRIMARY KEY,
            price_manual INTEGER     NOT NULL CHECK (price_manual > 0),
            reason       TEXT        NOT NULL,
            until        DATE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


def commission_at(scale, price: float) -> float:
    """Ставка, яку Rozetka утримає з цієї ціни продажу."""
    if not scale:
        return DEFAULT_COMMISSION
    for lo, hi, rate in sorted(scale):
        if lo <= price <= hi:
            return float(rate)
    return float(sorted(scale)[-1][2])


def select_targets(cur, a) -> list:
    """Товари під фільтр. Порожній фільтр свідомо не дозволяємо."""
    where = ["p.price_retail > 0", "m.rozetka_category_id IS NOT NULL"]
    args = []
    if a.sku:
        where.append('p.sku = ANY(%s)')
        args.append([s.strip().upper() for s in a.sku.split(',') if s.strip()])
    if a.category:
        where.append('m.rozetka_category_name ILIKE %s')
        args.append(f'%{a.category}%')
    if a.vendor:
        where.append('p.vendor ILIKE %s')
        args.append(f'%{a.vendor}%')
    cur.execute(f"""
        SELECT p.sku, p.name, p.vendor, p.price_retail,
               p.category_id, m.rozetka_category_id AS rz,
               m.rozetka_category_name AS rzname,
               o.price_manual, o.until AS o_until, o.reason AS o_reason
        FROM sexopt_products p
        JOIN rozetka_category_mapping m
          ON m.sexopt_category_id = p.category_id AND m.source = 'noire'
        LEFT JOIN sexopt_price_override o ON o.sku = p.sku
        WHERE {' AND '.join(where)}
        ORDER BY p.sku
    """, args)
    return cur.fetchall()


def cmd_list(cur):
    cur.execute("""
        SELECT o.sku, o.price_manual, o.reason, o.until, o.created_at,
               p.name, p.price_retail
        FROM sexopt_price_override o
        LEFT JOIN sexopt_products p ON p.sku = o.sku
        ORDER BY o.created_at DESC
    """)
    rows = cur.fetchall()
    if not rows:
        print('Чинних перевизначень немає.')
        return
    today = datetime.date.today()
    print(f"{'SKU':10} {'ціна':>7} {'до':>12} {'стан':9} причина")
    for r in rows:
        state = 'минуло' if r['until'] and r['until'] < today else 'діє'
        print(f"{r['sku']:10} {r['price_manual']:>7} "
              f"{str(r['until'] or '—'):>12} {state:9} {r['reason'][:44]}")
    print(f'\nВсього: {len(rows)}')


def cmd_clear(conn, cur, a):
    targets = select_targets(cur, a)
    skus = [r['sku'] for r in targets if r['price_manual'] is not None]
    if not skus:
        print('Під фільтр не потрапило жодного чинного перевизначення.')
        return
    print(f'До зняття: {len(skus)} перевизначень')
    for r in targets:
        if r['price_manual'] is not None:
            print(f"   {r['sku']:10} {r['price_manual']:>7} — {r['o_reason'][:44]}")
    if a.dry:
        print('\n(--dry: нічого не знято)')
        return
    cur.execute('DELETE FROM sexopt_price_override WHERE sku = ANY(%s)', (skus,))
    conn.commit()
    logger.success(f'Знято {len(skus)} перевизначень')


def cmd_set(conn, cur, a):
    tariffs = load_tariffs(cur)
    targets = select_targets(cur, a)
    if not targets:
        print('Під фільтр не потрапило жодного товару.')
        return

    ok, blocked_dump, blocked_jump = [], [], []
    for r in targets:
        rz = str(r['rz'])
        scale = tariffs.get(rz)
        retail = float(r['price_retail'])
        current = r['price_manual'] or calc_price(retail, scale)

        if a.price:
            new = int(a.price)
        else:
            new = int(round(current * (1 + a.percent / 100)))
        if new <= 0:
            continue

        # Запобіжник 1 — анти-демпінг. Рахуємо за ставкою, яка діє саме на
        # новій ціні: тир може змінитись разом з нею.
        net = new * (1 - commission_at(scale, new) / 100)
        if net < retail - 0.01:
            blocked_dump.append((r, current, new, net, retail))
            continue

        # Запобіжник 2 — стрибок, за яким Rozetka зупиняє позицію
        ratio = new / current if current else 1
        if (ratio >= JUMP_UP or ratio <= JUMP_DOWN) and not a.force:
            blocked_jump.append((r, current, new, ratio))
            continue

        ok.append((r, current, new, net))

    if blocked_dump:
        print(f'\n⛔ ВІДМОВЛЕНО — демпінг ({len(blocked_dump)}):')
        print('   після комісії Rozetka на руки лишиться менше за РРЦ SexOpt')
        for r, cur_p, new, net, retail in blocked_dump[:10]:
            print(f"   {r['sku']:10} {cur_p} → {new}: на руки {net:.0f} "
                  f"< РРЦ {retail:.0f}   (мінімум {cur_p})")
        if len(blocked_dump) > 10:
            print(f'   … ще {len(blocked_dump) - 10}')

    if blocked_jump:
        print(f'\n⚠️  ВІДМОВЛЕНО — стрибок ціни ({len(blocked_jump)}):')
        print('   Rozetka зробить позицію неактивною до ручного підтвердження')
        for r, cur_p, new, ratio in blocked_jump[:10]:
            direction = 'вгору' if ratio > 1 else 'вниз'
            k = ratio if ratio > 1 else 1 / ratio
            print(f"   {r['sku']:10} {cur_p} → {new}: у {k:.1f}× {direction}")
        if len(blocked_jump) > 10:
            print(f'   … ще {len(blocked_jump) - 10}')
        print('   Якщо це свідома дія — повтори з --force')

    if not ok:
        print('\nЗастосовувати нічого.')
        return

    print(f'\n✓ ДО ЗАСТОСУВАННЯ: {len(ok)}')
    print(f"{'SKU':10} {'РРЦ':>7} {'зараз':>7} {'стане':>7} {'Δ':>7} {'на руки':>8}")
    for r, cur_p, new, net in ok[:15]:
        print(f"{r['sku']:10} {float(r['price_retail']):>7.0f} {cur_p:>7} "
              f"{new:>7} {(new - cur_p) / cur_p * 100:>+6.1f}% {net:>8.0f}")
    if len(ok) > 15:
        print(f'   … ще {len(ok) - 15}')

    if a.dry:
        print('\n(--dry: у базу нічого не записано)')
        return

    psycopg2.extras.execute_values(cur, """
        INSERT INTO sexopt_price_override (sku, price_manual, reason, until)
        VALUES %s
        ON CONFLICT (sku) DO UPDATE SET
          price_manual = EXCLUDED.price_manual,
          reason = EXCLUDED.reason,
          until = EXCLUDED.until,
          created_at = NOW()
    """, [(r['sku'], new, a.reason, a.until) for r, _, new, _ in ok])
    conn.commit()
    logger.success(f'Записано {len(ok)} перевизначень')
    print('\nНабуде чинності при наступній перегенерації фіду '
          '(cron щогодини о :20) або одразу: '
          'python3 tools/noire_stock_sync.py --publish-rozetka')


def main():
    ap = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    ap.add_argument('--sku', help='через кому')
    ap.add_argument('--category', help='назва категорії Rozetka, частковий збіг')
    ap.add_argument('--vendor', help='бренд, частковий збіг')
    ap.add_argument('--price', type=int, help='фіксована ціна')
    ap.add_argument('--percent', type=float,
                    help='± відсоток від поточної розрахованої ціни')
    ap.add_argument('--reason', help='обовʼязково при встановленні')
    ap.add_argument('--until', help='дата автозавершення, YYYY-MM-DD')
    ap.add_argument('--force', action='store_true',
                    help='дозволити зміну, яку Rozetka вважає стрибком')
    ap.add_argument('--clear', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--dry', action='store_true')
    a = ap.parse_args()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    ensure_table(cur)
    conn.commit()

    if a.list:
        cmd_list(cur)
    elif a.clear:
        if not (a.sku or a.category or a.vendor):
            ap.error('--clear потребує хоча б одного фільтра: '
                     '--sku, --category або --vendor')
        cmd_clear(conn, cur, a)
    else:
        if not (a.sku or a.category or a.vendor):
            ap.error('потрібен хоча б один фільтр: --sku, --category або --vendor')
        if (a.price is None) == (a.percent is None):
            ap.error('вкажи рівно одне: --price або --percent')
        if not a.reason:
            ap.error('--reason обовʼязковий: через місяць має бути зрозуміло, '
                     'звідки взялась ручна ціна')
        if a.until:
            try:
                datetime.date.fromisoformat(a.until)
            except ValueError:
                ap.error('--until у форматі YYYY-MM-DD')
        cmd_set(conn, cur, a)

    cur.close()
    conn.close()


if __name__ == '__main__':
    main()
