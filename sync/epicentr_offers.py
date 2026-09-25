"""Ядро синхронізації офферів; транспорт передається ззовні."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import sqlite3

BATCH_SIZE = 200
RATE_LIMIT = 120
RATE_WINDOW = 120.0
AVAILABILITY = ('in_stock', 'under_the_order', 'not_available')
MODES = ('off', 'dry', 'live')
_STATUSES = ('enqueued', 'processed', 'skipped', 'forbidden', 'stale')


class EpicentrError(Exception):
    """Помилка транспорту або відповіді Епіцентру."""


class EpicentrAuthError(EpicentrError):
    """Відсутня або відхилена авторизація."""


def to_price(value) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        number = Decimal(str(value).strip().replace(',', '.'))
        if not number.is_finite() or number <= 0:
            return None
        number = number.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return number if number > 0 else None
    except InvalidOperation:
        return None


def desired_state(rows: list[dict]) -> tuple[dict, list[dict]]:
    # Спершу усуваємо дублікати: навіть заблокований останній рядок замінює попередній.
    latest = {}
    for row in rows:
        latest[(row.get('sku') or '').strip()] = row
    desired, blocked = {}, []
    for sku, row in latest.items():
        price, floor = to_price(row.get('price')), to_price(row.get('floor'))
        available = row.get('available')
        availability = ('in_stock' if available is True else
                        'not_available' if available is False else None)
        reason = None
        if not sku:
            reason = 'no_sku'
        elif price is not None and floor is not None and price < floor:
            reason = 'below_floor'
        elif price is None and availability is None:
            reason = 'nothing_to_send'
        if reason:
            blocked.append({'sku': sku, 'reason': reason})
        else:
            desired[sku] = {'price': price, 'availability': availability}
    return desired, blocked


def diff(desired: dict, sent: dict, forbidden=None) -> list[dict]:
    forbidden = forbidden or {}
    changes = []
    for sku in sorted(desired):
        if sku in forbidden and all(
                forbidden[sku].get(field) == desired[sku].get(field)
                for field in ('price', 'availability')):
            continue
        item = {'sku': sku}
        for field in ('price', 'availability'):
            value = desired[sku].get(field)
            if value is not None and value != sent.get(sku, {}).get(field):
                item[field] = value
        if len(item) > 1:
            changes.append(item)
    return changes


def batches(items: list[dict], size: int = BATCH_SIZE) -> list[list[dict]]:
    if size < 1:
        raise ValueError('Розмір пачки має бути додатним')
    return [items[start:start + size] for start in range(0, len(items), size)]


def build_payload(batch: list[dict]) -> dict:
    items = []
    for change in batch:
        item = {'sku': change['sku']}
        if change.get('price') is not None:
            item['prices'] = {'price': float(change['price'])}
        if change.get('availability') is not None:
            item['availability'] = change['availability']
        items.append(item)
    return {'items': items}


def parse_results(resp: dict) -> dict:
    if (not isinstance(resp, dict) or not isinstance(resp.get('items'), list)
            or not isinstance(resp.get('requestId'), str) or not resp['requestId']):
        raise EpicentrError('Некоректна відповідь: потрібні items і requestId')
    result = {'request_id': resp['requestId'], 'by_status': {s: [] for s in _STATUSES},
              'errors': {}, 'unknown': []}
    for item in resp['items']:
        if not isinstance(item, dict) or (item.get('sku') is None and 'id' not in item):
            raise EpicentrError('Некоректний запис результату')
        sku = str(item['sku']).strip() if item.get('sku') is not None else str(item['id']).strip()
        status = item.get('status')
        if isinstance(status, str) and status in result['by_status']:
            result['by_status'][status].append(sku)
        else:
            result['unknown'].append(sku)
        if item.get('errors'):
            result['errors'][sku] = item['errors']
    return result


class SentStore:
    """Підтверджені значення та журнал надісланих змін у SQLite."""

    def __init__(self, path=':memory:'):
        self.connection = sqlite3.connect(path)
        self.connection.executescript('''
            CREATE TABLE IF NOT EXISTS sent (
                sku TEXT PRIMARY KEY, price TEXT, availability TEXT
            );
            CREATE TABLE IF NOT EXISTS forbidden (
                sku TEXT PRIMARY KEY, price TEXT, availability TEXT, at TEXT
            );
            CREATE TABLE IF NOT EXISTS pending (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL, sku TEXT NOT NULL,
                price TEXT, availability TEXT, at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'enqueued', errors TEXT,
                UNIQUE(request_id, sku)
            );
        ''')

    def get_all(self) -> dict:
        return {sku: {'price': Decimal(price) if price is not None else None,
                      'availability': availability}
                for sku, price, availability in self.connection.execute(
                    'SELECT sku, price, availability FROM sent')}

    def mark_pending(self, request_id: str, items: list[dict], at: datetime) -> None:
        if at.tzinfo is None or at.utcoffset() is None:
            raise ValueError('Час надсилання має містити часовий пояс')
        timestamp = at.astimezone(timezone.utc).isoformat()
        with self.connection:
            self.connection.executemany('''
                INSERT INTO pending(request_id, sku, price, availability, at)
                VALUES (?, ?, ?, ?, ?) ON CONFLICT(request_id, sku) DO NOTHING
            ''', [(request_id, item['sku'],
                   str(item['price']) if item.get('price') is not None else None,
                   item.get('availability'), timestamp) for item in items])

    def forbidden_map(self) -> dict:
        return {sku: {'price': Decimal(price) if price is not None else None,
                      'availability': availability}
                for sku, price, availability in self.connection.execute(
                    'SELECT sku, price, availability FROM forbidden')}

    def pending_requests(self, now: datetime | None = None, stale_after_days: int = 14) -> list[str]:
        """Без now зберігає стару поведінку: повертає чергу без перевірки давності."""
        if now is not None and (now.tzinfo is None or now.utcoffset() is None):
            raise ValueError('Час перевірки має містити часовий пояс')
        cutoff = (now.astimezone(timezone.utc) - timedelta(days=stale_after_days)
                  if now is not None else None)
        requests = []
        with self.connection:
            rows = self.connection.execute('''
                SELECT request_id, MIN(CASE WHEN status = 'enqueued' THEN at END)
                FROM pending GROUP BY request_id
                HAVING SUM(CASE WHEN status = 'enqueued' THEN 1 ELSE 0 END) > 0
                ORDER BY MIN(sequence)
            ''').fetchall()
            for request_id, earliest in rows:
                if cutoff is not None and datetime.fromisoformat(earliest) < cutoff:
                    self.connection.execute('''
                        UPDATE pending SET status = 'stale'
                        WHERE request_id = ? AND status = 'enqueued'
                    ''', (request_id,))
                else:
                    requests.append(request_id)
        return requests

    def apply_results(self, parsed: dict, now: datetime | None = None) -> None:
        """Старі виклики без now отримують поточний час обробки в UTC."""
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('Час обробки має містити часовий пояс')
        timestamp = now.astimezone(timezone.utc).isoformat()
        with self.connection:
            for status in ('processed', 'skipped', 'forbidden'):
                for sku in parsed['by_status'][status]:
                    row = self.connection.execute('''
                        SELECT price, availability FROM pending
                        WHERE request_id = ? AND sku = ? AND status = 'enqueued'
                    ''', (parsed['request_id'], sku)).fetchone()
                    if row is None:
                        continue
                    if status == 'forbidden':
                        self.connection.execute('''
                            INSERT INTO forbidden(sku, price, availability, at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(sku) DO UPDATE SET
                                price = excluded.price,
                                availability = excluded.availability,
                                at = excluded.at
                        ''', (sku, *row, timestamp))
                    else:
                        self.connection.execute('''
                            INSERT INTO sent(sku, price, availability) VALUES (?, ?, ?)
                            ON CONFLICT(sku) DO UPDATE SET
                                price = COALESCE(excluded.price, sent.price),
                                availability = COALESCE(excluded.availability, sent.availability)
                        ''', (sku, *row))
                    self.connection.execute('''
                        UPDATE pending SET status = ?, errors = ?
                        WHERE request_id = ? AND sku = ?
                    ''', (status, json.dumps(parsed['errors'].get(sku), ensure_ascii=False),
                          parsed['request_id'], sku))


class OffersClient:
    """Переданий HTTP-транспорт зі спільним ковзним лімітом і повторами."""

    def __init__(self, post, get, token, clock, sleep, max_retries=3):
        if not isinstance(token, str) or not token.strip():
            raise EpicentrAuthError('Відсутній токен авторизації')
        if not isinstance(max_retries, int) or max_retries < 0:
            raise ValueError('Кількість повторів має бути невід’ємною')
        self.post, self.get = post, get
        self.headers = {'Authorization': 'Bearer ' + token}
        self.clock, self.sleep = clock, sleep
        self.max_retries = max_retries
        self._requests = []

    def _wait_slot(self):
        while True:
            now = self.clock()
            self._requests = [at for at in self._requests if now - at < RATE_WINDOW]
            if len(self._requests) < RATE_LIMIT:
                self._requests.append(now)
                return
            self.sleep(self._requests[0] + RATE_WINDOW - now)

    def _request(self, path, payload=None):
        url = 'https://merchant-api.epicentrm.com.ua' + path
        for attempt in range(self.max_retries + 1):
            self._wait_slot()
            try:
                if payload is None:
                    status, body = self.get(url, headers=dict(self.headers))
                else:
                    status, body = self.post(url, json=payload, headers=dict(self.headers))
            except Exception:
                # Транспорт може включити заголовок авторизації у власний виняток.
                raise EpicentrError('Помилка HTTP-транспорту') from None
            if not isinstance(status, int):
                raise EpicentrError('Некоректний HTTP-статус')
            if status == 200:
                if not isinstance(body, dict):
                    raise EpicentrError('Некоректне тіло HTTP-відповіді')
                return body
            if status in (401, 403):
                raise EpicentrAuthError(f'Помилка авторизації HTTP {status}')
            if (status == 429 or 500 <= status <= 599) and attempt < self.max_retries:
                self.sleep(2 ** attempt)
                continue
            raise EpicentrError(f'Помилка HTTP {status}')

    def submit(self, payload) -> dict:
        return self._request('/v1/offers', payload)

    def results(self, request_id) -> dict:
        return self._request('/v1/offers/update-results/' + request_id)


def run(rows, store, client, mode: str = 'off') -> dict:
    if mode not in MODES:
        raise ValueError('Невідомий режим синхронізації')
    report = {'mode': mode, 'changes': 0, 'batches': 0, 'blocked': [], 'sent': 0,
              'by_status': {s: 0 for s in _STATUSES}, 'errors': [], 'stopped': False}

    def apply(parsed):
        store.apply_results(parsed, datetime.now(timezone.utc))
        for status, skus in parsed['by_status'].items():
            report['by_status'][status] += len(skus)
        # Деталі відмов зберігаються в SQLite; звіт не копіює довільні дані API.
        for sku in parsed['errors']:
            report['errors'].append(f'Помилка обробки артикулу {sku}')
        for sku in parsed['unknown']:
            report['errors'].append(f'Невідомий статус артикулу {sku}')

    if mode == 'live':
        for request_id in store.pending_requests(datetime.now(timezone.utc)):
            try:
                parsed = parse_results(client.results(request_id))
                if parsed['request_id'] != request_id:
                    raise EpicentrError('Ідентифікатор результату не відповідає запиту')
                apply(parsed)
            except EpicentrAuthError as error:
                report['errors'].append(str(error))
                report['stopped'] = True
                break
            except EpicentrError as error:
                report['errors'].append(str(error))

    desired, report['blocked'] = desired_state(rows)
    changes = diff(desired, store.get_all(), store.forbidden_map())
    parts = batches(changes)
    report['changes'], report['batches'] = len(changes), len(parts)
    if mode == 'dry':
        report['payloads'] = [build_payload(part) for part in parts]
    if mode != 'live' or report['stopped']:
        return report
    for part in parts:
        try:
            response = client.submit(build_payload(part))
            report['sent'] += len(part)
            parsed = parse_results(response)
            store.mark_pending(parsed['request_id'], part, datetime.now(timezone.utc))
            apply(parsed)
        except EpicentrAuthError as error:
            report['errors'].append(str(error))
            report['stopped'] = True
            break
        except EpicentrError as error:
            report['errors'].append(str(error))
    return report
