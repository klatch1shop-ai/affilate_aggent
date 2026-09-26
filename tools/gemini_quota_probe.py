"""Коли скидається добова квота Gemini і чи вже можна працювати.

Скидання — опівночі за Тихоокеанським часом (PT), не за Києвом.
Джерело: офіційний форум Google AI Developers, 2026.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def next_reset_kyiv():
    now_pt = datetime.now(ZoneInfo('America/Los_Angeles'))
    reset_pt = (now_pt + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if now_pt.hour == 0 and now_pt.minute == 0:
        reset_pt = now_pt
    return reset_pt.astimezone(ZoneInfo('Europe/Kyiv'))


def probe_live():
    from shared.utils.llm_router import call_gemini
    try:
        call_gemini('Відповідай одним словом: скільки буде 2+2?', max_tokens=20)
        return True, None
    except Exception as e:
        return False, str(e)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--live', action='store_true', help='реальний запит до Gemini замість лише розрахунку часу')
    args = ap.parse_args()

    reset = next_reset_kyiv()
    left = reset - datetime.now(ZoneInfo('Europe/Kyiv'))
    print(f'наступне скидання (Київ): {reset.strftime("%Y-%m-%d %H:%M")} (через {left})')

    if args.live:
        ok, err = probe_live()
        print('живий запит: ОК' if ok else f'живий запит: ще ні — {err}')
