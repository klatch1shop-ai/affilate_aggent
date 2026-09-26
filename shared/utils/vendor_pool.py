"""Пул провайдерів для задач із перехресною перевіркою двома джерелами.

Навіщо. 26.09.2026 виявилось, що батч атрибутів Епіцентру видав 2557 рядків,
де у 94% «два незалежні джерела» були однією й тією самою моделлю: коли
Gemini вичерпав добову квоту, обидва запити тихо падали на Codex. Із 218
«ЗБІГів» 196 — це модель, що погодилась сама з собою. Помилки не було —
була втрата сенсу перевірки.

Тому тут вендор — **іменована річ**, а не безіменний запасний варіант:
  * `verdict()` не має права сказати «ЗБІГ», якщо вендор той самий;
  * `pick_two()` добирає друге джерело з ІНШОГО вендора;
  * `Stats` рахує, хто скільки відповів і збоїв, щоб порівнювати їх на
    справжніх даних, а не на враженнях.

Хто що вміє (перевірено живими запитами 26.09):
  kimi       — текст і ФОТО, платний (~$0.95/1М), БЕЗ добової стелі
  openrouter — текст і ФОТО (nemotron-3-nano-omni, вендор NVIDIA), 50/добу
  gemini     — текст і фото, але добова квота ~20 запитів на модель
  codex      — текст і фото, спільна квота з робочими задачами
  groq       — лише текст (gpt-oss-120b)
  cerebras   — лише текст (gpt-oss-120b)
"""
import time

VISION = ('kimi', 'openrouter', 'gemini', 'codex')
TEXT = ('groq', 'cerebras', 'kimi', 'openrouter', 'gemini', 'codex')

UNVERIFIED = 'НЕ ПЕРЕВІРЕНО (одне джерело)'
AGREE = 'ЗБІГ'
DISAGREE = 'РОЗБІЖНІСТЬ'
BOTH_UNKNOWN = 'обидва не знають'
ONLY_ONE_KNOWS = 'лише одне джерело'
FAILED = 'помилка запиту'

_UNKNOWN_MARKERS = ('НЕ ВИДНО', 'НЕ ВКАЗАНО')


def is_unknown(answer):
    return bool(answer) and answer.strip().upper() in {m.upper() for m in _UNKNOWN_MARKERS}


def verdict(photo_answer, text_answer, photo_vendor, text_vendor):
    """Чесний вердикт. «ЗБІГ» — тільки коли це РІЗНІ вендори.

    Той самий вендор двічі — не перевірка, хай навіть відповіді збіглися:
    модель послідовна у своїх помилках, і саме так 196 рядків набули
    хибної ваги 26.09.
    """
    if not photo_answer or not text_answer:
        return FAILED
    if is_unknown(photo_answer) and is_unknown(text_answer):
        return BOTH_UNKNOWN
    if is_unknown(photo_answer) or is_unknown(text_answer):
        # Одне джерело знає, друге чесно каже «не бачу» — це не розбіжність.
        # 26.09 живий тест: OpenRouter читає фото («2», «рожевий») там, де
        # Gemini і Codex обидва кажуть НЕ ВИДНО. Рахувати це суперечністю
        # означало б викидати єдину наявну відповідь.
        return ONLY_ONE_KNOWS
    if photo_vendor == text_vendor:
        return UNVERIFIED
    if photo_answer.strip().casefold() == text_answer.strip().casefold():
        return AGREE
    return DISAGREE


def pick_two(available, need_vision_first=True):
    """Два РІЗНІ вендори: перший уміє фото, другий — будь-який інший.

    Менше двох різних — повертає (вендор, None): краще чесне «одне джерело»,
    ніж вигаданий другий голос.
    """
    alive = [v for v in available if v]
    first_pool = VISION if need_vision_first else TEXT
    first = next((v for v in first_pool if v in alive), None)
    if first is None:
        return None, None
    second = next((v for v in TEXT if v in alive and v != first), None)
    return first, second


