#!/usr/bin/env python3
"""Замовлення NOIRE з Rozetka: ТТН → наклейка → CRM постачальника → Telegram.

Ланцюг (власник, 15.09 і 04.10):
  Rozetka підтверджено → наша ТТН у НП (з контролем оплати, якщо не оплачено)
  → PDF-наклейка 100×100 → кошик у CRM SexOpt → оформити → прикріпити ТТН
  → Telegram власнику: PDF, ID замовлення CRM, сума до сплати постачальнику.

ГОЛОВНИЙ РИЗИК І ЗАХИСТ ВІД НЬОГО

Кошик у CRM ОДИН НА ВЕСЬ АКАУНТ. Два замовлення, оброблені одночасно,
змішають позиції, і постачальник отримає чуже. Тому:
  * замок на файлі — одночасно працює рівно один прогін;
  * кошик має бути ПОРОЖНІЙ на старті, інакше зупиняємось (там чуже);
  * після наповнення склад кошика звіряється з очікуваним ТОЧНО — артикули
    й кількості; розбіжність зупиняє до оформлення;
  * кілька позицій в одному замовленні обробляються як одне ціле.

НЕЗВОРОТНІ ДІЇ вимагають явного дозволу:
  --create-ttn   створити ТТН (коштує грошей)
  --place        оформити замовлення в постачальника (створює зобовʼязання)
Без них — холостий прогін із показом того, що буде зроблено.

    venv/bin/python3 tools/noire_order_pipeline.py --order 907753887
    venv/bin/python3 tools/noire_order_pipeline.py --order 907753887 --create-ttn --place
"""
import argparse
import fcntl
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.append(os.path.join(BASE, 'agents', 'orders'))
from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BASE, '.env'), override=True)

LOCK = os.path.join(BASE, 'logs', 'noire_pipeline.lock')
STATE = os.path.join(BASE, 'logs', 'noire_pipeline_state.json')


def tg(text, pdf=None):
    import requests
    tok = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TG_BOT_TOKEN')
    chat = os.getenv('TELEGRAM_ADMIN_ID') or os.getenv('TG_CHAT_ID')
    if not (tok and chat):
        print('[telegram не налаштовано]')
        return
    try:
        if pdf and os.path.exists(pdf):
            with open(pdf, 'rb') as f:
                requests.post(f'https://api.telegram.org/bot{tok}/sendDocument',
                              data={'chat_id': chat, 'caption': text[:1000],
                                    'parse_mode': 'HTML'},
                              files={'document': f}, timeout=60)
        else:
            requests.post(f'https://api.telegram.org/bot{tok}/sendMessage',
                          data={'chat_id': chat, 'text': text,
                                'parse_mode': 'HTML'}, timeout=30)
    except Exception as exc:
        print(f'[telegram: {type(exc).__name__}]')


def load_state():
    return json.load(open(STATE, encoding='utf-8')) if os.path.exists(STATE) else {}


def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


def order_items(details):
    """{артикул: кількість} — кілька позицій в одному замовленні це норма."""
    out = {}
    for p in (details.get('purchases') or []):
        art = str((p.get('item') or {}).get('article') or p.get('article') or '').strip()
        if not art:
            continue
        out[art] = out.get(art, 0) + int(float(p.get('quantity') or 1))
    return out


