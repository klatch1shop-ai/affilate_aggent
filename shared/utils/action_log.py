"""
shared/utils/action_log.py
===========================
Єдиний журнал дій агентів замовлень — на всі майданчики.

Навіщо: аудит 31.08.2026 показав, що на питання «що робилось із замовленням
#904651025 і де воно спинилось» відповіді не було. Замовлення з безготівковою
оплатою агент БАЧИВ, але не обробляв — і сліду про це не лишилось ніде.

Тому головне правило цього журналу:

    ЗАПИСУВАТИ НЕ ЛИШЕ ДІЇ, А Й СВІДОМІ ПРОПУСКИ.

«Побачив #904651025 у статусі 26, не обробляю, бо сценарію немає» — це запис,
який робить пропущений випадок видимим одразу, а не через тиждень підвислих
замовлень.

Використання:
    from shared.utils.action_log import log_action
    log_action('rozetka', 'order_agent', order_id=904651025,
               step='pick', result='skip',
               reason='статус 26 (обробляється менеджером) — сценарію немає',
               extra={'payment_type': 'no_cash'})

Журнал НЕ має права зламати роботу агента: будь-яка помилка запису
проковтується й лише пишеться в лог. Агент важливіший за журнал.
"""
import os
import sys
import json
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(BASE)

TABLE = 'agent_action_log'

DDL = f'''
CREATE TABLE IF NOT EXISTS {TABLE} (
    id           BIGSERIAL PRIMARY KEY,
    ts           TIMESTAMP    NOT NULL DEFAULT NOW(),
    marketplace  VARCHAR(24)  NOT NULL,   -- rozetka / epicentr / prom
    agent        VARCHAR(48)  NOT NULL,   -- який процес пише
    order_id     VARCHAR(64),             -- рядком: id майданчиків різного типу
    step         VARCHAR(48)  NOT NULL,   -- pick / confirm / supplier / ttn / status
    result       VARCHAR(16)  NOT NULL,   -- ok / skip / fail
    reason       TEXT,                    -- ЧОМУ саме так; для skip обовʼязково
    extra        JSONB
);
CREATE INDEX IF NOT EXISTS {TABLE}_order_idx ON {TABLE} (order_id);
CREATE INDEX IF NOT EXISTS {TABLE}_ts_idx    ON {TABLE} (ts DESC);
CREATE INDEX IF NOT EXISTS {TABLE}_mp_idx    ON {TABLE} (marketplace, step, result);
'''

RESULTS = ('ok', 'skip', 'fail')


def ensure_table():
    from shared.utils.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(DDL)
    conn.commit()
    cur.close()
    conn.close()


def log_action(marketplace, agent, step, result,
               order_id=None, reason=None, extra=None):
    """Записує один крок. Ніколи не кидає виняток назовні."""
    if result not in RESULTS:
        result = 'fail'
    try:
        from shared.utils.db import get_connection
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            f'INSERT INTO {TABLE} (marketplace, agent, order_id, step, result, reason, extra)'
            f' VALUES (%s,%s,%s,%s,%s,%s,%s)',
            (marketplace, agent, str(order_id) if order_id is not None else None,
             step, result, reason,
             json.dumps(extra, ensure_ascii=False, default=str) if extra else None))
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        try:
            from loguru import logger
            logger.warning(f'action_log: {e}')
        except Exception:
            print(f'action_log: {e}', file=sys.stderr)
        return False


def order_history(order_id):
    """Уся історія одного замовлення — те, чого бракувало під час аудиту."""
    from shared.utils.db import get_connection
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(f'SELECT ts, marketplace, agent, step, result, reason, extra'
                f' FROM {TABLE} WHERE order_id=%s ORDER BY ts', (str(order_id),))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


if __name__ == '__main__':
    ensure_table()
    print(f'таблиця {TABLE} готова')
