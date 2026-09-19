#!/usr/bin/env python3
"""Щоденний бекап Postgres (cron на usa1). Логіка — ops/pg_backup.py (TASK-08, тести).

Аудит 19.09.2026 (docs/SYSTEM_DESIGN_AUDIT.md п.1): база без жодного бекапу. Тут —
лише справжній запуск команд і тривога в Telegram, якщо бекап не вдався.
Копію на ноутбук забирає сам ноутбук (rsync через ssh), бо копія на тому ж диску
від збою диска не рятує.

    venv/bin/python ops/run_pg_backup.py            # у ~/backups/pg
"""
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
load_dotenv(BASE / '.env')
from ops.pg_backup import backup  # noqa: E402

CONTAINER = 'agent_postgres'
BACKUP_DIR = Path(os.getenv('PG_BACKUP_DIR', str(Path.home() / 'backups' / 'pg')))


def run(cmd, stdout_path=None, stdin_path=None):
    out = open(stdout_path, 'wb') if stdout_path else subprocess.DEVNULL
    inp = open(stdin_path, 'rb') if stdin_path else subprocess.DEVNULL
    try:
        r = subprocess.run(cmd, stdout=out, stdin=inp, stderr=subprocess.PIPE, timeout=1800)
        return r.returncode, r.stderr.decode(errors='replace')[-500:]
    finally:
        for f in (out, inp):
            if hasattr(f, 'close'):
                f.close()


def env_of_container(name):
    r = subprocess.run(['docker', 'exec', CONTAINER, 'printenv', name], capture_output=True, text=True)
    return r.stdout.strip()


def alert(text):
    tok, chat = os.getenv('TG_BOT_TOKEN'), os.getenv('TG_CHAT_ID')
    if tok and chat:
        try:
            requests.post(f'https://api.telegram.org/bot{tok}/sendMessage',
                          json={'chat_id': chat, 'text': text}, timeout=15)
        except requests.RequestException:
            pass


def main():
    res = backup(run, str(BACKUP_DIR), CONTAINER, env_of_container('POSTGRES_USER'),
                 env_of_container('POSTGRES_DB'), datetime.now(timezone.utc))
    print(res)
    if not res['ok']:
        alert(f"⚠️ Бекап бази НЕ вдався: {res['error']}. Старі копії збережено.")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
