"""Генератор YML-фіду для EVA Маркетплейс.

Формат перевірено на реальному прикладі з довідки продавця
(`docs/research/EVA_MARKETPLACE.md` §3, sellersupport.eva.ua). Лише чисті
функції: дані й довідник категорій дає викликач, тут немає ні БД, ні мережі.

Правила стандарту (з довідки, дослівно):
  * url прайсу статичний — не тут, це відповідальність деплою;
  * кодування UTF-8;
  * заборонені недруковані символи ASCII 0–31, крім 9/10/13 (таб, LF, CR);
  * `"`, `&`, `<`, `>`, `'` у тексті — екранувати кодами (тегів це не стосується);
  * id товарів і категорій не можна міняти після додавання — тому SKU і
    categoryId викликач має підставляти вже стабільними, тут вони не чіпаються.
"""
import re

MAX_PICTURES = 15
_CONTROL_CHARS = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f]')
_ESCAPES = (('&', '&amp;'), ('<', '&lt;'), ('>', '&gt;'), ('"', '&quot;'), ("'", '&apos;'))


def esc_text(t) -> str:
    """Текст поза тегами: керівні символи прибрати, спецсимволи — кодами."""
    if t is None:
        return ''
    s = _CONTROL_CHARS.sub('', str(t))
    for a, b in _ESCAPES:
        s = s.replace(a, b)
    return s


def cdata(t) -> str:
    """CDATA-блок для опису. `]]>`  усередині — єдине, що ламає CDATA."""
    s = _CONTROL_CHARS.sub('', str(t)) if t is not None else ''
    return '<![CDATA[' + s.replace(']]>', ']]]]><![CDATA[>') + ']]>'


def build_offer(item: dict) -> str:
    """Один `<offer>` за прикладом довідки. `item`:
    sku, name_ru, name_ua, price, price_old, qty, vendor, category_id,
    pictures (список), description_ru, description_ua, params (dict).
    """
    sku = item.get('sku')
    price = item.get('price')
    pics = item.get('pictures') or []
    if not sku:
        raise ValueError('sku обовʼязковий')
    if not price:
        raise ValueError('price обовʼязковий і мусить бути додатним')
    if not pics:
        raise ValueError('потрібне хоча б одне фото')

    qty = item.get('qty') or 0
    available = 'true' if qty and qty > 0 else 'false'
    lines = [f'      <offer id="{esc_text(sku)}" available="{available}">',
             f'        <price>{round(price)}</price>']
    if item.get('price_old'):
        lines.append(f'        <price_old>{round(item["price_old"])}</price_old>')
    lines += [f'        <stock_quantity>{int(qty)}</stock_quantity>',
             '        <currencyId>UAH</currencyId>',
             f'        <categoryId>{esc_text(item.get("category_id"))}</categoryId>']
    for url in pics[:MAX_PICTURES]:
        lines.append(f'        <picture>{esc_text(url)}</picture>')
    lines += [f'        <vendor>{esc_text(item.get("vendor"))}</vendor>',
             f'        <article>{esc_text(sku)}</article>',
             f'        <name>{esc_text(item.get("name_ru"))}</name>',
             f'        <name_ua>{esc_text(item.get("name_ua"))}</name_ua>',
             f'        <description>{cdata(item.get("description_ru"))}</description>',
             f'        <description_ua>{cdata(item.get("description_ua"))}</description_ua>']
    for name, value in (item.get('params') or {}).items():
        lines.append(f'        <param name="{esc_text(name)}">{esc_text(value)}</param>')
    lines.append('      </offer>')
    return '\n'.join(lines)


def build_categories(categories: dict) -> str:
    """`categories` — {categoryId: назва}. Порожній довідник — ValueError:
    фід без жодної категорії структурно невалідний."""
    if not categories:
        raise ValueError('довідник категорій порожній')
    lines = ['<categories>']
    for cid, name in categories.items():
        lines.append(f'  <category id="{esc_text(cid)}">{esc_text(name)}</category>')
    lines.append('</categories>')
    return '\n'.join(lines)


def build_feed(items: list, categories: dict, *, shop_name: str, shop_company: str,
               shop_url: str, now: str, return_skipped: bool = False):
    """Повний документ. Товар, категорії якого нема в довіднику, — пропускається
    (не падаємо на всьому фіді через одну неправильну категорію) і потрапляє
    у `skipped`, якщо `return_skipped=True`.
    """
    if not items:
        raise ValueError('items порожній — писати нема чого')
    offers, skipped = [], []
    for it in items:
        cid = str(it.get('category_id'))
        if cid not in categories:
            skipped.append((it.get('sku'), f'категорія {cid} відсутня в довіднику'))
            continue
        offers.append(build_offer(it))

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{esc_text(now)}">',
        '<shop>',
        f'<name>{esc_text(shop_name)}</name>',
        f'<company>{esc_text(shop_company)}</company>',
        f'<url>{esc_text(shop_url)}</url>',
        '<currencies>',
        '<currency rate="1" id="UAH"/>',
        '</currencies>',
        build_categories(categories),
        '<offers>',
        *offers,
        '</offers>',
        '</shop>',
        '</yml_catalog>',
    ]
    xml = '\n'.join(parts)
    return (xml, skipped) if return_skipped else xml
