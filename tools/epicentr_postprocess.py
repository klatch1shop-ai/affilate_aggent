import re, os

src = 'exports/carvol_epicentr_new.xml'
dst = 'exports/carvol_epicentr.xml'

with open(src, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Фільтр фото + розбивка на офери
header, rest = content.split('<offers>', 1)
body, footer = rest.rsplit('</offers>', 1)

offers_raw = re.findall(r'<offer[^>]*>.*?</offer>', body, re.DOTALL)
print('Всього офферів:', len(offers_raw))

# 2. Залишаємо тільки з фото
with_photo = [o for o in offers_raw if '<picture>' in o]
print('З фото:', len(with_photo))

# 3. Замінюємо 2874 → 2848
fixed = []
for o in with_photo:
    o = o.replace('code="2874">Автосвітло', 'code="2848">Аксесуари для автосигналізацій')
    fixed.append(o)

# 4. Дедупліація по id
seen_ids = set()
deduped = []
for o in fixed:
    m = re.search(r'<offer id="([^"]+)"', o)
    if m:
        oid = m.group(1)
        if oid not in seen_ids:
            seen_ids.add(oid)
            deduped.append(o)
print('Після дедуп:', len(deduped), '(видалено дублів:', len(fixed) - len(deduped), ')')

# 5. Обрізаємо назви > 150 символів
result = []
for o in deduped:
    def trim_name(m):
        tag, text, close = m.group(1), m.group(2), m.group(3)
        if len(text) > 150:
            text = text[:147] + '...'
        return tag + text + close
    o = re.sub(r'(<name[^>]*>)([^<]{151,})(</name>)', trim_name, o)
    result.append(o)

# 6. Виправляємо подвійне закриття в кінці
new_content = header + '<offers>\n' + '\n'.join(result) + '\n</offers>\n</yml_catalog>'

with open(dst, 'w', encoding='utf-8') as f:
    f.write(new_content)

size_mb = os.path.getsize(dst) / 1024 / 1024
print('Збережено:', dst, '(%d KB)' % (size_mb * 1024))
