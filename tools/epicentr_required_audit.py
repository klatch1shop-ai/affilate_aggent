"""
tools/epicentr_required_audit.py
=================================
Звіряє фід Єпіцентру з довідником data/epicentr_attribute_sets.json
(наповнюється tools/epicentr_attrset_fetch.py).

Два правила, на яких раніше двічі помилилися:
  1) звіряти за КОДОМ атрибута (paramcode), а не за назвою — назви у фіді
     й у кабінеті різняться (напр. «Керування через застосунок» vs
     «... (Smart)»);
  2) вага/висота/ширина/довжина віддаються окремими тегами, а не <param>.

Запуск:  venv/bin/python3 tools/epicentr_required_audit.py <feed.xml>
"""
import os, sys, json, collections
import xml.etree.ElementTree as ET

BASE  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(BASE, 'data', 'epicentr_attribute_sets.json')

# системні атрибути, які фід віддає окремими тегами
TAG_OF = {'weight': 'weight', 'height': 'height',
          'width': 'width', 'length': 'length', 'depth': 'length'}


def title(attr):
    for t in attr.get('translations', []):
        if t.get('languageCode') == 'ua':
            return t.get('title') or attr['code']
    return attr.get('code')


def main():
    if len(sys.argv) < 2:
        sys.exit('вкажи шлях до фіду')
    sets = json.load(open(CACHE, encoding='utf-8'))
    root = ET.parse(sys.argv[1]).getroot()
    offers = root.findall('.//offer')

    by_cat = collections.defaultdict(list)
    for o in offers:
        el = o.find('attribute_set')
        by_cat[el.get('code') if el is not None else None].append(o)

    print(f'фід: {sys.argv[1]}')
    print(f'offerів: {len(offers)} | категорій: {len(by_cat)}')
    unknown = [c for c in by_cat if c not in sets]
    if unknown:
        print(f'категорій немає в довіднику: {len(unknown)} → {unknown[:8]}')

    complete = 0
    gaps_by_attr = collections.Counter()
    gaps_by_cat = collections.Counter()
    offers_with_gaps = []

    for cat, group in by_cat.items():
        spec = sets.get(cat)
        if not spec:
            continue
        req = [a for a in spec.get('attributes', []) if a.get('isRequired')]
        for o in group:
            have = {p.get('paramcode') for p in o.findall('param')
                    if (p.text or '').strip()}
            missing = []
            for a in req:
                code = a['code']
                if code in have:
                    continue
                tag = TAG_OF.get(code)
                if tag and (o.findtext(tag) or '').strip():
                    continue
                missing.append(f'{title(a)} [{code}]')
            if missing:
                offers_with_gaps.append(((o.findtext('vendorCode') or o.get('id')), cat, missing))
                gaps_by_cat[cat] += 1
                for m in missing:
                    gaps_by_attr[m] += 1
            else:
                complete += 1

    print(f'\nусі обовʼязкові заповнені: {complete}')
    print(f'бракує хоч однієї:         {len(offers_with_gaps)}')
    print('\nнайчастіші прогалини:')
    for name, n in gaps_by_attr.most_common(20):
        print(f'  {n:6}  {name}')
    print('\nпо категоріях:')
    for cat, n in gaps_by_cat.most_common(12):
        nm = title({'code': cat, 'translations': sets[cat].get('translations', [])})
        print(f'  {n:6}  {cat}  {nm}')

    out = os.path.join(BASE, 'docs', 'epicentr_required_gaps.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        json.dump([{'article': a, 'category': c, 'missing': m}
                   for a, c, m in offers_with_gaps], f, ensure_ascii=False, indent=1)
    print(f'\nдеталі → {out}')


if __name__ == '__main__':
    main()
