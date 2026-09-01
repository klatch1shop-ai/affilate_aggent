#!/usr/bin/env python3
"""Систематичний аудит маппінгу sexopt_category → epicentr_category.

Метод: з назви товару визначається його ТИП (за ключовими словами, від
найспецифічніших до загальних), тип зіставляється з очікуваною
epicentr-категорією. Далі по кожній sexopt-категорії рахується, яка частка
товарів «не пасує» призначеній категорії. Групи з високою часткою
невідповідності виводяться на ручний розгляд — скрипт нічого не змінює.
"""
import re, random, collections, argparse
import psycopg2, psycopg2.extras

# (regex по назві, очікуваний epicentr_category_code, підпис типу)
# Порядок важливий: перший збіг виграє, тому специфічніші йдуть вище.
TYPE_RULES: list[tuple[str, str, str]] = [
    (r'^\s*(набір|комплект).{0,40}(бдсм|bdsm|фіксац|бондаж)', '9458', 'БДСМ-набір'),
    (r'електростимул|e-?stim',                        '9458', 'електростимуляція'),
    (r'кляп|\bgag\b',                                 '9458', 'кляп'),
    (r'наручник|handcuff|поножі|фіксатор|бандаж|розпірк|хрестовин|армбіндер|armbinder',
                                                      '9458', 'фіксація'),
    (r'батіг|флогер|стек|паддл|шльопалк|ляпалк|whip|flogger|paddle|crop',
                                                      '9458', 'імпакт'),
    (r'нашийник|чокер|портупе|збруя|harness|collar|повід|leash',
                                                      '9458', 'нашийник/портупея'),
    (r'затискач.{0,25}(соск|клітор|груд)|nipple clamp', '9458', 'затискачі'),
    (r'мотузк|шибарі|бондажн|bondage tape|скотч для бондажу', '9458', 'мотузка/скотч'),
    (r'маска на очі|пов.язка на очі|blindfold|тиклер|лоскіт|колесо вартенберга|pinwheel',
                                                      '9458', 'сенсорика'),
    (r'пояс вірності|chastity',                       '9458', 'пояс вірності'),
    (r'анальн(а|ий|і)? (пробк|плаг)|butt plug|бутплаг', '9484', 'анальна пробка'),
    (r'анальн.{0,20}(кульк|намист|ланцюж|beads)',     '9486', 'анальні кульки'),
    (r'анальн.{0,15}(розширювач|dilator)|фістинг|fisting', '9548', 'анальний розширювач'),
    (r'анальн.{0,15}душ|спринцівк|enema|douche',      '9550', 'анальний душ'),
    (r'масажер простати|prostate massager',           '9488', 'масажер простати'),
    (r'вагінальн.{0,20}(кульк|тренаж)|кегел|kegel|вагінізм', '9478', 'вагінальні кульки'),
    (r'насадка на (член|пеніс)|penis sleeve|cock sleeve|nude sleeve', '9474', 'насадка на член'),
    (r'ерекційн.{0,15}(кільц|віброкільц)|cock ?ring|cocksling|ball stretcher|ball splitter|ball pouch',
                                                      '9470', 'ерекційне кільце'),
    (r'мастурбатор|онахол|onahole|fleshlight|fleshjack|яйце tenga|tenga egg|стимулятор для ерогенних',
                                                      '9472', 'мастурбатор'),
    (r'страпон|strap-?on|безремінн',                  '9482', 'страпон'),
    (r'трусики для страпона|боді з фіксацією|шорти з фіксацією|трусики з фіксацією|вібронасадка для страпон',
                                                      '9616', 'аксесуар для страпона'),
    (r'фалоімітат|ділдо|дилдо|\bdildo\b|фалос',       '9480', 'фалоімітатор'),
    (r'вібратор|віброяйце|віброкул|вібромасажер|пульсатор|вібростимулятор',
                                                      '9466', 'вібратор'),
    (r'вакуумн.{0,25}стимулятор|womanizer|satisfyer.{0,20}(стимулятор)?',
                                                      '9476', 'вакуумний стимулятор'),
    (r'помпа|екстендер|extender|pump',                '9476', 'помпа/екстендер'),
    (r'секс-?машин|sex machine',                      '9456', 'секс-машина'),
    (r'лялька|doll|мінілялька',                       '9468', 'лялька'),
    (r'лубрикант|змазк|гель-?змазк|glide',            '9452', 'лубрикант'),
    (r'збуджувальн|стимулювальн.{0,15}(гель|крем)|афродизіак|рідкий вібратор',
                                                      '9452', 'збуджувальний засіб'),
    (r'масажн.{0,10}(свічк|олі)|свічка для',          '9630', 'масажна свічка'),
    (r'олія для (еротичного )?масажу|массажн.{0,10}олі', '9632', 'масажна олія'),
    (r'парфум|духи|феромон',                          '9454', 'парфуми'),
    (r'пролонгатор|подовжувач статевого',             '9636', 'пролонгатор'),
    (r'очищувач|toycleaner|toy cleaner|догляд за (секс-?)?іграшк|антибактер',
                                                      '9448', 'догляд за іграшками'),
    (r'меблі для сексу|гойдалк|секс-?крісл|подушка для сексу', '9578', 'меблі'),
    (r'презерватив|серветк.{0,10}латекс|dental dam|спрей.{0,25}(слиновид|орал)|для орального',
                                                      '9628', 'засоби для орального'),
    (r'гель для душу|скраб|батер|крем-?пудра|крем для гоління|піна для інтимн|спрей після гоління',
                                                      '9450', 'косметика'),
    (r'кабель|адаптер|конектор|кріплення|сушарк|кейс для зберіган|чохол|батарейк',
                                                      '9526', 'аксесуар'),
]

