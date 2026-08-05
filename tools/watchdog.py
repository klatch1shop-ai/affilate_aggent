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
  5. Telegram звіт кожні 6 годин
"""

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
CRON_FLAG       = "/tmp/watchdog_cron_warned.flag"
SYNC_ERROR_FLAG = "/tmp/watchdog_sync_error_last.txt"

# NOIRE: опублікований фід має бути доступним і не старішим за добу
NOIRE_FEED      = "/home/tek/agent-system/output/noire_epicentr_phase1.xml"
NOIRE_RAW_URL   = ("https://raw.githubusercontent.com/klatch1shop-ai/"
                   "noire-feed/main/noire_epicentr.xml")
NOIRE_MAX_AGE_H = 26          # 2-годинний цикл + запас на добовий простій
NOIRE_FLAG      = "/tmp/watchdog_noire_last.txt"

CRON_CHECKS = [
    ("rozetka_github_sync.py", "cd /home/tek/agent-system"),
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


# ── check 1: git ──────────────────────────────────────────────────────────────

def check_git() -> dict:
    rc, stdout, _ = run("git status --porcelain")
    if rc != 0:
        return {"ok": False, "msg": "git status failed"}

    if not stdout:
        log("[git] репо чисте")
        return {"ok": True, "msg": "clean"}

    changed = len(stdout.splitlines())
    log(f"[git] {changed} змінених файлів — авто-коміт...")

    ts  = datetime.now().strftime("%Y-%m-%d %H:%M")
    rc2, _, err2 = run(f'git add -A && git commit -m "auto: watchdog sync {ts}"')
    if rc2 != 0:
        log(f"[git] commit failed: {err2}")
        return {"ok": False, "msg": f"commit failed: {err2[:80]}"}

    # Push виконує тільки розробник вручну — watchdog лише комітить локально
    log(f"[git] авто-коміт (без push): {changed} файлів")
    return {"ok": True, "msg": f"auto-committed {changed} files (no push)"}


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

def check_sync_log() -> dict:
    if not os.path.exists(SYNC_LOG):
        return {"ok": True, "msg": "no log yet"}

    try:
        lines = Path(SYNC_LOG).read_text(errors="replace").splitlines()
        lines = [l.strip() for l in lines if l.strip()]
        if not lines:
            return {"ok": True, "msg": "empty"}

        last = lines[-1]
        if "FAILED" in last.upper() or ("ERROR" in last.upper() and "WARNING" not in last.upper()):
            log(f"[sync] FAILED виявлено: {last}")

            # Dedup: не відправляємо той самий алерт поки помилка не зміниться
            last_sent = ""
            if os.path.exists(SYNC_ERROR_FLAG):
                try:
                    last_sent = Path(SYNC_ERROR_FLAG).read_text().strip()
                except Exception:
                    pass

            err_key = last[:200]
            if err_key != last_sent:
                tg(f"🚨 <b>Watchdog</b>: rozetka_sync_cron FAILED!\n<code>{last[:200]}</code>")
                Path(SYNC_ERROR_FLAG).write_text(err_key)
                log(f"[sync] алерт відправлено в Telegram")
            else:
                log(f"[sync] та сама помилка — алерт вже надсилали, пропускаємо дублікат")

            return {"ok": False, "msg": last[:80]}

        # Успішний run — скидаємо прапор щоб наступна помилка знову тригернула алерт
        if os.path.exists(SYNC_ERROR_FLAG):
            os.remove(SYNC_ERROR_FLAG)
            log(f"[sync] прапор помилки скинуто (успішний run)")
        return {"ok": True, "msg": last[:80]}
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

    try:
        r = requests.head(NOIRE_RAW_URL, timeout=30, allow_redirects=True)
        if r.status_code != 200:
            problems.append(f"raw-URL віддає HTTP {r.status_code}")
        elif int(r.headers.get("content-length", 0)) < 1_000_000:
            problems.append("raw-URL віддає підозріло малий файл")
    except Exception as e:
        problems.append(f"raw-URL недоступний: {type(e).__name__}")

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


def send_report(git_r: dict, svc_r: dict, cron_r: dict, sync_r: dict):
    ts = datetime.now().strftime("%d.%m %H:%M")

    svc_parts  = [f"{'✅' if active else '❌'} {svc}" for svc, active in svc_r.get("services", {}).items()]
    git_ok     = git_r["ok"]
    sync_ok    = sync_r["ok"]
    svc_ok     = svc_r["ok"]
    all_ok     = svc_ok and git_ok and sync_ok and cron_r["ok"]

    if all_ok:
        status_line = "  ".join(svc_parts) + ("  ✅ sync" if sync_ok else "  ❌ sync")
        msg = f"🔔 <b>Watchdog OK</b> [{ts}]\n{status_line}"
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
        msg = f"🚨 <b>Watchdog</b> [{ts}]\n" + "\n".join(problems)

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

    log(f"[git]  ok={git_r['ok']}  {git_r['msg']}")
    log(f"[cron] ok={cron_r['ok']} {cron_r['msg']}")
    log(f"[svc]  ok={svc_r['ok']}  {svc_r.get('services')}")
    log(f"[sync] ok={sync_r['ok']} {sync_r['msg']}")
    log(f"[noire] ok={noire_r['ok']} {noire_r['msg']}")

    if should_report():
        send_report(git_r, svc_r, cron_r, sync_r)

    log("=== Watchdog END ===")


if __name__ == "__main__":
    main()
