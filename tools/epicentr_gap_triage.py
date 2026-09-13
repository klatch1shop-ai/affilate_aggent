#!/usr/bin/env python3
"""
tools/epicentr_gap_triage.py
=============================
Сортування прогалин ПЕРЕД тим, як витрачати час на пошук.

ЧОМУ. SKILL-23 ставить пошук в інтернеті третім джерелом і вимагає рахувати
концентрацію до того, як планувати роботу. 07.09.2026 виявилось, що
концентрації замало: для «Кольору виробника» 173 картки лягли на 32 бренди,
тобто пошук виглядав дешевим — а насправді безнадійним.

Причина не в якості пошуку. Один і той самий `Strap-On-Me Desirous Harness`
у різних магазинах описаний як **black** і як **bronze**: модель випускають
у кількох кольорах, а наша назва варіанта не називає. Дізнатись колір
НАШОГО екземпляра ззовні неможливо в принципі — і це не залежить від того,
скільки запитів зробити.

Тому перед пошуком кожна прогалина розкладається на чотири класи:

  A. значення є в НАШІЙ назві      → заповнити, варіант визначений
  B. значення є лише в описі       → кандидат, дивитись поштучно
  C. значення варіантне, у нас його немає → пошук НЕ допоможе, питати
                                            постачальника
  D. атрибут не застосовний до товару     → питання до майданчика

Клас D — окремий і важливий: «Колір виробника» вимагається для перехідника,
ремкомплекту клапана й еластичного бинта. Це не прогалина в даних, це
невідповідність набору атрибутів товару.

Значення НЕ вигадуються (правило 5 черги) і НЕ беруться з карток
конкурентів (SKILL-14.8): дозволено лише наші власні дані.

Тільки читання. Нічого не пише в кабінет.

    python3 tools/epicentr_gap_triage.py
    python3 tools/epicentr_gap_triage.py --attr "Матеріал" --show 20
"""
import os, re, sys, json, argparse, collections

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE)
from dotenv import load_dotenv                                   # noqa: E402
load_dotenv(os.path.join(BASE, '.env'))
import psycopg2, psycopg2.extras                                 # noqa: E402

GAPS = os.path.join(BASE, 'docs', 'epicentr_enrich_gaps.json')
OPTS = os.path.join(BASE, 'data', 'epicentr_options_cache.json')
OUT  = os.path.join(BASE, 'docs', 'epicentr_gap_triage.json')

# Пакування, а не товар. Постачальник пише «ламінований картон» у полі
# «Матеріал», описуючи коробку — 40 таких значень 07.09.2026.
PACK = {'картон', 'папір', 'поліетилен', 'ламінований картон',
        'щільний картон', 'гофрокартон', 'пластик пакування'}

# Класи товарів, для яких колір і матеріал вироба здебільшого не мають
# сенсу: це запчастина, витратник або кріплення до іншого виробу.
# Характеристики, довідник яких — спільний для ВСЬОГО каталогу Єпіцентру,
# а не для нашої категорії. «Колір виробника» має 8453 значення: кольори
# меблів («клен танзау»), коди тканин («t-131»), англійські слова («captain»,
# «wolf», «aqua»). Текстовий збіг тут дає хибне спрацювання гарантовано —
# виміряно 07.09.2026: «Mystim Captain Hook» → колір «captain», «HEADGEAR - 4»
# → колір «100», займенник «він» → колір у 77 картках.
#
# Такі характеристики автоматично не заповнюються НІКОЛИ, незалежно від того,
# наскільки переконливо виглядає збіг.
NEVER_AUTO = {'Колір виробника'}

NOT_APPLICABLE = re.compile(
    r'\b(адаптер|перехідник|ремкомплект|ремонтн\w+ комплект|запасн\w+|'
    r'кріплення|тримач|підставка|ложе|майданчик|бинт|змінн\w+ (вставка|насадка)|'
    r'клапан|подовжувач|чохол|футляр|сумка|кейс)\b', re.I)


def words(s):
    return re.findall(r"[а-яїієґa-z0-9']{2,}", (s or '').lower())


def dict_hit(value, toks, low_text):
    """Значення довідника присутнє як ОКРЕМЕ слово або дослівна фраза.

    Збіг підрядка тут не годиться: 07.09.2026 наївна перевірка знайшла
    «він» (займенник) як колір у 77 картках. Межі слова обовʼязкові.
    """
    v = (value or '').lower().strip()
    if len(v) < 3:
        return False
    # Числові й буквено-числові коди довідника («100», «105», «c30», «t-131»)
    # чіпляються за будь-яке число в назві товару. Виміряно 07.09.2026:
    # «Насадка … HEADGEAR - 4 см» діставала колір «100». Значення, у якому
    # немає щонайменше трьох літер поспіль, ознакою бути не може.
    if not re.search(r'[а-яїієґa-z]{3,}', v):
        return False
    vw = words(v)
    if not vw:
        return False
    if len(vw) == 1:
        return vw[0] in toks
    return re.search(r'(?<![а-яїієґa-z])' + re.escape(v) + r'(?![а-яїієґa-z])',
                     low_text) is not None


