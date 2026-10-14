import sys, collections, csv, os
sys.path.insert(0, '.')
sys.path.insert(0, 'tools')
from tools import katran_rozetka_generator as G
from rozetka_stop_brands import banned, load as load_stop
root = G.fetch()
cats, tree = G.categories()
stop = load_stop()
# категорії, заборонені незалежно від бренду (зі звітів валідації Rozetka)
СТОП_КАТ = {'Пральні машини', 'Блендери', 'Мультиварки', 'Тримери'}
рядки, викинуто = [], collections.Counter()
for it in root.iter('product'):
    g = lambda t: (it.findtext(t) or '').strip()
    if g('stock') != 'есть': continue
    cid = g('categoryId')
    if cid not in cats: continue
    rz, назва, ком = cats[cid]
    if назва in СТОП_КАТ:
        викинуто['стоп-категорія ' + назва] += 1; continue
    vendor = g('vendor') or 'Без бренду'
    bad, why = banned(vendor, назва, stop)
    if bad:
        викинуто['стоп-бренд'] += 1; continue
    if ком is None or float(ком) > 8: continue
    try:
        rrc = float(g('price_rrc') or 0); pdv = float(g('price_pdv') or 0)
    except ValueError: continue
    if not (rrc and pdv): continue
    ком = float(ком); ринок = rrc * 0.93; чисте = ринок * (1 - ком / 100)
    if чисте < pdv: continue
    рядки.append({'артикул': g('artikul') or g('code'), 'назва': g('name')[:80],
                  'категорія': назва, 'комісія': ком, 'ррц': rrc,
                  'закуп_пдв': pdv, 'ціна_0.93ррц': round(ринок),
                  'маржа': round(чисте - pdv),
                  'маржа_%': round((чисте - pdv) / pdv * 100, 1),
                  'кількість': g('stock_quantity')})
рядки.sort(key=lambda r: -r['маржа'])
print('відкинуто:', dict(викинуто))
print('кандидатів:', len(рядки))
print('за категоріями:', dict(collections.Counter(r['категорія'] for r in рядки)))
print(f"\n{'артикул':16} {'РРЦ':>7} {'ціна':>7} {'маржа':>7} {'%':>5}  назва")
for r in рядки[:15]:
    print(f"{r['артикул'][:16]:16} {r['ррц']:7.0f} {r['ціна_0.93ррц']:7} "
          f"{r['маржа']:7} {r['маржа_%']:5.0f}  {r['назва'][:46]}")
сума = sum(r['маржа'] for r in рядки)
print(f"\nсукупна маржа, якщо продати по одній штуці кожної: {сума:,} грн".replace(',', ' '))
os.makedirs('exports', exist_ok=True)
with open('exports/katran_кандидати_старт.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.DictWriter(f, fieldnames=list(рядки[0])); w.writeheader(); w.writerows(рядки)
print('список: exports/katran_кандидати_старт.csv')
