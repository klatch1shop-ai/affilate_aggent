"""Обмежені повтори виклику з підставленою функцією очікування."""


def call_with_retry(fn, *, sleep, delays=(1, 2, 4),
                    retry_on=(ConnectionError, TimeoutError)):
    for attempt in range(len(delays) + 1):
        try:
            return fn()
        except retry_on:
            if attempt == len(delays):
                raise
            sleep(delays[attempt])