def load():
    cn = psycopg2.connect(host=os.getenv('DB_HOST'), port=os.getenv('DB_PORT'),
                          dbname=os.getenv('DB_NAME'), user=os.getenv('DB_USER'),
                          password=os.getenv('DB_PASSWORD'))
    cur = cn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("SELECT sku, name, description_html FROM sexopt_products")
    prod = {r['sku']: r for r in cur.fetchall()}
    gaps = json.load(open(GAPS, encoding='utf-8'))
    opts = json.load(open(OPTS, encoding='utf-8'))
    return prod, [g for g in gaps if g['sku'] in prod and g['missing']], opts


def triage(prod, gaps, opts, only_attr=None):
    out = []
    for g in gaps:
        p = prod[g['sku']]
        name = p['name'] or ''
        desc = re.sub(r'<[^>]+>', ' ', p['description_html'] or '')
        n_toks, n_low = set(words(name)), name.lower()
        d_toks, d_low = set(words(desc)), desc.lower()
        na = bool(NOT_APPLICABLE.search(name))
        for m in g['missing']:
            if only_attr and m['name'] != only_attr:
                continue
            dic = opts.get(f"{g['category']}:{m['code']}") if 'category' in g \
                else opts.get(f"{g.get('catcode')}:{m['code']}")
            row = {'sku': g['sku'], 'attr': m['name'], 'code': m['code'],
                   'type': m['type'], 'cat': g.get('categoryName') or g.get('cat'),
                   'name': name[:110]}
            if not dic:
                row['class'] = 'E'
                row['why'] = 'довідника значень немає (числове або вільне поле)'
                out.append(row); continue
            in_name = [v for v in dic if dict_hit(v, n_toks, n_low)]
            in_desc = [v for v in dic if dict_hit(v, d_toks, d_low)]
            if m['name'] in ('Матеріал', 'Основний матеріал'):
                in_name = [v for v in in_name if v.lower() not in PACK]
                in_desc = [v for v in in_desc if v.lower() not in PACK]
            if m['name'] in NEVER_AUTO:
                in_name = in_desc = []
            if in_name:
                row.update({'class': 'A', 'values': in_name[:5],
                            'why': 'значення стоїть у нашій назві'})
            elif in_desc:
                row.update({'class': 'B', 'values': in_desc[:5],
                            'why': 'значення лише в описі — перевірити поштучно'})
            elif na:
                row.update({'class': 'D',
                            'why': 'атрибут не застосовний: запчастина, '
                                   'витратник або кріплення'})
            else:
                row.update({'class': 'C',
                            'why': 'у наших даних значення немає; варіантний '
                                   'атрибут — пошук ззовні не визначить наш '
                                   'екземпляр'})
            out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--attr')
    ap.add_argument('--show', type=int, default=0)
    ap.add_argument('--out', default=OUT)
    a = ap.parse_args()

    prod, gaps, opts = load()
    rows = triage(prod, gaps, opts, a.attr)
    json.dump(rows, open(a.out, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)

    by = collections.Counter(r['class'] for r in rows)
    LABEL = {'A': 'A  значення в нашій назві — заповнити',
             'B': 'B  значення лише в описі — перевірити поштучно',
             'C': 'C  даних немає, атрибут варіантний — питати постачальника',
             'D': 'D  атрибут не застосовний — питання до майданчика',
             'E': 'E  довідника немає (числове/вільне поле)'}
    print(f'прогалин розібрано: {len(rows)}\n')
    for k in 'ABCDE':
        if by[k]:
            print(f'  {by[k]:5}  {LABEL[k]}')
    print('\nза характеристикою (A / B / C / D / E):')
    per = collections.defaultdict(collections.Counter)
    for r in rows:
        per[r['attr']][r['class']] += 1
    for attr, c in sorted(per.items(), key=lambda kv: -sum(kv[1].values()))[:14]:
        print(f"  {sum(c.values()):4}  {attr:26} "
              f"{c['A']:4} {c['B']:4} {c['C']:4} {c['D']:4} {c['E']:4}")
    if a.show:
        print(f'\nперші {a.show} класу A (готові до заповнення):')
        for r in [x for x in rows if x['class'] == 'A'][:a.show]:
            print(f"   {r['sku']:9} {r['attr']:22} {r.get('values')}  ← {r['name'][:52]}")
    print(f'\n→ {a.out}')


if __name__ == '__main__':
    main()
