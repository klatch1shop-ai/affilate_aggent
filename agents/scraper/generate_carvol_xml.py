import os, sys, json
from datetime import datetime
from loguru import logger

sys.path.append('/home/tek/agent-system')
from dotenv import load_dotenv
load_dotenv('/home/tek/agent-system/.env')
from shared.utils.db import get_connection
from agents.scraper.carvol_category_map import CATEGORY_MAP

SHOP_NAME = "klatch1 shop"
SHOP_COMPANY = "3721108"
SHOP_URL = "https://cs4053918.prom.ua/"

def escape_xml(text: str) -> str:
    if not text: return ""
    return (str(text)
        .replace('&', '&amp;')
        .replace('"', '&quot;')
        .replace("'", '&apos;')
        .replace('<', '&lt;')
        .replace('>', '&gt;'))

def generate_xml(output_file: str = "data/carvol_rozetka.xml"):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT external_id, article, name_ua, description_ua,
               vendor, price, category_id, pictures, params,
               stock_quantity, available
        FROM carvol_products
        WHERE has_params = true AND price > 0 AND available = true
        ORDER BY category_id, vendor, article
    """)
    products = [dict(r) for r in cur.fetchall()]
    cur.close(); conn.close()
    logger.info(f"[XML] {len(products)} products")

    categories_used = {}
    for p in products:
        cat_id, cat_name, rz_id = CATEGORY_MAP.get(p['category_id'], CATEGORY_MAP['default'])
        categories_used[cat_id] = (cat_name, rz_id)

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<yml_catalog date="{datetime.now().strftime("%Y-%m-%d %H:%M")}">',
        '  <shop>',
        f'    <name>{SHOP_NAME}</name>',
        f'    <company>{SHOP_COMPANY}</company>',
        f'    <url>{SHOP_URL}</url>',
        '    <currencies><currency id="UAH" rate="1"/></currencies>',
        '    <categories>',
    ]
    for cat_id, (cat_name, rz_id) in sorted(categories_used.items()):
        lines.append(f'      <category id="{cat_id}" rz_id="{rz_id}">{cat_name}</category>')
    lines += ['    </categories>', '    <offers>']

    names_used = set()
    processed = 0

    for p in products:
        sku = str(p['external_id'])
        article = escape_xml(p['article'] or sku)
        name_ua = escape_xml(p['name_ua'] or '')

        orig = name_ua
        counter = 1
        while name_ua in names_used:
            name_ua = f"{orig} {counter}"
            counter += 1
        names_used.add(name_ua)

        desc = escape_xml(p['description_ua'] or '')
        vendor = escape_xml(p['vendor'] or '')
        price = int(float(p['price']))
        stock = int(p['stock_quantity'] or 0)
        cat_id = CATEGORY_MAP.get(p['category_id'], CATEGORY_MAP['default'])[0]

        pics = p['pictures'] or []
        if isinstance(pics, str): pics = json.loads(pics)
        params = p['params'] or {}
        if isinstance(params, str): params = json.loads(params)

        lines.append(f'      <offer id="{sku}" available="true">')
        lines.append(f'        <price>{price}</price>')
        lines.append(f'        <currencyId>UAH</currencyId>')
        lines.append(f'        <categoryId>{cat_id}</categoryId>')
        for url in pics[:10]:
            if url: lines.append(f'        <picture>{url}</picture>')
        lines.append(f'        <vendor>{vendor}</vendor>')
        lines.append(f'        <article>{article}</article>')
        lines.append(f'        <stock_quantity>{stock}</stock_quantity>')
        lines.append(f'        <name_ua>{name_ua}</name_ua>')
        lines.append(f'        <name>{name_ua}</name>')
        if desc:
            lines.append(f'        <description_ua><![CDATA[<p>{desc}</p>]]></description_ua>')
        for k, v in params.items():
            if k and v and str(v).strip():
                lines.append(f'        <param name="{escape_xml(str(k))}">{escape_xml(str(v))}</param>')
        lines.append('      </offer>')
        processed += 1

    lines += ['    </offers>', '  </shop>', '</yml_catalog>']

    os.makedirs('data', exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    size_kb = os.path.getsize(output_file) // 1024
    logger.success(f"[XML] → {output_file} ({size_kb}KB, {processed} offers)")
    return output_file, processed

if __name__ == "__main__":
    file, count = generate_xml()
    print(f"\n✅ XML: {file}")
    print(f"   Товарів: {count}")
    print(f"   Розмір: {os.path.getsize(file)//1024}KB")
