"""
Order Agent Daemon — нескінченний цикл з watchdog
Запускається через systemd, перезапускається автоматично
"""
import sys, os, time, requests, traceback
sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv; load_dotenv('/home/tek/agent-system/.env')
from loguru import logger

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_ADMIN = os.getenv('TELEGRAM_ADMIN_ID')
INTERVAL = 300  # 5 хвилин

def tg(text: str):
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={'chat_id': TELEGRAM_ADMIN, 'text': text, 'parse_mode': 'HTML'},
            timeout=10
        )
    except:
        pass

def main():
    tg('🟢 <b>Order Agent запущено</b>\nАвтоматична обробка замовлень активна\nІнтервал: 5 хвилин')
    logger.info('=== Order Agent Daemon старт ===')
    
    consecutive_errors = 0
    
    while True:
        try:
            from agents.orders.order_agent import process_orders
            process_orders()
            consecutive_errors = 0
            
        except Exception as e:
            consecutive_errors += 1
            error_msg = traceback.format_exc()
            logger.error(f'Помилка #{consecutive_errors}: {e}')
            
            tg(f'⚠️ <b>Order Agent помилка #{consecutive_errors}</b>\n{str(e)[:200]}')
            
            if consecutive_errors >= 5:
                tg('🔴 <b>Order Agent критична помилка!</b>\n5 помилок підряд — перезапуск через systemd')
                sys.exit(1)  # systemd перезапустить
        
        logger.info(f'Очікуємо {INTERVAL} сек...')
        time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
