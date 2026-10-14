import sys, collections
sys.path.insert(0, '.')
from tools import katran_rozetka_generator as G
root = G.fetch()
cats, tree = G.categories()
СТОП = {'Пральні машини', 'Блендери', 'Мультиварки', 'Тримери'}
груп = collections.defaultdict(lambda: {'n': 0, 'ок': collections.Counter()})
СЦЕН = (1.00, 0.93, 0.80)
for it in root.iter('product'):
    g = lambda t: (it.findtext(t) or '').strip()
    if (g('stock') or '').strip() != 'есть':
        continue
    cid = g('categoryId')
    if cid not in cats:
        continue
    rz, назва, ком = cats[cid][0], cats[cid][1], cats[cid][2]
    if назва in СТОП or ком is None:
        continue
    try:
        rrc = float(g('price_rrc') or 0); pdv = float(g('price_pdv') or 0)
    except ValueError:
        continue
    if not (rrc and pdv):
        continue
    k = (round(float(ком), 1), назва)
    груп[k]['n'] += 1
    for с in СЦЕН:
        if (rrc * с) * (1 - float(ком) / 100) >= pdv:
            груп[k]['ок'][с] += 1
усього = sum(v['n'] for v in груп.values())
print(f'товарів у наявності з РРЦ і закупівлею: {усього}')
print(f"{'комісія':>7} {'категорія':26} {'шт':>5} {'за РРЦ':>7} {'×0.93':>7} {'×0.80':>7}")
for (ком, назва), v in sorted(груп.items(), key=lambda x: (-x[0][0], -x[1]['n']))[:24]:
    n = v['n']
    print(f'{ком:6.1f}% {назва[:26]:26} {n:5} '
          + ' '.join(f"{v['ок'][с] * 100 // n:6}%" for с in СЦЕН))
print('\nразом по комісії:')
по_ком = collections.defaultdict(lambda: [0, collections.Counter()])
for (ком, _), v in груп.items():
    по_ком[ком][0] += v['n']
    for с in СЦЕН:
        по_ком[ком][1][с] += v['ок'][с]
for ком, (n, ок) in sorted(по_ком.items(), reverse=True):
    print(f'  {ком:5.1f}%  {n:4} шт · прибуткові: за РРЦ {ок[1.0]*100//n}% · '
          f'×0.93 {ок[0.93]*100//n}% · ×0.80 {ок[0.80]*100//n}%')
