#!/usr/bin/env python3
"""Кінцева звірка замовлення NOIRE: Rozetka ↔ Нова Пошта ↔ CRM постачальника (лише читання).

Скіл: .claude/skills/skill-33-noire-order-end-to-end/SKILL.md

    python3 tools/noire_order_verify.py 906078985          # звірка, таблиця в консоль
    python3 tools/noire_order_verify.py 906078985 --tg     # і підсумок у Telegram

Запускати ПІСЛЯ всіх операцій (ТТН, CRM, прикріплення). Нічого не змінює.
Кожна перевірка: ✅ збігається · ⚠️ відоме відхилення (не помилка коду) ·
❌ розбіжність, треба розібратись. Код виходу 1, якщо є хоч один ❌.

Чому звіряємо з трьох джерел, а не з повідомлень скриптів: відповідь
«success» — факт про запит, а не про стан (SKILL-21, SKILL-24).
"""
import json
import os
import sys
from datetime import date, datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(BASE_DIR, 'tools'))
_argv, sys.argv = sys.argv, [sys.argv[0], '0']      # np_create_ttn читає argv лише в main()
import np_create_ttn as N  # noqa: E402
sys.argv = _argv
RZ = N.RZ
LOG = os.path.join(BASE_DIR, 'shared', 'feeds', 'orders', 'supplier_orders.jsonl')
AFTER_TTN = {61, 3, 4, 5}      # статуси Rozetka, у яких ТТН уже має бути