def run(order_id, create_ttn, place, check_only=False):
    import rozetka_order_agent as RZ
    import np_label as LBL

    st = load_state()
    key = str(order_id)
    done = st.get(key, {})

    d = RZ.get_order_details(order_id)
    if not d:
        sys.exit('замовлення не прочитано')
    items = order_items(d)
    paid = RZ.payment_paid(d)
    amount = float(d.get('amount') or d.get('cost') or 0)
    print(f'замовлення {order_id}: сума {amount:.0f} грн · оплата '
          f'{d.get("payment_type")} · paid={paid}')
    print(f'позицій: {len(items)} → {items}')

    ok, lines = RZ.noire_stock([{'sku': k, 'quantity': v} for k, v in items.items()])
    for ln in lines:
        print('  ', ln)
    if ok is not True:
        tg(f'⚠️ Замовлення {order_id}: товару немає у постачальника\n' + '\n'.join(lines))
        sys.exit('наявність не підтверджена — зупиняюсь')

    # ── 1. ТТН ────────────────────────────────────────────────────────
    ttn = done.get('ttn') or d.get('ttn') or RZ._ttn_of(d)
    if not ttn:
        if not create_ttn:
            print('\n[холостий] ТТН не створено: потрібен --create-ttn')
            subprocess.run([sys.executable, os.path.join(BASE, 'tools', 'np_create_ttn.py'),
                            str(order_id), '--dry-params'], cwd=BASE)
            return
        r = subprocess.run([sys.executable, os.path.join(BASE, 'tools', 'np_create_ttn.py'),
                            str(order_id), '--create'], cwd=BASE,
                           capture_output=True, text=True, timeout=600)
        print(r.stdout[-1200:])
        if r.returncode != 0:
            tg(f'❌ Замовлення {order_id}: ТТН не створено\n{(r.stdout or r.stderr)[-500:]}')
            sys.exit('ТТН не створено')
        d = RZ.get_order_details(order_id)
        ttn = d.get('ttn') or RZ._ttn_of(d)
        done['ttn'] = ttn
        st[key] = done
        save_state(st)
    print(f'ТТН: {ttn}')

    # ── 2. Наклейка 100×100 ───────────────────────────────────────────
    pdf, why, status = LBL.label_pdf(ttn)
    print(f'наклейка: {status} — {why[:80]}')
    if status != 'ok':
        tg(f'⚠️ Замовлення {order_id}, ТТН {ttn}: наклейка не готова ({status}): {why}')

    # ── 3. CRM постачальника ──────────────────────────────────────────
    if not place:
        print('\n[холостий] у постачальника нічого не оформлено: потрібен --place')
        print(f'  було б: кошик {items} → оформити → прикріпити ТТН {ttn}')
        return

    from playwright.sync_api import sync_playwright
    import smtm_crm as CRM
    with sync_playwright() as p:
        crm = CRM.Crm(p)
        try:
            crm.login()

            # ── Порядок перевірок має значення ────────────────────────
            # 04.10: кошик наповнювався ДО перевірки «чи вже оформлено», і
            # повторний запуск лишав товар висіти в кошику — наступне
            # замовлення стартувало б із чужою позицією.
            # --check-only: проходимо шлях НОВОГО замовлення (очищення
            # кошика, наповнення, звірка) і зупиняємось ДО оформлення.
            # Потрібен, щоб перевірити очищення, не створюючи зобовʼязань.
            already = None if check_only else done.get('crm_id')

            if not already:
                # Кошик мусить бути порожній. Залишки прибираємо самі:
                # інакше одна недороблена спроба блокує всю роботу.
                if not crm.cart_is_empty():
                    left = crm.cart_items()
                    print(f'кошик не порожній: {left} — прибираю')
                    if not crm.clear_cart():
                        tg(f'⚠️ Замовлення {order_id}: кошик CRM не вдалось '
                           f'очистити, там лишилось {crm.cart_items()}. '
                           'Зупиняюсь, щоб не змішати замовлення.')
                        sys.exit('кошик не очистився')
                    tg(f'ℹ️ Перед замовленням {order_id} прибрано залишки '
                       f'з кошика CRM: {left}')
                for sku, qty in items.items():
                    if not crm.add(sku, qty):
                        sys.exit(f'{sku}: кількість у кошику не збіглась')
                same, why2 = crm.cart_matches(items)
                print('звірка кошика:', why2)
                if not same:
                    tg(f'❌ Замовлення {order_id}: {why2}. Нічого не оформлено.')
                    sys.exit(why2)

            # ── СТРАХУВАННЯ 1: не оформлювати двічі ──────────────────
            # Якщо замовлення вже створене (обрив на пізнішому кроці),
            # беремо збережений ID і йдемо одразу до ТТН. 04.10 прогін
            # упав на прикріпленні ПІСЛЯ оформлення — без цього повторний
            # запуск створив би друге замовлення в постачальника.
            if check_only:
                print('\n[перевірка] кошик наповнено й звірено, '
                      'оформлення НЕ виконується')
                print('  у кошику:', crm.cart_items())
                crm.clear_cart()
                print('  кошик після прибирання:', crm.cart_items())
                return

            crm_id = already
            if crm_id:
                print(f'замовлення вже оформлене раніше: {crm_id} — кошик не чіпав')
                crm.open(f'/uk/checkout/{crm_id}')
            else:
                crm.checkout_open()
                crm_id = crm.place_order()
                done['crm_id'] = crm_id
                st[key] = done
                save_state(st)        # фіксуємо ОДРАЗУ після незворотного
                print('оформлено в CRM:', crm_id)
                # Після оформлення кошик має спорожніти сам. Якщо ні —
                # прибираємо, щоб не отруїти наступне замовлення.
                if not crm.cart_is_empty():
                    print('кошик не спорожнів після оформлення — прибираю')
                    crm.clear_cart()

            # ── СТРАХУВАННЯ 2: збій прикріплення не лишає нас мовчки ──
            attached, note = False, ''
            if pdf and os.path.exists(pdf):
                try:
                    attached, note = crm.attach_ttn(ttn, pdf)
                except Exception as exc:
                    note = f'{type(exc).__name__}: {exc}'
                print('прикріплення ТТН:', attached, note[:120])
            else:
                note = 'наклейки немає'

            info = crm.order_info(crm_id) or {}
            done['сума'] = info.get('сума')
            done['ттн_прикріплено'] = info.get('джерело_ттн') == 'TTN_FILE'
            st[key] = done
            save_state(st)

            # Правду беремо з API постачальника, а не з того, що здалося
            # браузеру: кнопка могла натиснутись без результату.
            attached = done['ттн_прикріплено']
            if not attached:
                tg(f'⚠️ <b>ПОТРІБНА РУКА</b>\n'
                   f'Замовлення Rozetka {order_id} оформлене в постачальника '
                   f'(ID <b>{crm_id}</b>), але ТТН НЕ прикріпилась.\n'
                   f'Причина: {note[:200]}\n'
                   f'Відкрийте https://new.smtm.com.ua/uk/checkout/{crm_id}, '
                   f'оберіть «Прикріпити файл», введіть <code>{ttn}</code> '
                   f'і додайте PDF із цього повідомлення.', pdf)
        except SystemExit:
            raise
        except Exception as exc:
            # ── СТРАХУВАННЯ 3: будь-який збій ПІСЛЯ оформлення ────────
            # Замовлення вже існує й коштує грошей — мовчати не можна.
            cid = done.get('crm_id')
            if cid:
                tg(f'❌ <b>ЗБІЙ ПІСЛЯ ОФОРМЛЕННЯ</b>\n'
                   f'Rozetka {order_id} → постачальник ID <b>{cid}</b>\n'
                   f'{type(exc).__name__}: {str(exc)[:200]}\n'
                   f'Перевірте https://new.smtm.com.ua/uk/checkout/{cid}', pdf)
            raise
        finally:
            crm.close()

    msg = (f'<b>Замовлення Rozetka {order_id}</b>\n'
           f'ID у постачальника: <b>{done.get("crm_id")}</b>\n'
           f'До сплати постачальнику: <b>{done.get("сума")}</b>\n'
           f'ТТН: <code>{ttn}</code>' +
           (f' (контроль оплати {amount:.0f} грн)' if paid is not True else ' (оплачено)') +
           f'\nПозиції: {items}\n'
           f'ТТН прикріплено: {"так" if attached else "НІ — прикріпіть вручну"}')
    tg(msg, pdf)
    print('\n' + msg.replace('<b>', '').replace('</b>', '')
          .replace('<code>', '').replace('</code>', ''))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--order', type=int, required=True)
    ap.add_argument('--create-ttn', action='store_true')
    ap.add_argument('--place', action='store_true')
    ap.add_argument('--check-only', action='store_true',
                    help='перевірити очищення й наповнення кошика без оформлення')
    a = ap.parse_args()
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    with open(LOCK, 'w') as lk:
        try:
            fcntl.flock(lk, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            sys.exit('інший прогін уже працює — кошик CRM один на акаунт, чекаємо')
        run(a.order, a.create_ttn, a.place or a.check_only, a.check_only)