CAT_NAMES: dict[str, str] = {}


def detect(name: str):
    for rx, code, label in TYPE_RULES:
        if re.search(rx, name, re.I):
            return code, label
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', type=int, default=20)
    ap.add_argument('--seed', type=int, default=20260728)
    ap.add_argument('--threshold', type=float, default=0.5,
                    help='частка невідповідних, від якої група вважається підозрілою')
    args = ap.parse_args()
    random.seed(args.seed)

    conn = psycopg2.connect(host='192.168.3.28', dbname='agentdb',
                            user='agentadmin', password='1')
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT m.sexopt_category_id AS sid, m.sexopt_category_name AS sname,
               m.epicentr_category_code AS ep, p.sku, p.name
        FROM epicentr_category_mapping m
        JOIN sexopt_products p ON p.category_id = m.sexopt_category_id
        WHERE m.epicentr_category_code NOT IN ('7216','9464')
    """)
    rows = cur.fetchall()
    cur.execute("SELECT DISTINCT epicentr_category_code c, sexopt_category_name n "
                "FROM epicentr_category_mapping")
    cur.execute("SELECT code, name_ua FROM epicentr_intimate_categories")
    for r in cur.fetchall():
        CAT_NAMES[r['code']] = r['name_ua']

    groups = collections.defaultdict(list)
    for r in rows:
        groups[(r['sid'], r['sname'], r['ep'])].append((r['sku'], r['name']))

    suspicious = []
    for (sid, sname, ep), items in groups.items():
        sample = items if len(items) <= args.sample else random.sample(items, args.sample)
        verdicts = collections.Counter()
        mism = []
        for sku, nm in sample:
            code, label = detect(nm)
            if code is None:
                verdicts['?'] += 1
            elif code == ep:
                verdicts['ok'] += 1
            else:
                verdicts[label] += 1
                mism.append((sku, nm, label, code))
        decided = sum(v for k, v in verdicts.items() if k != '?')
        bad = decided - verdicts['ok']
        share = bad / decided if decided else 0
        if decided >= 3 and share >= args.threshold:
            top = collections.Counter((l, c) for _, _, l, c in mism).most_common(1)[0]
            suspicious.append(dict(sid=sid, sname=sname, ep=ep, total=len(items),
                                   sample=len(sample), bad=bad, decided=decided,
                                   share=share, top=top, examples=mism[:5]))

    suspicious.sort(key=lambda x: (-x['share'], -x['total']))
    print(f'Перевірено sexopt-категорій: {len(groups)}, товарів: {len(rows)}')
    print(f'Вибірка: до {args.sample} випадкових на категорію (seed {args.seed})')
    print(f'Підозрілих груп (>= {args.threshold:.0%} невідповідності): {len(suspicious)}\n')
    for s in suspicious:
        (label, want), n = s['top']
        print('=' * 96)
        print(f"{s['sid']}  {s['sname']}")
        print(f"  зараз: {s['ep']} {CAT_NAMES.get(s['ep'],'')}   |   товарів у категорії: {s['total']}")
        print(f"  невідповідність: {s['bad']}/{s['decided']} у вибірці ({s['share']:.0%})")
        print(f"  домінує тип: «{label}» → очікувана категорія {want} {CAT_NAMES.get(want,'')} ({n} з вибірки)")
        for sku, nm, lb, cd in s['examples']:
            print(f"     {sku:9} [{lb}→{cd}] {nm[:78]}")


if __name__ == '__main__':
    main()
