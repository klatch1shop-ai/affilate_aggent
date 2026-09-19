"""Локальна перевірка віку та наповнення фідів."""

import os


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
        result[marketplace] = {'ok': age_min <= max_age_min and offers > 0,
                               'age_min': age_min, 'offers': offers}
    return result
