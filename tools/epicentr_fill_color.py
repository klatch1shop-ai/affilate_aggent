"""Заповнює «Колір виробника» за фото, беручи ДОЗВОЛЕНІ значення з опублікованих карток.

Три причини, чому звичайний шлях не працював (знайдено 27.09.2026):
  1) довідник має 8468 варіантів — меблеві відтінки, камуфляж, артикули, —
     і модель у ньому тоне: 146 карток поспіль дали «не визначила»;
  2) кольору немає в назві товару, він лише на зображенні;
  3) значення цього атрибута — СПИСОК, а коди в опублікованих картках
     короткі (`ff8cwdpi`), не ті довгі хеші, що віддає /options.

Тому відповідність «назва → код» беремо з самих опублікованих карток: те, що
вже пройшло модерацію, точно дійсне.
"""
import argparse, json, os, sys, re
from concurrent.futures import ThreadPoolExecutor
import requests
from dotenv import load_dotenv

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE); load_dotenv(os.path.join(BASE, '.env'))
from shared.utils.llm_router import call_gemini
from shared.utils.vendor_pool import _fetch

API='https://core-api.epicentrm.com.ua'
CODE='78'

def login(s):
    r=s.post(f'{API}/v2/users/login', json={'login':os.getenv('EPICENTR_EMAIL'),
             'password':os.getenv('EPICENTR_PASSWORD')}, timeout=40)
    r.raise_for_status(); s.headers['Authorization']=f"Bearer {r.json()['token']['auth']}"

def ua(o):
    for t in (o or {}).get('translations', []):
        if t.get('languageCode')=='ua': return t.get('value') or t.get('title')
    return None

def learn(s, products, set_code, sample=60):
    """{українська назва: код} — лише те, що вживають опубліковані картки."""
    pool=[p for p in products if p.get('status')=='published'
          and str(p.get('attributeSetCode'))==str(set_code)][:sample]
    found={}
    def one(p):
        try: return s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45).json()
        except Exception: return None
    with ThreadPoolExecutor(max_workers=6) as ex:
        for d in ex.map(one, pool):
            for v in ((d or {}).get('attributeValues') or []):
                if str(v['code'])!=CODE: continue
                for o in (v.get('options') or []):
                    name=ua(o)
                    if name: found[name]=o['code']
    return found

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--set', required=True); ap.add_argument('--skus', required=True)
    ap.add_argument('--apply', action='store_true'); ap.add_argument('--limit', type=int, default=0)
    a=ap.parse_args()
    products=json.load(open(os.path.join(BASE,'data','epicentr_products.json'),encoding='utf-8'))
    gaps=json.load(open(os.path.join(BASE,'exports','noire_gaps.json'),encoding='utf-8'))
    sent=set(json.load(open(os.path.join(BASE,'exports','epicentr_sent_moderation.json'),encoding='utf-8')))
    wanted={k for k,v in gaps.items() if k not in sent and v['set']==a.set
            and any(m['code']==CODE for m in v['miss'])}
    todo=[p for p in products if p['sku'] in wanted]
    if a.limit: todo=todo[:a.limit]

    s=requests.Session(); s.headers.update({'Accept':'application/json',
        'Content-Type':'application/json','Accept-Language':'uk-UA'})
    login(s)
    allowed=learn(s, products, a.set)
    if not allowed: sys.exit('в опублікованих картках цього набору немає кольорів')
    print(f'дозволено (зі зразків): {list(allowed)}')
    print(f'карток: {len(todo)}' + ('' if a.apply else '  (ПОКАЗ)'))
    form=s.get(f'{API}/v2/pim/products/forms/attribute-set/by-code/{a.set}/attributes', timeout=40).json()
    items=form.get('items', form if isinstance(form,list) else [])
    fid=next((x.get('id') for x in items if str(x['code'])==CODE), None)

    def work(p):
        try: d=s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45).json()
        except Exception as e: return p['sku'],'помилка читання',str(e)[:60]
        cur=[{'id':v['id'],'code':v['code'],'value':v['value']} for v in (d.get('attributeValues') or [])]
        if CODE in {str(v['code']) for v in cur}: return p['sku'],'вже було',None
        media=[m for m in (d.get('media') or []) if m.get('source')]
        main=next((m for m in media if m.get('isMain')), media[0] if media else None)
        if not main: return p['sku'],'немає фото',None
        q=(f"Товар: «{p.get('name')}»\n\nЯкого кольору САМ ВИРІБ на фото? "
           f"Дозволені значення, інших немає:\n{json.dumps(list(allowed), ensure_ascii=False)}\n\n"
           "Обери РІВНО ОДНЕ. Якщо визначити неможливо — НЕ ЗНАЮ. Лише значення, без пояснень.")
        try:
            img=_fetch(main['source'])[0]
            txt,_m,_t=call_gemini(q, timeout=90, max_tokens=50, image_bytes=img, image_mime='image/jpeg')
        except Exception as e: return p['sku'],'модель впала',str(e)[:60]
        ans=(txt or '').strip().strip('."\'«»')
        key=next((k for k in allowed if k.casefold()==ans.casefold()), None)
        if not key: return p['sku'],'не визначила',ans[:30]
        if not a.apply: return p['sku'],'знайдено',key
        cur.append({'id':fid,'code':CODE,'value':[allowed[key]]})   # значення — СПИСОК
        body={'attributeValues':cur,'categories':d.get('categories'),'isPrepayment':d.get('isPrepayment'),
              'media':d.get('media'),'productInPromotion':d.get('productInPromotion'),
              'attributeSetCode':d.get('attributeSetCode'),'companyId':d.get('companyId'),
              'sku':d.get('sku'),'translations':d.get('translations')}
        r2=s.put(f"{API}/v4/pim/products/common/{p['id']}", json=body, timeout=60)
        if r2.status_code not in (200,201,204):
            return p['sku'],'відмова API',f'{r2.status_code} {r2.text[:90]}'
        chk=s.get(f"{API}/v2/pim/products/{p['id']}", timeout=45)
        now={str(v['code']) for v in (chk.json().get('attributeValues') or []) if v.get('value')}
        return (p['sku'],'записано',key) if CODE in now else (p['sku'],'не закріпилось',key)

    stats={}
    with ThreadPoolExecutor(max_workers=5) as ex:
        for i,(sku,st,det) in enumerate(ex.map(work, todo),1):
            stats[st]=stats.get(st,0)+1
            if i<=6 or st in ('відмова API','не закріпилось'): print(f'  {sku}: {st} {det or ""}', flush=True)
    print(f'\nпідсумок: {stats}')

if __name__=='__main__': main()
