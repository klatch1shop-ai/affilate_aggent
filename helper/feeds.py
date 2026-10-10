"""Локальна перевірка віку та наповнення фідів.

Рішення «застояв чи ні» береться з `tools/feed_freshness_watch.py` — там
воно єдине. 06.10 тут стояв власний поріг 180 хвилин на ВСІ фіди, і бот
скаржився на застій фіду Prom щоночі: Prom публікується за розкладом
(07:40, 11:40, 15:40, 19:40), і нічний розрив у 12 годин — це норма.
"""

import datetime
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tools'))


def count_offers(path: str) -> int:
    marker = b'<offer '
    tail = b''
    count = 0
    with open(path, 'rb') as source:
        while chunk := source.read(64 * 1024):
            data = tail + chunk
            count += data.count(marker)
            tail = data[-(len(marker) - 1):]
    return count


def feeds_status(paths: dict, now: float, max_age_min: int = 180,
                 stat=os.stat, counter=count_offers) -> dict:
    result = {}
    for marketplace, path in paths.items():
        try:
            info = stat(path)
            offers = counter(path)
        except OSError:
            result[marketplace] = {'ok': False, 'age_min': None, 'offers': 0}
            continue
        age_min = int((now - info.st_mtime) // 60)
        try:
            from feed_freshness_watch import is_stale, rule_for
            bad, _ = is_stale(rule_for(marketplace),
                              datetime.datetime.fromtimestamp(info.st_mtime),
                              datetime.datetime.fromtimestamp(now))
        except Exception:
            # Сторож недоступний — повертаємось до простого порогу, але
            # мовчки НЕ вважаємо фід свіжим.
            bad = age_min > max_age_min
        result[marketplace] = {'ok': not bad and offers > 0,
                               'age_min': age_min, 'offers': offers}
    return result