def main():
    oid = int(sys.argv[1])
    res = []

    def put(state, name, detail):
        res.append((state, name, detail))

    # ── Rozetka ──
    d = RZ.get_order_details(oid)
    if not d:
        sys.exit(f'Rozetka: замовлення {oid} не прочитано')
    dl = d.get('delivery') or {}
    st, ttn = d.get('status'), RZ._ttn_of(d)
    put('✅' if st in AFTER_TTN else '❌', 'Rozetka: статус', f'{st} (очікується 61 або далі: {sorted(AFTER_TTN)})')
    put('✅' if ttn else '❌', 'Rozetka: ТТН у замовленні', ttn or 'немає')
    purchases = {str((p.get('item') or {}).get('article') or p.get('article') or '').strip(): int(float(p.get('quantity') or 0))
                 for p in (d.get('purchases') or [])}
    amount = int(float(d.get('amount') or 0))
    paid = RZ.payment_paid(d)
    ptype = d.get('payment_type') or (d.get('payment') or {}).get('payment_type')
    put('ℹ️', 'Rozetka: склад і оплата', f'{purchases} | {amount} грн | {ptype}, оплачено={paid} | БД агента: {RZ.get_db_status(oid)}')
    if not ttn:
        return report(oid, res)

    # ── Нова Пошта ──
    created = str(d.get('created') or '')[:10]
    try:
        frm = datetime.strptime(created, '%Y-%m-%d').strftime('%d.%m.%Y')
    except ValueError:
        frm = date.today().strftime('%d.%m.%Y')
    docs = N.np('InternetDocument', 'getDocumentList',
                {'DateTimeFrom': frm, 'DateTimeTo': date.today().strftime('%d.%m.%Y'), 'GetFullList': '1'}).get('data') or []
    t = next((x for x in docs if x.get('IntDocNumber') == ttn), None)
    put('✅' if t else '❌', 'НП: ТТН в акаунті', f'{ttn} ' + ('знайдено' if t else f'не знайдено серед {len(docs)} ТТН з {frm}'))
    if t:
        rp = N.phone380(dl.get('recipient_phone') or d.get('recipient_phone'))
        bar = str(t.get('InfoRegClientBarcodes') or '')
        put('✅' if bar == str(oid) else '⚠️', 'НП: № замовлення в ТТН', bar or 'порожньо (ТТН створено не скриптом?)')
        put('✅' if t.get('RecipientAddress') == dl.get('ref_id') else '❌', 'НП: відділення = Rozetka',
            f"{t.get('CityRecipientDescription')}, {str(t.get('RecipientAddressDescription'))[:45]}")
        put('✅' if t.get('RecipientsPhone') == rp else '❌', 'НП: телефон одержувача', f"НП {t.get('RecipientsPhone')} / Rozetka {rp}")
        put('✅' if int(float(t.get('Cost') or 0)) == amount else '❌', 'НП: оголошена вартість', f"{t.get('Cost')} / сума {amount}")
        cod = int(float(t.get('BackwardDeliveryMoney') or 0))
        if paid is True:
            put('✅' if cod == 0 else '❌', 'НП: післяплата', f'{cod} грн (замовлення оплачене — має бути 0)')
        elif cod == amount:
            put('✅', 'НП: післяплата', f'{cod} грн = сума замовлення')
        elif cod == 0:
            put('⚠️', 'НП: післяплата', f'0 грн, а клієнт платить при отриманні {amount} грн (API блокує картку — додати вручну)')
        else:
            put('❌', 'НП: післяплата', f'{cod} грн ≠ сума {amount}')
        put('ℹ️', 'НП: стан', f"{t.get('StateName')} | друк: {t.get('Printed')}")

    # ── CRM постачальника ──
    try:
        from playwright.sync_api import sync_playwright
        import smtm_crm
        with sync_playwright() as p:
            crm = smtm_crm.Crm(p)
            try:
                lst = crm.api('/uk/inner/order?{}')
                items = (lst or {}).get('items') or []
                o = next((x for x in items if x.get('ttnNumber') == ttn), None)
                put('✅' if o else '❌', 'CRM: замовлення з цією ТТН',
                    f"ID {o['id']} від {str(o.get('orderDate'))[:16]}" if o else f'немає серед {len(items)} останніх')
                if o:
                    ok = o.get('ttnOrigin') == 'TTN_FILE' and not o.get('waitForTtn')
                    put('✅' if ok else '❌', 'CRM: ТТН прикріплена файлом', f"ttnOrigin={o.get('ttnOrigin')}, waitForTtn={o.get('waitForTtn')}")
                    crm_items = {}
                    for it in o.get('cartItems') or []:
                        a = (it.get('product') or {}).get('article')
                        crm_items[a] = crm_items.get(a, 0) + int(float(it.get('amount') or 0))
                    put('✅' if crm_items == purchases else '❌', 'CRM: позиції = Rozetka', f'CRM {crm_items} / Rozetka {purchases}')
                    rows = [r for grp in (o.get('orders') or []) for r in (grp if isinstance(grp, list) else [grp])]
                    docs_ = ', '.join(f"{r.get('docNumber')} {r.get('docSum')} {(r.get('currency') or {}).get('name')}" for r in rows)
                    put('ℹ️', 'CRM: документ постачальника', f"{docs_ or '—'} | разом {o.get('totalSum')} грн")
                    unpaid = [r for r in rows if not r.get('paid')]
                    put('✅' if rows and not unpaid else '⚠️', 'CRM: оплата постачальнику',
                        f"статус {', '.join(str(r.get('status')) for r in rows)}; сплачено {o.get('depositPaidAmount')} з {o.get('totalSum')} грн"
                        + (' — не оплачено: постачальник не відвантажить' if unpaid else ''))
                    age_h = (datetime.now() - datetime.fromisoformat(str(o.get('orderDate'))[:19])).total_seconds() / 3600 \
                        if o.get('orderDate') else 0
                    if t and rows and not unpaid and t.get('StateId') in (1, '1') and age_h > 24:
                        put('⚠️', 'НП: оплачено, але не відвантажено', f"{age_h:.0f} год; ТТН ще «{t.get('StateName')}»")
                    crm_id = o['id']
                else:
                    crm_id = None
            finally:
                crm.close()
    except Exception as e:                        # CRM недоступна — це не «все гаразд»
        put('❌', 'CRM: перевірка не виконана', f'{type(e).__name__}: {str(e)[:120]}')
        crm_id = None

    # ── журнал сум до сплати ──
    recs = []
    if os.path.exists(LOG):
        for line in open(LOG, encoding='utf-8'):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('rozetka_order') == oid:
                recs.append(r)
    pay = next((r for r in reversed(recs) if r.get('to_pay_usd') or r.get('to_pay_eur') or r.get('to_pay_uah')), None)
    put('✅' if pay else '⚠️', 'Журнал: сума до сплати',
        ' / '.join(f'{pay[k]} {c}' for k, c in (('to_pay_usd', '$'), ('to_pay_eur', '€'), ('to_pay_uah', 'грн')) if pay.get(k)) if pay else f'запису немає ({LOG})')
    return report(oid, res, crm_id)


def report(oid, res, crm_id=None):
    fails = sum(1 for s, _, _ in res if s == '❌')
    warns = sum(1 for s, _, _ in res if s == '⚠️')
    print(f'Звірка Rozetka #{oid}' + (f' ↔ CRM {crm_id}' if crm_id else ''))
    for s, name, detail in res:
        print(f'  {s} {name:30} {detail}')
    verdict = '❌ є розбіжності' if fails else ('⚠️ збігається, є відомі відхилення' if warns else '✅ усе збігається')
    print(f'Підсумок: {verdict} (❌ {fails}, ⚠️ {warns})')
    if '--tg' in sys.argv:
        lines = [f'🔎 <b>Звірка Rozetka #{oid}</b>' + (f' ↔ CRM {crm_id}' if crm_id else ''), verdict]
        lines += [f'{s} {name}: {detail}' for s, name, detail in res if s in ('❌', '⚠️')]
        N.tg_text('\n'.join(lines)[:3900])
    return 1 if fails else 0


if __name__ == '__main__':
    if len(sys.argv) < 2 or not sys.argv[1].isdigit():
        sys.exit(__doc__)
    sys.exit(main())
