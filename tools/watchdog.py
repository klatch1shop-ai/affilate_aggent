#!/usr/bin/env python3
"""
tools/watchdog.py — моніторинг здоров'я системи.

Запускається кожні 10 хвилин через cron:
  */10 * * * * cd /home/tek/agent-system && /home/tek/agent-system/venv/bin/python3 tools/watchdog.py >> /tmp/watchdog.log 2>&1

Перевіряє:
  1. Git uncommitted changes — авто-коміт локально (push — тільки розробник вручну)
  2. Crontab — правильні шляхи (cd /home/tek/agent-system)
  3. Сервіси systemd — перезапускає якщо впали
  4. rozetka_sync_cron.log — FAILED alert
  5. Фіди (три NOIRE + Carvol→Rozetka) — свіжість, розмір, доступність
  6. Telegram звіт кожні 6 годин — сервіси, git, cron, sync і всі чотири фіди
"""

import calendar
import html
import re
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

# ── config ───────────────────────────────────────────────────────────────────

REPO_DIR = "/home/tek/agent-system"
load_dotenv(dotenv_path=os.path.join(REPO_DIR, ".env"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN")
CHAT_ID   = (
    os.getenv("TELEGRAM_ADMIN_ID")
    or os.getenv("TELEGRAM_CHAT_ID")
    or os.getenv("TG_CHAT_ID")
)

SERVICES        = ["rozetka-order-agent", "tg-dispatcher", "noire-notifier"]
REPORT_INTERVAL = timedelta(hours=6)
STATE_FILE      = "/tmp/watchdog_last_report.txt"
SYNC_LOG        = "/tmp/rozetka_sync_cron.log"
# Початок прогону в логу. Лог дописується, тож без цієї межі перевірка або
# бачить лише хвіст останнього прогону, або тривожить на давно виправлених
# відмовах — див. last_sync_run().
SYNC_RUN_MARKER = "=== Rozetka GitHub Sync ==="
CRON_FLAG       = "/tmp/watchdog_cron_warned.flag"
SYNC_ERROR_FLAG = "/tmp/watchdog_sync_error_last.txt"

# NOIRE: опублікований фід має бути доступним і не старішим за добу
NOIRE_FEED      = "/home/tek/agent-system/output/noire_epicentr_phase1.xml"
NOIRE_RAW_URL   = ("https://raw.githubusercontent.com/klatch1shop-ai/"
                   "noire-feed/main/noire_epicentr.xml")
NOIRE_MAX_AGE_H = 26          # 2-годинний цикл + запас на добовий простій
NOIRE_FLAG      = "/tmp/watchdog_noire_last.txt"

# Rozetka забирає прайс щогодини, тому й публікація щогодинна, і поріг
# свіжості вужчий: три пропущені цикли — вже привід сповістити.
NOIRE_RZ_FEED     = "/home/tek/agent-system/output/noire_rozetka.xml"
NOIRE_RZ_RAW_URL  = ("https://raw.githubusercontent.com/klatch1shop-ai/"
                     "noire-feed/main/noire_rozetka.xml")
NOIRE_RZ_MAX_AGE_H = 3
NOIRE_RZ_MIN_BYTES = 5_000_000     # фід ~16 МБ; менше — ознака обрізаного файлу

# raw.githubusercontent віддає XML стиснутим, і content-length тоді показує
# розмір gzip (1,2 МБ замість 16 МБ) — перевірка розміру на цьому хибно
# спрацьовувала. Просимо нестиснуту відповідь, щоб бачити справжню довжину.
IDENTITY = {"Accept-Encoding": "identity"}
NOIRE_RZ_FLAG      = "/tmp/watchdog_noire_rz_last.txt"

# Prom забирає прайс раз на 4 години у вікні 07:00-22:00, тому публікація
# теж чотиригодинна. Поріг свіжості врахоує нічну паузу: після 19:40
# наступна збірка аж о 07:40, тобто 12 годин тиші — це норма.
NOIRE_PROM_FEED     = "/home/tek/agent-system/output/noire_prom.xml"
NOIRE_PROM_RAW_URL  = ("https://raw.githubusercontent.com/klatch1shop-ai/"
                       "noire-feed/main/noire_prom.xml")
NOIRE_PROM_MAX_AGE_H = 14
NOIRE_PROM_MIN_BYTES = 20_000_000    # фід ~44 МБ; менше — обрізаний файл
NOIRE_PROM_FLAG      = "/tmp/watchdog_noire_prom_last.txt"

# Carvol → Rozetka. Прайс збирає rozetka_github_sync.py щодня о 07:15 і пушить
# у репозиторій affilate_aggent — саме звідти Rozetka забирає файл. Це єдиний
# наш фід, який публікується не в noire-feed, тому й URL інший.
CARVOL_RZ_FEED      = "/home/tek/agent-system/data/carvol_rozetka.xml"
CARVOL_RZ_RAW_URL   = ("https://raw.githubusercontent.com/klatch1shop-ai/"
                       "affilate_aggent/main/data/carvol_rozetka.xml")
# Комміти, що торкались саме цього файлу: дата останнього = вік ОПУБЛІКОВАНОЇ
# версії. Потрібен окремо від raw-URL, бо raw віддає старий файл із HTTP 200
# і повним розміром — недоставлена публікація звідти не видно.
CARVOL_RZ_API_URL   = ("https://api.github.com/repos/klatch1shop-ai/"
                       "affilate_aggent/commits"
                       "?path=data/carvol_rozetka.xml&per_page=1")
CARVOL_RZ_MAX_AGE_H = 26          # добовий цикл о 07:15 + запас на один збій
CARVOL_RZ_MIN_BYTES = 20_000_000  # фід ~40 МБ; менше — ознака обрізаного файлу
CARVOL_RZ_FLAG      = "/tmp/watchdog_carvol_rz_last.txt"

CRON_CHECKS = [
    ("rozetka_github_sync.py", "cd /home/tek/agent-system"),
    ("--publish-rozetka",      "cd /home/tek/agent-system"),
    ("--publish-prom",         "cd /home/tek/agent-system"),
    ("noire_stock_sync.py",    "cd /home/tek/agent-system"),
    ("price_updater.py",       "cd /home/tek/agent-system"),
    ("feed_sync.py",           "cd /home/tek/agent-system"),
]

# systemctl --user потребує XDG_RUNTIME_DIR в cron
_uid = os.getuid()
os.environ.setdefault("XDG_RUNTIME_DIR",        f"/run/user/{_uid}")
os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{_uid}/bus")


# ── helpers ───────────────────────────────────────────────────────────────────

def log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def run(cmd: str, cwd: str = REPO_DIR) -> tuple:
    """Returns (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, cwd=cwd,
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return 1, "", "timeout"
    except Exception as e:
        return 1, "", str(e)


def tg(msg: str):
    if not BOT_TOKEN or not CHAT_ID:
        log(f"[tg] не налаштовано BOT_TOKEN/CHAT_ID")
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log(f"[tg] помилка: {e}")


def probe_raw(url: str, min_bytes: int, label: str = "",
              attempts: int = 3, pause: float = 20.0) -> str:
    """Доступність опублікованого фіду. Порожній рядок = все гаразд.

    Одного запиту замало. raw.githubusercontent.com — CDN, і він регулярно
    віддає 429/502/503 на секунди. 17.08.2026 з 15:40 до 18:10 watchdog
    надіслав вісім тривог, тоді як паралельна перевірка з іншої мережі дала
    45 успішних відповідей поспіль: фід був доступний увесь час.

    Тому проблемою вважається лише стійка недоступність — кілька спроб із
    паузою, і достатньо однієї вдалої, щоб визнати фід живим.
    """
    what = f"raw-URL {label}".strip()
    last = ""
    for i in range(attempts):
        try:
            r = requests.head(url, timeout=30, allow_redirects=True,
                              headers=IDENTITY)
            if r.status_code == 200:
                if int(r.headers.get("content-length", 0)) < min_bytes:
                    return f"{what} віддає підозріло малий файл"
                return ""
            last = f"HTTP {r.status_code}"
        except Exception as e:
            last = type(e).__name__
        if i < attempts - 1:
            time.sleep(pause)
    # Код відповіді НЕ входить у текст: доти він був частиною ключа
    # дедуплікації, і чергування 429 → 503 → 502 щоразу вважалось новою
    # проблемою. Одна несправність давала вісім тривог замість однієї.
    return f"{what} недоступний {attempts} спроби поспіль (останнє: {last})"


def published_age_h(api_url: str) -> float:
    """Вік ОПУБЛІКОВАНОЇ версії файлу в годинах. -1.0 = дізнатись не вдалось.

    Свіжість локального файлу і свіжість публікації — різні події, і саме на
    цьому розрив: 23-25.08.2026 rozetka_github_sync щодня збирав новий прайс
    Carvol і щодня НЕ міг його віддати (двічі 'Authentication failed', раз
    'cannot pull with rebase'). Локальний файл при цьому був свіжий, raw-URL
    відповідав HTTP 200 повного розміру — обидві перевірки NOIRE-зразка
    сказали б «усе гаразд» про день, коли Rozetka отримала вчорашні ціни.
    За 23.08 у репозиторії коміту немає взагалі.

    Береться дата коміту, а не час пушу: вона показує, коли зібрано ВМІСТ, що
    зараз лежить за посиланням. Прайс, запушений із запізненням на добу, і є
    добової давнини, хоч би коли він доїхав.

    Невідомий результат навмисно НЕ є проблемою: watchdog ходить сюди 144 рази
    на добу, ліміт GitHub без токена — 60 запитів на годину з IP, і
    перетворювати кожен 403 на тривогу означало б навчити власника
    прогортати сповіщення не читаючи.
    """
    try:
        r = requests.get(api_url, timeout=30,
                         headers={"Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            log(f"[pub] GitHub API HTTP {r.status_code} — вік публікації невідомий")
            return -1.0
        commits = r.json()
        if not commits:
            log("[pub] GitHub API: жодного коміту по цьому шляху")
            return -1.0
        iso = commits[0]["commit"]["committer"]["date"]      # 2026-08-25T04:15:42Z
        made = calendar.timegm(
            datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").timetuple())
        return (time.time() - made) / 3600
    except Exception as e:
        log(f"[pub] вік публікації невідомий: {type(e).__name__}: {e}")
        return -1.0


# ── check 1: git ──────────────────────────────────────────────────────────────

# Файл, змінений щойно, майже напевно зараз редагується — агентом, редактором
# або скриптом. `git add -A` захоплював його в напівзаписаному стані й комітив
# під ім'ям власника. Тому свіжі зміни пропускаємо й чекаємо наступного циклу.
GIT_SETTLE_SEC = 180


def _dirty_files() -> list:
    """[(шлях, вік_змін_у_секундах)] — усе, що git бачить як змінене."""
    rc, out, _ = run("git status --porcelain")
    if rc != 0 or not out:
        return []
    items = []
    for line in out.splitlines():
        # `run()` робить strip() на всьому виводі, тому провідний пробіл
        # ПЕРШОГО рядка зникає: « M file» стає «M file», і зріз line[3:]
        # відрізає перший символ імені. Тому знімаємо префікс статусу
        # регуляркою, а не фіксованою позицією.
        path = re.sub(r'^\s*[MADRCU?!]{1,2}\s+', '', line).strip().strip('"')
        if ' -> ' in path:                      # перейменування
            path = path.split(' -> ')[-1]
        if not path:
            continue
        try:
            age = time.time() - os.path.getmtime(os.path.join(REPO_DIR, path))
        except OSError:
            age = 1e9                           # видалений файл — комітимо
        items.append((path, age))
    return items


def check_git() -> dict:
    """Авто-коміт як страхувальна сітка для роботи агентів.

    Історично сюди потрапляв не лише згенерований XML, а й код, який пишуть
    агенти — `tools/toptul_*.py`, `tools/rozetka_*.py`. Це корисно: робота не
    губиться між сесіями. Ламало інше — `git add -A` захоплює **все дерево**
    атомарно, зокрема файл, який агент редагує саме зараз, і комітить його
    напівзаписаним під ім'ям власника.

    Тому замість `-A` додаємо пофайлово й **пропускаємо все, змінене за
    останні GIT_SETTLE_SEC секунд**. Файл, який дійсно дописали, потрапить у
    наступний цикл через 10 хвилин; файл, який ще пишуть, лишиться недоторканим.
    """
    items = _dirty_files()
    if not items:
        log("[git] репо чисте")
        return {"ok": True, "msg": "clean"}

    ready = [p for p, age in items if age >= GIT_SETTLE_SEC]
    fresh = [p for p, age in items if age < GIT_SETTLE_SEC]
    if fresh:
        log(f"[git] пропускаю {len(fresh)} щойно змінених "
            f"(можуть редагуватись): {', '.join(fresh[:4])}")
    if not ready:
        return {"ok": True, "msg": f"{len(fresh)} files still being edited"}

    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    quoted = " ".join(f'"{p}"' for p in ready)
    rc2, _, err2 = run(f'git add -- {quoted} && '
                       f'git commit -m "auto: watchdog sync {ts}"')
    if rc2 != 0:
        log(f"[git] commit failed: {err2}")
        return {"ok": False, "msg": f"commit failed: {err2[:80]}"}

    # Push виконує тільки розробник вручну — watchdog лише комітить локально
    log(f"[git] авто-коміт (без push): {len(ready)} файлів — "
        f"{', '.join(ready[:5])}{'…' if len(ready) > 5 else ''}")
    return {"ok": True, "msg": f"auto-committed {len(ready)} files (no push)"}


# ── check 2: crontab ──────────────────────────────────────────────────────────

def check_cron() -> dict:
    rc, crontab, _ = run("crontab -l")
    if rc != 0:
        return {"ok": True, "msg": "no crontab"}

    issues = []
    for script, required in CRON_CHECKS:
        lines = [
            l for l in crontab.splitlines()
            if script in l and not l.strip().startswith("#")
        ]
        for line in lines:
            if required not in line:
                issues.append(f"{script} — відсутній '{required}'")
                log(f"[cron] WARN: {script} не має '{required}'")

    if issues:
        if not os.path.exists(CRON_FLAG):
            tg("⚠️ <b>Watchdog cron</b>: некоректні шляхи\n" + "\n".join(issues))
            Path(CRON_FLAG).write_text(str(time.time()))
        return {"ok": False, "msg": "; ".join(issues)}

    if os.path.exists(CRON_FLAG):
        os.remove(CRON_FLAG)
    log("[cron] всі шляхи OK")
    return {"ok": True, "msg": "ok"}


# ── check 3: services ─────────────────────────────────────────────────────────

def check_services() -> dict:
    statuses   = {}
    restarted  = []
    failed     = []

    for svc in SERVICES:
        rc, out, _ = run(f"systemctl --user is-active {svc}")
        active = out.strip() == "active"
        statuses[svc] = active

        if not active:
            log(f"[svc] {svc} не активний ('{out}') — перезапускаю...")
            rc2, _, err2 = run(f"systemctl --user restart {svc}")
            if rc2 == 0:
                restarted.append(svc)
                log(f"[svc] {svc} перезапущено")
                tg(f"⚠️ <b>Watchdog</b>: <code>{svc}</code> впав — перезапущено ✅")
            else:
                failed.append(svc)
                log(f"[svc] {svc} НЕ вдалось перезапустити: {err2}")
                tg(f"🚨 <b>ALARM Watchdog</b>: <code>{svc}</code> не запускається!\n<code>{err2[:200]}</code>")

    all_ok = not failed
    return {"ok": all_ok, "services": statuses, "restarted": restarted, "failed": failed}


# ── check 4: sync log ─────────────────────────────────────────────────────────

def last_sync_run(text: str) -> list:
    """Рядки ОСТАННЬОГО прогону rozetka_github_sync.py.

    Лог дописується, а не перезаписується: у ньому лежать усі прогони від
    18.08.2026. Тому обидві очевидні межі неправильні — читати файл цілком не
    можна (три відмови 23-25.08 тривожили б вічно), читати самий останній
    рядок теж не можна: саме через це вони не тривожили жодного разу.
    """
    lines = [l.rstrip() for l in text.splitlines()]
    starts = [i for i, l in enumerate(lines) if SYNC_RUN_MARKER in l]
    if starts:
        return lines[starts[-1]:]
    # Маркера немає — лог обрізали або формат змінився. Беремо хвіст, довший
    # за один прогін (~23 рядки): краще подивитись зайве, ніж оголосити
    # успішним прогін, якого не бачили.
    return lines[-40:]


def check_sync_log() -> dict:
    """Чи доїхала щоденна публікація прайсу Carvol у GitHub.

    Читається ОСТАННІЙ прогін цілком, а не останній його рядок. Стара версія
    брала `lines[-1]`, а `rozetka_github_sync.py` друкує останнім рядок
    «URL: …» — тому «Git push: ❌ FAILED» 23, 24 і 25.08.2026 не дав жодної
    тривоги, і добу, коли Rozetka читала позавчорашні ціни, помітили лише
    через два дні й лише руками.

    У тривогу йде рядок ERROR, а не «FAILED»: наслідок однаковий для
    протухлого токена і для незакоміченого файлу, а робити з ними треба різне.

    Ключ дедуплікації містить дату прогону. Без неї друга така сама відмова
    наступного дня мовчала б (текст той самий), з нею виходить рівно одна
    тривога на кожен провалений прогін — а не 144 на добу від
    десятихвилинного cron.

    Чого ця перевірка НЕ ловить: мовчазного зависання, коли прогін почався й
    не закінчився. Це видно з іншого боку — `check_carvol_rozetka_feed()`
    міряє вік локального файлу й вік публікації.
    """
    if not os.path.exists(SYNC_LOG):
        return {"ok": True, "msg": "no log yet"}

    try:
        block = [l.strip() for l in
                 last_sync_run(Path(SYNC_LOG).read_text(errors="replace"))
                 if l.strip()]
        if not block:
            return {"ok": True, "msg": "empty"}

        stamp = block[0][:16]          # «2026-08-25 07:15» із рядка-маркера
        bad = [
            l for l in block
            if "FAILED" in l.upper()
            or "TRACEBACK" in l.upper()
            or ("| ERROR" in l.upper() and "WARNING" not in l.upper())
        ]
        if bad:
            reason = next((l for l in bad if "| ERROR" in l.upper()), bad[0])
            log(f"[sync] прогін {stamp} провалився: {reason[:160]}")

            last_sent = ""
            if os.path.exists(SYNC_ERROR_FLAG):
                try:
                    last_sent = Path(SYNC_ERROR_FLAG).read_text().strip()
                except Exception:
                    pass

            err_key = f"{stamp} {reason}"[:200]
            if err_key != last_sent:
                # Причина йде з виводу git і може містити '<'. Telegram із
                # parse_mode=HTML відповідає на таке HTTP 400, а tg() помилку
                # ковтає — тобто тривоги просто не було б. Саме той різновид
                # мовчання, який ця перевірка й лікує.
                tg("🚨 <b>Watchdog</b>: прайс Carvol не опубліковано "
                   f"({stamp})\n<code>{html.escape(reason[:300])}</code>")
                Path(SYNC_ERROR_FLAG).write_text(err_key)
                log(f"[sync] алерт відправлено в Telegram")
            else:
                log(f"[sync] та сама помилка — алерт вже надсилали, пропускаємо дублікат")

            return {"ok": False, "msg": reason[:80]}

        # Успішний run — скидаємо прапор щоб наступна помилка знову тригернула алерт
        if os.path.exists(SYNC_ERROR_FLAG):
            os.remove(SYNC_ERROR_FLAG)
            log(f"[sync] прапор помилки скинуто (успішний run)")
        return {"ok": True, "msg": f"{stamp} ok"}
    except Exception as e:
        return {"ok": True, "msg": f"read error: {e}"}


def check_noire_feed() -> dict:
    """Опублікований NOIRE-фід: доступність raw-URL і свіжість.

    Локальний файл може бути свіжим, а публікація — відсталою (впав push),
    тому перевіряються обидві сторони.
    """
    problems = []
    if os.path.exists(NOIRE_FEED):
        age_h = (time.time() - os.path.getmtime(NOIRE_FEED)) / 3600
        if age_h > NOIRE_MAX_AGE_H:
            problems.append(f"локальний фід не оновлювався {age_h:.0f} год")
    else:
        problems.append("локального фіду немає")

    bad = probe_raw(NOIRE_RAW_URL, 1_000_000)
    if bad:
        problems.append(bad)

    if problems:
        key = "; ".join(problems)[:200]
        last = ""
        if os.path.exists(NOIRE_FLAG):
            try:
                last = Path(NOIRE_FLAG).read_text().strip()
            except Exception:
                pass
        if key != last:
            tg(f"🚨 <b>Watchdog NOIRE</b>: {key}")
            Path(NOIRE_FLAG).write_text(key)
        log(f"[noire] ПРОБЛЕМА: {key}")
        return {"ok": False, "msg": key[:80]}

    if os.path.exists(NOIRE_FLAG):
        os.remove(NOIRE_FLAG)
    log("[noire] фід свіжий, raw-URL доступний")
    return {"ok": True, "msg": "feed ok"}


def check_noire_prom_feed() -> dict:
    """Фід Prom: свіжість локального файлу і доступність raw-URL.

    Поріг ширший за Rozetka: публікація йде лише вдень (07:00-22:00), тож
    уночі файл законно старіє до 12 годин.
    """
    problems = []
    if os.path.exists(NOIRE_PROM_FEED):
        age_h = (time.time() - os.path.getmtime(NOIRE_PROM_FEED)) / 3600
        if age_h > NOIRE_PROM_MAX_AGE_H:
            problems.append(f"фід Prom не оновлювався {age_h:.0f} год")
    else:
        problems.append("локального фіду Prom немає")

    bad = probe_raw(NOIRE_PROM_RAW_URL, NOIRE_PROM_MIN_BYTES, "Prom")
    if bad:
        problems.append(bad)

    if problems:
        key = "; ".join(problems)[:200]
        last = ""
        if os.path.exists(NOIRE_PROM_FLAG):
            try:
                last = Path(NOIRE_PROM_FLAG).read_text().strip()
            except Exception:
                pass
        if key != last:
            tg(f"🚨 <b>Watchdog NOIRE Prom</b>: {key}")
            Path(NOIRE_PROM_FLAG).write_text(key)
        log(f"[noire-prom] ПРОБЛЕМА: {key}")
        return {"ok": False, "msg": key[:80]}

    if os.path.exists(NOIRE_PROM_FLAG):
        os.remove(NOIRE_PROM_FLAG)
    log("[noire-prom] фід свіжий, raw-URL доступний")
    return {"ok": True, "msg": "feed ok"}


def check_noire_rozetka_feed() -> dict:
    """Фід Rozetka: свіжість локального файлу і доступність raw-URL.

    Окремо від epicentr-перевірки: інший файл, інший URL і втричі вужчий
    поріг свіжості — Rozetka оновлюється щогодини, а не раз на добу.
    """
    problems = []
    if os.path.exists(NOIRE_RZ_FEED):
        age_h = (time.time() - os.path.getmtime(NOIRE_RZ_FEED)) / 3600
        if age_h > NOIRE_RZ_MAX_AGE_H:
            problems.append(f"фід Rozetka не оновлювався {age_h:.0f} год")
    else:
        problems.append("локального фіду Rozetka немає")

    bad = probe_raw(NOIRE_RZ_RAW_URL, NOIRE_RZ_MIN_BYTES, "Rozetka")
    if bad:
        problems.append(bad)

    if problems:
        key = "; ".join(problems)[:200]
        last = ""
        if os.path.exists(NOIRE_RZ_FLAG):
            try:
                last = Path(NOIRE_RZ_FLAG).read_text().strip()
            except Exception:
                pass
        if key != last:
            tg(f"🚨 <b>Watchdog NOIRE Rozetka</b>: {key}")
            Path(NOIRE_RZ_FLAG).write_text(key)
        log(f"[noire-rz] ПРОБЛЕМА: {key}")
        return {"ok": False, "msg": key[:80]}

    if os.path.exists(NOIRE_RZ_FLAG):
        os.remove(NOIRE_RZ_FLAG)
    log("[noire-rz] фід свіжий, raw-URL доступний")
    return {"ok": True, "msg": "feed ok"}



# ── Повідомлення Rozetka продавцеві ────────────────────────────────────────
RZ_FEEDBACK_URL  = "https://api-seller.rozetka.com.ua/feedbacks/search"
RZ_FEEDBACK_SEEN = "/tmp/watchdog_rz_feedback_seen.txt"


def check_rozetka_messages() -> dict:
    """
    Нові повідомлення від Rozetka продавцеві (`/feedbacks/search`).

    Навіщо: 01.09.2026 знайдено ВИПАДКОВО, шукаючи інше, чотири звернення —
    зокрема «ваш номер телефону для покупців недоступний, це призводить до
    скарг і скасувань» та прохання обробити конкретне замовлення. Розетка
    пише нам у канал, який ніхто не читав.

    Тривожимо лише на НОВІ id: перелік уже побачених лежить у файлі, інакше
    кожен цикл повторював би те саме й ми перестали б читати сповіщення.
    """
    tok = os.getenv("ROZETKA_API_TOKEN", "")
    if not tok:
        return {"ok": True, "msg": "ROZETKA_API_TOKEN не задано — пропускаю"}
    try:
        r = requests.get(RZ_FEEDBACK_URL, timeout=30,
                         headers={"Authorization": f"Bearer {tok}",
                                  "Content-Language": "uk"},
                         params={"page": 1})
        d = r.json()
        if not d.get("success"):
            err = (d.get("errors") or {}).get("message", "")
            return {"ok": False, "msg": f"Rozetka feedbacks: {err or r.status_code}"}
        items = (d.get("content") or {}).get("feedbacks") or []
    except Exception as e:
        return {"ok": False, "msg": f"Rozetka feedbacks: {e}"}

    seen = set()
    if os.path.exists(RZ_FEEDBACK_SEEN):
        seen = set(open(RZ_FEEDBACK_SEEN, encoding="utf-8").read().split())
    fresh = [f for f in items if str(f.get("id")) not in seen]

    if fresh:
        with open(RZ_FEEDBACK_SEEN, "a", encoding="utf-8") as fh:
            for f in fresh:
                fh.write(f"{f.get('id')}\n")
        lines = []
        for f in fresh[:3]:
            txt = re.sub(r"<[^>]+>", " ", f.get("text") or "")
            txt = " ".join(html.unescape(txt).split())[:180]
            lines.append(f"• {txt}")
        tg("💬 <b>Нові повідомлення Rozetka</b>\n\n" + "\n\n".join(lines))
        return {"ok": False, "msg": f"нових повідомлень: {len(fresh)}"}
    return {"ok": True, "msg": f"нових немає (всього {len(items)})"}

def check_carvol_rozetka_feed() -> dict:
    """Фід Carvol для Rozetka: свіжість, розмір і те, чи публікація доїхала.

    Постачальник Carvol — читання й тільки читання: перевірка нічого не
    перезбирає й не публікує, лише дивиться на готовий файл і на GitHub.

    Три різні відмови, які не заміняють одна одну:
      * файл не оновився (не відпрацював cron о 07:15 або впав збір);
      * файл оновився, але обрізаний (обрив запису — Rozetka зніме з продажу
        все, чого раптом не стало у прайсі);
      * файл цілий, а на GitHub лежить учорашній — саме це й ставалось.
    """
    problems = []
    if os.path.exists(CARVOL_RZ_FEED):
        age_h = (time.time() - os.path.getmtime(CARVOL_RZ_FEED)) / 3600
        if age_h > CARVOL_RZ_MAX_AGE_H:
            problems.append(f"фід Carvol не оновлювався {age_h:.0f} год")
        size = os.path.getsize(CARVOL_RZ_FEED)
        if size < CARVOL_RZ_MIN_BYTES:
            problems.append(f"фід Carvol обрізаний: {size} Б")
    else:
        problems.append("локального фіду Carvol немає")

    bad = probe_raw(CARVOL_RZ_RAW_URL, CARVOL_RZ_MIN_BYTES, "Carvol")
    if bad:
        problems.append(bad)

    pub_h = published_age_h(CARVOL_RZ_API_URL)
    if pub_h > CARVOL_RZ_MAX_AGE_H:
        problems.append(f"опублікована версія Carvol старша за "
                        f"{CARVOL_RZ_MAX_AGE_H} год ({pub_h:.0f}) — push не доїхав")

    if problems:
        key = "; ".join(problems)[:200]
        last = ""
        if os.path.exists(CARVOL_RZ_FLAG):
            try:
                last = Path(CARVOL_RZ_FLAG).read_text().strip()
            except Exception:
                pass
        if key != last:
            tg(f"🚨 <b>Watchdog Carvol Rozetka</b>: {key}")
            Path(CARVOL_RZ_FLAG).write_text(key)
        log(f"[carvol-rz] ПРОБЛЕМА: {key}")
        return {"ok": False, "msg": key[:80]}

    if os.path.exists(CARVOL_RZ_FLAG):
        os.remove(CARVOL_RZ_FLAG)
    pub = "невідомо" if pub_h < 0 else f"{pub_h:.0f} год тому"
    log(f"[carvol-rz] фід свіжий, raw-URL доступний, опубліковано {pub}")
    return {"ok": True, "msg": "feed ok"}


# ── report every 6h ───────────────────────────────────────────────────────────

def should_report() -> bool:
    if not os.path.exists(STATE_FILE):
        return True
    try:
        last = float(Path(STATE_FILE).read_text().strip())
        return (time.time() - last) >= REPORT_INTERVAL.total_seconds()
    except Exception:
        return True


def save_report_ts():
    Path(STATE_FILE).write_text(str(time.time()))


def send_report(git_r: dict, svc_r: dict, cron_r: dict, sync_r: dict,
                noire_r: dict, noire_rz: dict, noire_prom: dict,
                carvol_rz: dict):
    """Шестигодинний звіт: сервіси, git, cron, sync і ВСІ ЧОТИРИ фіди.

    Фіди додано 01.09.2026. Доти звіт їх не бачив, і це давало найгіршу з
    можливих відповідей: «Watchdog OK» о тій самій годині, коли фід Rozetka
    відстав на дев'ять годин або публікація Carvol не доїхала до GitHub. Про
    фіди дізнавались лише з негайних тривог, а ті надсилаються ОДИН раз на
    несправність (дедуплікація по файлу-прапорцю) — пропустив сповіщення о
    03:00, і наступні шість годин система мовчить.

    Рядок друкується по кожному фіду ЗАВЖДИ, і в доброму звіті теж. Перелік
    лише проблемних читався б як «решта гаразд», хоча насправді означав би
    ще й «перевірка не відпрацювала»: зниклий рядок видно, зниклу проблему —
    ні.
    """
    ts = datetime.now().strftime("%d.%m %H:%M")

    svc_parts  = [f"{'✅' if active else '❌'} {svc}" for svc, active in svc_r.get("services", {}).items()]
    git_ok     = git_r["ok"]
    sync_ok    = sync_r["ok"]
    svc_ok     = svc_r["ok"]

    # Порядок той самий, що й у логах main() — щоб звіт і лог читались поруч.
    feeds = [
        ("Єпіцентр NOIRE",  noire_r),
        ("Rozetka NOIRE",   noire_rz),
        ("Prom NOIRE",      noire_prom),
        ("Carvol → Rozetka", carvol_rz),
    ]
    feed_lines = [
        f"{'✅' if r['ok'] else '❌'} {label}"
        + ("" if r["ok"] else f" ({r['msg'][:60]})")
        for label, r in feeds
    ]
    feeds_ok = all(r["ok"] for _, r in feeds)

    # Фіди входять у загальний присуд, а не дописуються збоку: заголовок
    # «Watchdog OK» над мертвим фідом — саме те, що ця правка прибирає.
    all_ok = svc_ok and git_ok and sync_ok and cron_r["ok"] and feeds_ok

    if all_ok:
        status_line = "  ".join(svc_parts) + ("  ✅ sync" if sync_ok else "  ❌ sync")
        msg = (f"🔔 <b>Watchdog OK</b> [{ts}]\n{status_line}\n"
               f"<b>Фіди:</b>\n" + "\n".join(feed_lines))
    else:
        problems = []
        for svc, active in svc_r.get("services", {}).items():
            if not active:
                problems.append(f"❌ {svc}")
        if not git_ok:
            problems.append(f"❌ git sync ({git_r['msg'][:40]})")
        if not sync_ok:
            problems.append(f"❌ rozetka sync ({sync_r['msg'][:40]})")
        if not cron_r["ok"]:
            problems.append(f"⚠️ cron ({cron_r['msg'][:40]})")
        msg = (f"🚨 <b>Watchdog</b> [{ts}]\n" + "\n".join(problems)
               + ("\n" if problems else "")
               + "<b>Фіди:</b>\n" + "\n".join(feed_lines))

    save_report_ts()
    tg(msg)
    log(f"[report] 6h звіт ({'OK' if all_ok else 'PROBLEMS'}) відправлено в Telegram")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    log("=== Watchdog START ===")

    git_r  = check_git()
    cron_r = check_cron()
    svc_r  = check_services()
    sync_r = check_sync_log()
    noire_r = check_noire_feed()
    noire_rz = check_noire_rozetka_feed()
    noire_prom = check_noire_prom_feed()
    carvol_rz = check_carvol_rozetka_feed()
    rz_msg    = check_rozetka_messages()

    log(f"[git]  ok={git_r['ok']}  {git_r['msg']}")
    log(f"[cron] ok={cron_r['ok']} {cron_r['msg']}")
    log(f"[svc]  ok={svc_r['ok']}  {svc_r.get('services')}")
    log(f"[sync] ok={sync_r['ok']} {sync_r['msg']}")
    log(f"[noire] ok={noire_r['ok']} {noire_r['msg']}")
    log(f"[noire-rz] ok={noire_rz['ok']} {noire_rz['msg']}")
    log(f"[noire-prom] ok={noire_prom['ok']} {noire_prom['msg']}")
    log(f"[carvol-rz] ok={carvol_rz['ok']} {carvol_rz['msg']}")
    log(f"[rz-msg] ok={rz_msg['ok']} {rz_msg['msg']}")

    if should_report():
        send_report(git_r, svc_r, cron_r, sync_r,
                    noire_r, noire_rz, noire_prom, carvol_rz)

    log("=== Watchdog END ===")


if __name__ == "__main__":
    main()
