# ЗАВДАННЯ 30: монтаж із шаблонів (щоб ролик не був слайдшоу)

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_edit_plan.py`. **Дата:** 20.09.2026.
**Навіщо:** `content/ffmpeg_cmd.py` (TASK-18) вміє лише рівне слайдшоу. Дослідження
`docs/research/VIDEO_TOOLS_2026.md` і вимога YouTube до «неавтентичного» контенту: потрібні
рух кадру, титри з характеристик товару й підкладка. Демо 20.09 зібрано вручну — тепер модуль.

## Файли
Створити `content/edit_plan.py`. Лише стандартна бібліотека. **Нічого не запускати**: модуль
лише **будує рядки фільтрів і список аргументів**; `subprocess` не імпортувати.

## Інтерфейс
```python
FPS, W, H = 30, 1080, 1920
TEMPLATES = ('zoom_in', 'zoom_out', 'pan_right', 'static')
ROTATION = ('zoom_in', 'pan_right', 'zoom_out')
FIT = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'

def frames(duration, fps=FPS) -> int
def shot_filter(template, duration, index, *, fps=FPS) -> str
def title_filter(text, start, end, *, size=64, position='bottom') -> str
def plan_shots(images, durations, templates=None) -> list[dict]
def build_filtergraph(shots, titles=(), *, srt=None) -> str
def command(images, durations, out, *, titles=(), audio=None, music=None, srt=None) -> list[str]
```

### `frames(duration, fps)`
`round(duration * fps)`, мінімум 1. `duration <= 0` → `ValueError`.

### `shot_filter(template, duration, index, *, fps)`
Повертає рядок виду `'[{index}:v]{FIT},{рух},setsar=1[v{index}]'`, де `{рух}`:

| шаблон | рух |
|---|---|
| `zoom_in` | `zoompan=z='min(zoom+0.0009,1.18)':d={n}:s=1080x1920:fps={fps}` |
| `zoom_out` | `zoompan=z='if(eq(on,0),1.18,max(zoom-0.0009,1.0))':d={n}:s=1080x1920:fps={fps}` |
| `pan_right` | `zoompan=z=1.18:x='iw*0.18*on/{n}':d={n}:s=1080x1920:fps={fps}` |
| `static` | `zoompan=z=1:d={n}:s=1080x1920:fps={fps}` |

`{n}` — `frames(duration, fps)`. Шаблон не з `TEMPLATES` → `ValueError`.
**Чому `FIT` перед рухом:** інакше `crop` після `scale=…:-2` дає `Invalid argument (-22)` —
на це вже наступали 20.09.

### `title_filter(text, start, end, *, size=64, position='bottom')`
`drawtext=text='<екранований текст>':fontsize=<size>:fontcolor=white:borderw=4:
bordercolor=black@0.8:x=(w-text_w)/2:y=<y>:enable='between(t,<start>,<end>)'` — **одним рядком**,
без пробілів і переносів. `y`: `'bottom'` → `h-360`, `'top'` → `240`, `'center'` → `(h-text_h)/2`;
інше → `ValueError`. `start >= end` → `ValueError`.
Екранування в тексті: `\` → `\\`, `'` → `\'`, `:` → `\:`, `%` → `\%`.
`start`/`end` друкуються з двома знаками (`1.00`, `3.50`).

### `plan_shots(images, durations, templates=None)`
`[{'image', 'duration', 'template', 'index'}]`, `index` з 0.
- довжини списків різні або порожні → `ValueError`;
- `templates=None` → шаблони по колу з `ROTATION`;
- `templates` — список: по колу з нього; порожній список → `ValueError`;
  невідомий шаблон у списку → `ValueError`.

### `build_filtergraph(shots, titles=(), *, srt=None)`
Склеює через `';'`:
1. фільтр кожного кадру (`shot_filter`);
2. `'[v0][v1]…concat=n=<k>:v=1:a=0[vcat]'`;
3. якщо є `titles` (список `(text, start, end)` або `(text, start, end, position)`):
   `'[vcat]' + ','.join(title_filter(...)) + '[vtxt]'`;
4. якщо є `srt`: `"[<попередній>]subtitles=<srt>:force_style='Fontsize=18,Outline=2'[vout]"`;
5. **останній ярлик завжди `[vout]`** — якщо ні титрів, ні субтитрів, додати
   `'[vcat]null[vout]'`.
Порожній `shots` → `ValueError`.

### `command(images, durations, out, *, titles=(), audio=None, music=None, srt=None)`
Список аргументів:
- `['ffmpeg', '-y']`, далі на кожне фото `['-loop', '1', '-t', '<тривалість:.3f>', '-i', <шлях>]`;
- далі `['-i', audio]`, якщо є; далі `['-i', music]`, якщо є;
- `['-filter_complex', <граф>]`; якщо є **і** `audio`, **і** `music`, до графа через `';'`
  додається `'[{a}:a]volume=1[a0];[{m}:a]volume=0.12[a1];[a0][a1]amix=inputs=2:duration=first[aout]'`,
  де `{a}`, `{m}` — номери відповідних входів;
- `['-map', '[vout]']`; далі, якщо є звук: `['-map', '[aout]']` (коли обидва) або
  `['-map', '<номер>:a']` (коли лише один), і `['-shortest']`;
- хвіст: `['-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
  '-r', '30', out]`.
- Без звуку `-shortest` **не додається** (як у TASK-18).

## Правила
- Нічого не друкувати в stdout, нічого не писати на диск, не запускати процесів.
- Не чіпати `tests/`, `content/ffmpeg_cmd.py`, `.env`, інші модулі.

## Приймання
```
venv/bin/python -m pytest tests/test_edit_plan.py -q      → зелені
venv/bin/python -m pytest tests/ -q -k 'not edit_plan'    → зелені
```
Звіт `docs/reports/TASK-30-report.md`.

## Відповіді на можливі питання
1. **Один кадр** — `concat=n=1` усе одно ставиться (щоб ярлик `[vcat]` існував завжди).
2. **Титр із часом за межами ролика** — не перевіряємо, це турбота викликача.
3. **`music` без `audio`** — дозволено: тоді `amix` не потрібен, звук мапиться напряму.
4. **Пробіли й кирилиця в шляхах** — не екранувати: це список аргументів, не рядок оболонки.
