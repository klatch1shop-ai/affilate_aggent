"""Детермінована оцінка втрат ролика перед публікацією."""

TARGET_LEN = (21.0, 34.0)
ALLOWED_LEN = (15.0, 45.0)
HOOK_MAX_S = 2.5
PACE = (2.5, 3.5)
CUTS_WINDOW_S, CUTS_MIN = 5.0, 2
CTA_MAX_S, CTA_AFTER = 2.0, 0.6
SIMILARITY_MAX = 0.3
GREETINGS = ('привіт', 'вітаю', 'доброго дня', 'сьогодні розповім', 'у цьому відео', 'друзі')
PROBLEM_WORDS = ('помилк', 'не роб', 'проблем', 'чому', 'скільки', 'як ', 'ризик', 'втрат')
WEIGHTS = {'hook_time': 20, 'hook_specific': 15, 'length': 15, 'no_greeting': 10,
           'pace': 10, 'cuts': 10, 'subtitles': 10, 'cta': 5, 'unique': 5}


def words(text) -> int:
    """Порахувати слова за пробілами, відкинувши самі розділові знаки."""
    return sum(any(char.isalnum() for char in part) for part in text.split())


def shingles(text, n=4) -> set[str]:
    """Утворити множину послідовностей слів без розділових знаків."""
    if n < 1:
        raise ValueError('Розмір шингла має бути додатним')
    tokens = [''.join(char for char in part if char.isalnum())
              for part in text.lower().split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return set()
    if len(tokens) < n:
        return {' '.join(tokens)}
    return {' '.join(tokens[index:index + n]) for index in range(len(tokens) - n + 1)}


def similarity(ours, theirs, n=4) -> float:
    """Визначити частку наших шинглів у тексті постачальника."""
    own = shingles(ours, n)
    return len(own & shingles(theirs, n)) / len(own) if own else 0.0


def score(video: dict) -> dict:
    """Перевірити ролик і повернути бал та впорядковані втрати."""
    timings = video['timings']
    if not timings:
        raise ValueError('Хронометраж не може бути порожнім')
    duration = sum(end - start for start, end, _ in timings)
    hook = (video.get('hook') or timings[0][2]).strip().lower().replace('’', "'")
    hook_duration = timings[0][1] - timings[0][0]
    cta_duration = timings[-1][1] - timings[-1][0]
    text = ' '.join(line for _, _, line in timings)
    pace = words(text) / duration if duration > 0 else 0.0
    specific = any(char.isdigit() for char in hook) or '?' in hook or any(
        word in hook for word in PROBLEM_WORDS
    )
    greeting = next((word for word in GREETINGS if hook.startswith(word)), '')
    cuts, start = 0, 0.0
    for shot in video['shots']:
        if start >= CUTS_WINDOW_S:
            break
        cuts += 1
        start += shot['duration']
    overlap = similarity(text, video['supplier_text']) if video['supplier_text'] else 0.0
    subtitles = bool(video['has_subtitles'])
    values = {
        'hook_time': (hook_duration <= HOOK_MAX_S, hook_duration, HOOK_MAX_S,
                      'скоротіть гачок до 2.5 с'),
        'hook_specific': (specific, 'є' if specific else 'нема конкретики',
                          'число, питання або проблема', 'додайте число, питання або проблему'),
        'length': (TARGET_LEN[0] <= duration <= TARGET_LEN[1], duration, TARGET_LEN,
                   'цільова довжина 21–34 с'),
        'no_greeting': (not greeting, greeting, '', 'приберіть привітання з початку'),
        'pace': (PACE[0] <= pace <= PACE[1], pace, PACE, 'темп 2.5–3.5 слова за секунду'),
        'cuts': (cuts >= CUTS_MIN, cuts, CUTS_MIN, 'додайте зміну кадру в перші 5 с'),
        'subtitles': (subtitles, subtitles, True, 'увімкніть субтитри'),
        'cta': (cta_duration <= CTA_MAX_S and timings[-1][0] > CTA_AFTER * duration,
                cta_duration, {'max_s': CTA_MAX_S, 'after': CTA_AFTER},
                'CTA коротший за 2 с і в кінці'),
        'unique': (overlap < SIMILARITY_MAX, overlap, SIMILARITY_MAX,
                   'перепишіть своїми словами'),
    }
    checks, losses = [], []
    total = 0
    for cid, weight in WEIGHTS.items():
        ok, got, want, hint = values[cid]
        checks.append({'id': cid, 'ok': ok, 'weight': weight, 'got': got,
                       'want': want, 'hint': '' if ok else hint})
        if ok:
            total += weight
        else:
            losses.append({'id': cid, 'weight': weight, 'hint': hint})
            if cid == 'length' and ALLOWED_LEN[0] <= duration <= ALLOWED_LEN[1]:
                total += weight / 2
    total = int(total)
    verdict = 'публікувати' if total >= 70 else 'доопрацювати' if total >= 50 else 'не публікувати'
    return {'score': total, 'max_score': sum(WEIGHTS.values()), 'checks': checks,
            'verdict': verdict, 'losses': sorted(losses, key=lambda loss: -loss['weight'])}


def report(result: dict) -> str:
    """Скласти текст оцінки та підказок без побічних дій."""
    lines = [f"🎬 Оцінка ролика: {result['score']}/{result['max_score']} — {result['verdict']}"]
    if result['losses']:
        lines.append('Втрати:')
        lines.extend(f"• {loss['id']} (−{loss['weight']}): {loss['hint']}"
                     for loss in result['losses'])
    else:
        lines.append('Втрат нема')
    return '\n'.join(lines)
