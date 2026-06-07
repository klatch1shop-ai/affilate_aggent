"""
katran_github_sync.py
=====================
Щогодинна синхронізація фіду Катрана → GitHub.

Cron (кожну годину на сервері):
0 * * * * /home/tek/agent-system/venv/bin/python3 /home/tek/agent-system/agents/orders/katran_github_sync.py >> /tmp/katran_sync_cron.log 2>&1
"""
import sys, os, subprocess, requests
from datetime import datetime
from loguru import logger

# Визначаємо корінь проекту відносно цього файлу
REPO_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, REPO_PATH)

from dotenv import load_dotenv
load_dotenv(os.path.join(REPO_PATH, ".env"))

XML_RELATIVE = "data/katran_rozetka.xml"
XML_PATH = os.path.join(REPO_PATH, XML_RELATIVE)
LOG_FILE = "/tmp/katran_github_sync.log"

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TG_ADMIN = os.getenv("TELEGRAM_ADMIN_ID")


def tg_error(msg: str):
    """Надсилає повідомлення адміну тільки при помилці."""
    if not TG_TOKEN or not TG_ADMIN:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_ADMIN, "text": msg, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        logger.warning(f"[Sync] TG send error: {e}")


def git_push(stats: dict) -> bool:
    """Робить git add + commit + push. Повертає True якщо успішно або немає змін."""
    commit_msg = (
        f"sync: katran feed {datetime.now().strftime('%Y-%m-%d %H:%M')} "
        f"({stats['in_stock']} offers)"
    )
    try:
        for cmd in [
            ["git", "add", "-f", XML_RELATIVE],
            ["git", "commit", "-m", commit_msg],
            ["git", "pull", "--rebase"],
            ["git", "push"],
        ]:
            r = subprocess.run(cmd, cwd=REPO_PATH, capture_output=True, text=True)
            if r.returncode != 0:
                combined = r.stdout + r.stderr
                if "nothing to commit" in combined:
                    logger.info("[Sync] Git: немає змін у файлі")
                    return True
                logger.error(f"[Sync] Git {cmd[1]} failed: {combined[:300]}")
                return False
        logger.success("[Sync] Git push OK")
        return True
    except Exception as e:
        logger.error(f"[Sync] Git exception: {e}")
        return False


def main():
    logger.add(LOG_FILE, rotation="10 MB", level="INFO", enqueue=True)
    start = datetime.now()
    logger.info("=== Katran GitHub Sync START ===")

    try:
        # 1. Генеруємо XML з фіду Катрана
        from agents.orders.katran_xml_generator import generate_xml
        file, count, stats = generate_xml(output_file=XML_PATH)

        logger.info(
            f"[Sync] XML готовий: {count} офферів "
            f"(пропущено: наявність={stats['skipped_stock']}, "
            f"ціна={stats['skipped_price']})"
        )

        # 2. Git push
        pushed = git_push(stats)

        duration = (datetime.now() - start).seconds

        if not pushed:
            tg_error(
                f"❌ <b>Katran GitHub Sync: git push failed</b>\n"
                f"Офферів: {count}\n"
                f"Час: {duration}с\n"
                f"Лог: {LOG_FILE}"
            )
            sys.exit(1)

        logger.info(
            f"=== Katran GitHub Sync DONE: {count} офферів, {duration}с ==="
        )

        # Статистика в stdout (видна в cron лозі)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] "
              f"katran_github_sync: OK | "
              f"offers={count} | "
              f"total={stats['total']} | "
              f"skipped_stock={stats['skipped_stock']} | "
              f"skipped_price={stats['skipped_price']} | "
              f"categories={stats['categories']} | "
              f"duration={duration}s")

    except Exception as e:
        duration = (datetime.now() - start).seconds
        logger.error(f"[Sync] Критична помилка: {e}")
        tg_error(
            f"❌ <b>Katran GitHub Sync: помилка</b>\n"
            f"<code>{str(e)[:500]}</code>\n"
            f"Час: {duration}с"
        )
        raise


if __name__ == "__main__":
    main()
