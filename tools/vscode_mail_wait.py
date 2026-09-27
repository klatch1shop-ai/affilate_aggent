"""Чекає на НОВЕ повідомлення від власника й завершується, щойно воно прийде.

Навіщо. 27.09.2026 я зробив канал «власник → Claude» і оголосив його робочим,
а він таким не був: скринька — це файл на сервері, і я мав САМ згадати піти
його прочитати. Власник написав о 12:06, я побачив о 13:40. Це не канал, це
сподівання на мою уважність.

Тепер інакше: цей скрипт запускається у фоні й просто чекає. Щойно у скриньці
зʼявляється лист, він завершується — і оболонка сповіщає мене про завершення
фонової задачі. Тобто прокидаюсь я, а не сподіваюсь згадати.

    venv/bin/python tools/vscode_mail_wait.py            # чекати без обмеження
    venv/bin/python tools/vscode_mail_wait.py --timeout 3600
"""
import argparse
import os
import subprocess
import sys
import time

from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
load_dotenv(os.path.join(BASE, '.env'))

from helper import vscode_inbox                                     # noqa: E402

HOST = os.getenv('VSCODE_INBOX_HOST', 'tek@192.168.3.28')
REMOTE = os.getenv('VSCODE_INBOX_REMOTE', '/home/tek/helper_data/vscode_inbox.jsonl')


def fetch(host, path, timeout=30):
    if not host:
        try:
            with open(path, encoding='utf-8') as f:
                return f.read()
        except OSError:
            return ''
    try:
        r = subprocess.run(['ssh', '-o', 'BatchMode=yes', host,
                            f'cat {path} 2>/dev/null || true'],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ''
    except Exception:
        # Тимчасовий збій мережі не має завершувати чекання: інакше вартовий
        # «прокинеться» без листа й розбудить мене намарно.
        return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--every', type=int, default=30, help='як часто зазирати, секунд')
    ap.add_argument('--timeout', type=int, default=0, help='0 = без обмеження')
    ap.add_argument('--host', default=HOST)
    ap.add_argument('--path', default=REMOTE)
    a = ap.parse_args()

    start = time.time()
    seen = len(vscode_inbox.parse_lines(fetch(a.host or None, a.path)))
    print(f'чекаю на нові листи (зараз у скриньці {seen})', flush=True)

    while True:
        if a.timeout and time.time() - start > a.timeout:
            print('час вичерпано, нових листів не було')
            return 1
        time.sleep(a.every)
        entries = vscode_inbox.parse_lines(fetch(a.host or None, a.path))
        if len(entries) > seen:
            fresh = entries[seen:]
            print(f'\n🔔 НОВИХ ЛИСТІВ: {len(fresh)}')
            for letter in fresh:
                print(f"  [{letter.get('ts')} UTC] {letter.get('text')}")
            return 0


if __name__ == '__main__':
    sys.exit(main())
