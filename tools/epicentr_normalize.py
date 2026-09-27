"""Приводить експортовані значення до букви довідника Єпіцентру й показує,
скільки з них PIM реально прийме. Нічого не пише в кабінет."""
import collections, importlib.util, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_s = importlib.util.spec_from_file_location('afm', os.path.join(BASE, 'tools', 'epicentr_attr_fill_multi.py'))
afm = importlib.util.module_from_spec(_s); _s.loader.exec_module(afm)
from content import epicentr_value_map as vm

sets = json.load(open(os.path.join(BASE, 'data', 'epicentr_attribute_sets.json'), encoding='utf-8'))
src = os.path.join(BASE, 'exports', 'epicentr_sets')
out_dir = os.path.join(BASE, 'exports', 'epicentr_sets_norm'); os.makedirs(out_dir, exist_ok=True)
how_all, miss = collections.Counter(), collections.Counter()
total_in = total_out = 0
for fn in sorted(os.listdir(src)):
    code = fn[:-5]
    vals = json.load(open(os.path.join(src, fn), encoding='utf-8'))
    if code not in sets: continue
    names = {a for v in vals.values() for a in v}
    opts = {}
    for at in sets[code]['attributes']:
        nm = afm.ua(at)
        if nm in names:
            opts[nm] = afm.options(code, str(at['code']))
    fixed = {}
    for sku, v in vals.items():
        mapped, report = vm.map_values(v, opts)
        for r in report:
            how_all[r['як']] += 1
            if not r['довідник']: miss[f"{r['атрибут']}={r['наше']}"] += 1
        total_in += len(v)
        if mapped:
            fixed[sku] = mapped; total_out += len(mapped)
    if fixed:
        json.dump(fixed, open(os.path.join(out_dir, fn), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'  набір {code}: {len(vals)} карток → {len(fixed)} із значеннями', flush=True)
print(f'\nзначень було {total_in}, придатних {total_out} ({total_out*100//max(total_in,1)}%)')
print('як знайдено:', how_all.most_common())
print('найчастіші промахи:', miss.most_common(12))
