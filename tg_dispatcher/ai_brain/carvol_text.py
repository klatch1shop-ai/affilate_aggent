"""ТТН від Carvol, надіслані ТЕКСТОМ, а не PDF → наше замовлення Rozetka.

18.09.2026: 17.09 Carvol надіслав номери ТТН двома текстовими повідомленнями;
диспетчер приймав від нього лише PDF і відкинув їх мовчки. Два замовлення
добу стояли без ТТН, а зміст повідомлень не зберігся ніде.

Правило зіставлення суворіше, ніж для PDF (там є рівень «лише за ціною»):
  * кандидати — лише підтверджені замовлення БЕЗ ТТН;
  * номер ТТН перевіряється в НП з ТЕЛЕФОНОМ кожного кандидата: НП віддає
    дані одержувача, лише коли телефон справжній — це і є підтвердження;
  * рівно один підтверджений кандидат → ТТН можна вносити; інакше — людині.

Модуль без мережі: трекінг НП передається функцією `np_lookup(ttn, phone)`.
"""
import re

TTN = re.compile(r'(?<!\d)(\d{14})(?!\d)')
ORDER = re.compile(r'(?<!\d)(\d{9})(?!\d)')


def digits(s):
    return re.sub(r'\D', '', s or '')


def extract_ttns(text):
    """Усі 14-значні номери по порядку, без повторів."""
    seen, out = set(), []
    for t in TTN.findall(text or ''):
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def extract_order_ids(text):
    """9-значні номери (номер замовлення Rozetka), що не є частиною ТТН."""
    return [o for o in ORDER.findall(TTN.sub(' ', text or ''))]


def _phone_match(a, b):
    a, b = digits(a)[-9:], digits(b)[-9:]
    return bool(a) and a == b


def resolve(ttn, candidates, np_lookup, order_hint=None):
    """→ (order_id або None, пояснення).

    candidates: [{'order_id', 'phone', 'recipient'}] — підтверджені без ТТН.
    np_lookup(ttn, phone) → dict як np_api.get_ttn_info (recipient_phone, recipient_name, city, error).
    order_hint: номер замовлення, якщо Carvol написав його поруч із ТТН.
    """
    pool = [c for c in candidates if str(c['order_id']) == str(order_hint)] if order_hint else candidates
    if order_hint and not pool:
        return None, f'номер замовлення {order_hint} є в тексті, але серед відкритих без ТТН його немає'
    confirmed = []
    for c in pool:
        info = np_lookup(ttn, c.get('phone') or '') or {}
        if info.get('error'):
            continue
        if _phone_match(info.get('recipient_phone'), c.get('phone')):
            confirmed.append((c, info))
    if len(confirmed) == 1:
        c, info = confirmed[0]
        where = ', '.join(x for x in (info.get('city'), info.get('recipient_name')) if x)
        return c['order_id'], f'НП підтвердила телефон одержувача ({where})'
    if not confirmed:
        return None, f'НП не підтвердила жодного з {len(pool)} кандидатів'
    return None, f'НП підтвердила {len(confirmed)} кандидатів — неоднозначно'


def parse_ttn_command(text):
    """«/ttn 906298386 20451539117101» → ('906298386', '20451539117101'); інакше None."""
    parts = (text or '').split()
    if len(parts) != 3 or not parts[0].lower().startswith('/ttn'):
        return None
    oid, ttn = parts[1], parts[2]
    if not (ORDER.fullmatch(oid) and TTN.fullmatch(ttn)):
        return None
    return oid, ttn


REPLY_ORDER = re.compile(r'Замовлення\s+\S+\s*#\s*(\d{9})|#\s*(\d{9})')


def order_from_reply(reply_text):
    """Номер замовлення з повідомлення бота, на яке відповів Carvol.

    18.09.2026 (скрін від Carvol): вони відповідають (reply) на наше повідомлення
    «📦 Замовлення Розетка #906298386 …» самим номером ТТН. Номер замовлення —
    у повідомленні, на яке відповіли; це найточніше джерело.
    """
    m = REPLY_ORDER.search(reply_text or '')
    return (m.group(1) or m.group(2)) if m else None