class Stats:
    """Скільки кожен вендор відповів, скільки разів упав, скільки часу забрав.

    Потрібне, щоб порівняння провайдерів спиралось на заміри, а не на
    враження, — і щоб видно було, коли пул звузився до одного вендора.
    """

    def __init__(self):
        self.ok = {}
        self.fail = {}
        self.ms = {}

    def record(self, vendor, ok, ms=0):
        bucket = self.ok if ok else self.fail
        bucket[vendor] = bucket.get(vendor, 0) + 1
        if ok:
            self.ms.setdefault(vendor, []).append(ms)

    def summary(self):
        out = {}
        for vendor in set(self.ok) | set(self.fail):
            times = sorted(self.ms.get(vendor, []))
            out[vendor] = {
                'відповів': self.ok.get(vendor, 0),
                'збоїв': self.fail.get(vendor, 0),
                'медіана_мс': times[len(times) // 2] if times else None,
            }
        return out


def call(vendor, prompt, image_url=None, image_bytes=None, image_mime=None,
         timeout=180, max_tokens=300, callers=None):
    """Запит до названого вендора. Кидає виняток, якщо не вийшло.

    `callers` дає підставити функції у тестах, не чіпаючи мережу.
    """
    c = callers or _default_callers()
    fn = c.get(vendor)
    if fn is None:
        raise ValueError(f'невідомий вендор: {vendor}')
    has_image = bool(image_url or image_bytes)
    if has_image and vendor not in VISION:
        raise ValueError(f'{vendor} не вміє дивитись фото')
    return fn(prompt, image_url=image_url, image_bytes=image_bytes,
              image_mime=image_mime, timeout=timeout, max_tokens=max_tokens)


def first_ok(vendors, prompt, stats=None, **kw):
    """Перший вендор зі списку, що відповів. Повертає (текст, вендор, помилки).

    Помилки повертаються, а не ковтаються: саме мовчазне падіння на той
    самий Codex і зіпсувало попередній прогін.
    """
    errors = []
    for vendor in vendors:
        t0 = time.time()
        try:
            text = call(vendor, prompt, **kw)
            ms = int((time.time() - t0) * 1000)
            if stats is not None:
                stats.record(vendor, True, ms)
            return text, vendor, errors
        except Exception as e:
            if stats is not None:
                stats.record(vendor, False)
            # Сам тип помилки нічого не пояснює: «RuntimeError» однаково
            # виглядає і для вичерпаної квоти, і для порожньої відповіді.
            errors.append(f'{vendor}:{type(e).__name__}: {str(e)[:160]}')
    return None, None, errors


def _fetch(url, _cache={}):
    """Байти зображення за посиланням — для вендорів, які не вміють брати URL.

    ЗНАЙДЕНО 26.09.2026: gemini приймає лише `image_bytes`, codex — лише шлях
    до файлу, і обидва мовчки ІГНОРУВАЛИ `image_url`. Через це вони «дивились»
    на фото, якого не отримували, і відповідали «НЕ ВИДНО» — а я записав це в
    їхню непридатність. Порожня відповідь через відсутні дані виглядає так
    само, як через невміння; різницю видно лише коли передаси дані насправді.
    """
    if url in _cache:
        return _cache[url]
    import requests
    resp = requests.get(url, timeout=60, headers={'User-Agent': 'Mozilla/5.0'})
    resp.raise_for_status()
    if len(_cache) > 32:
        _cache.clear()
    _cache[url] = (resp.content, resp.headers.get('content-type', 'image/jpeg').split(';')[0])
    return _cache[url]


def _default_callers():
    import os
    import tempfile

    from shared.utils import llm_router as r

    def kimi(prompt, image_url=None, image_bytes=None, image_mime=None,
             timeout=180, max_tokens=300):
        text, _ = r.call_kimi(prompt, timeout=timeout, max_tokens=max_tokens,
                              image_url=image_url, image_bytes=image_bytes,
                              image_mime=image_mime)
        return text

    def openrouter(prompt, image_url=None, image_bytes=None, image_mime=None,
                   timeout=180, max_tokens=300):
        text, _ = r.call_openrouter(prompt, timeout=timeout, max_tokens=max_tokens,
                                    image_url=image_url, image_bytes=image_bytes,
                                    image_mime=image_mime)
        return text

    def gemini(prompt, image_url=None, image_bytes=None, image_mime=None,
               timeout=180, max_tokens=300):
        if image_url and not image_bytes:          # інакше запит піде БЕЗ фото
            image_bytes, image_mime = _fetch(image_url)
        text, _model, _tok = r.call_gemini(prompt, timeout=timeout, max_tokens=max_tokens,
                                           image_bytes=image_bytes, image_mime=image_mime)
        return text

    def codex(prompt, image_url=None, image_bytes=None, image_mime=None,
              timeout=180, max_tokens=300):
        if image_url and not image_bytes:
            image_bytes, image_mime = _fetch(image_url)
        path = None
        try:
            if image_bytes:
                suffix = '.png' if 'png' in (image_mime or '') else '.jpg'
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                    f.write(image_bytes)
                    path = f.name
            text, _ = r.call_codex(prompt, image_path=path, timeout=timeout)
            return text
        finally:
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    def groq(prompt, image_url=None, image_bytes=None, image_mime=None,
             timeout=180, max_tokens=300):
        text, _ = r.call_groq(prompt, timeout=timeout, max_tokens=max_tokens)
        return text

    def cerebras(prompt, image_url=None, image_bytes=None, image_mime=None,
                 timeout=180, max_tokens=300):
        text, _ = r.call_cerebras(prompt, timeout=timeout, max_tokens=max_tokens)
        return text

    return {'kimi': kimi, 'openrouter': openrouter, 'gemini': gemini,
            'codex': codex, 'groq': groq, 'cerebras': cerebras}
