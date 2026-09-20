# ЗАВДАННЯ 29: озвучка роликів як модуль (українська, безкоштовно)

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_voice.py`. **Дата:** 20.09.2026.
**Перевірено вручну 20.09:** edge-tts, голоси `uk-UA-OstapNeural` / `uk-UA-PolinaNeural`,
демо-ролик зібрано (скіл `product-video`). Тепер це має стати модулем із тестами.

## Файли
Створити `content/voice.py`. Стандартна бібліотека. **Без мережі**: синтез і вимір тривалості
передаються ззовні (як `fetchers` у TASK-02).

## Інтерфейс
```python
VOICES = {'male': 'uk-UA-OstapNeural', 'female': 'uk-UA-PolinaNeural'}
PAUSE = 0.35          # пауза після репліки, с
def plan_lines(script: dict) -> list[str]
def synthesize(lines, synth, probe, *, voice='male', rate='+8%', out_dir='.') -> list[dict]
def align(segments: list[dict]) -> list[tuple[float, float, str]]
def concat_list(paths: list[str]) -> str
```
- `plan_lines` — з результату `content.script.parse_script`: `[hook] + points + [cta]`; порожні
  рядки пропустити; кожен рядок обрізати пробілами.
- `synthesize(lines, synth, probe, …)`: `synth(text, voice, rate, path)` створює файл,
  `probe(path) -> float` дає тривалість. Повертає `[{'text','path','duration'}]`, де
  `duration = probe(...) + PAUSE`. `voice` не з `VOICES` (і не схожий на код голосу
  `xx-XX-NameNeural`) → `ValueError`. Порожній `lines` → `[]`. Виняток `synth` для одного рядка →
  **не валить усе**: сегмент пропускається, а в результат додається `{'text', 'path': None,
  'duration': 0.0, 'error': <тип винятку>}`.
- `align` — з сегментів робить інтервали `(початок, кінець, текст)` без проміжків; сегменти з
  `path is None` пропускаються.
- `concat_list` — вміст файлу для `ffmpeg -f concat`: рядки `file '<шлях>'`; апостроф у шляху
  екранується як `'\''`.

## Приймання
```
venv/bin/python -m pytest tests/test_voice.py -q    → зелені
venv/bin/python -m pytest tests/ -q -k "not voice"  → зелені
```
Звіт `docs/reports/TASK-29-report.md`.
