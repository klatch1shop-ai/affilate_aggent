# ЗАВДАННЯ 18: ядро контент-заводу — теми, сценарій, субтитри, монтаж

**Виконавець:** Codex. **Приймає:** рецензент за `tests/test_content.py` і читанням коду.
**Дата:** 20.09.2026. **Дослідження:** `docs/research/SOCIAL_CONTENT_2026.md`.

## 1. Навіщо

Просування магазину в соцмережах — незакритий напрям. Дослідження показало: короткі вертикальні
ролики працюють, але **шаблонний ШІ-контент без власної цінності карається** (YouTube,
«inauthentic content»), а ШІ-складові треба **позначати** (TikTok, Meta). Тому конвеєр будуємо
так: теми — **зі справжніх питань покупців і нашого каталогу**, сценарій — чернетка з фактів
(без вигадок), монтаж — локально через ffmpeg, публікація — **лише після кнопки власника**
(TASK-13).

Це завдання — **ядро без мережі й без ffmpeg-запуску**: теми, перевірка сценарію, субтитри,
**побудова команди** ffmpeg. Запуск монтажу й публікацію підключає рецензент.

## 2. Файли

Створити: `content/__init__.py` (порожній), `content/topics.py`, `content/script.py`,
`content/subtitles.py`, `content/ffmpeg_cmd.py`. Стандартна бібліотека. Без мережі.

## 3. `content/topics.py`

```python
def from_questions(comments: list[dict], *, limit: int = 10) -> list[dict]
def from_catalog(products: list[dict], *, limit: int = 10, min_price: float = 0) -> list[dict]
def merge(*groups, limit: int = 10) -> list[dict]
```
- `comments` — як віддає `integrations.rozetka.item_comments()`: `{'id','type','created','read',
  'has_answer','title','article','item_name','text'}`.
- `from_questions`: беруться **лише** `type == 'question'` і `has_answer is False`; тема:
  `{'kind': 'question', 'title': <item_name або title>, 'article': <article>, 'source': <text>,
  'created': <created>}`; новіші першими; дублікати за `article` — лише найновіше питання.
- `from_catalog`: `products` — `{'sku','name','price','sold','available'}`; беруться лише
  `available` і `price >= min_price`; тема `{'kind': 'product', 'title': name, 'article': sku,
  'source': '', 'sold': sold}`; сортування за `sold` спаданням.
- `merge(*groups, limit)` — чергує групи (одна тема з першої, одна з другої…), прибирає дублікати
  за `article`, обрізає до `limit`.

## 4. `content/script.py` — перевірка чернетки сценарію

```python
MAX_HOOK = 90
MAX_POINT = 120
BANNED = ('лікує', 'виліковує', 'гарантує результат', 'найкращий у світі', 'дешевше за всіх',
          'чудодійн', '100% ефектив')
DISCLOSURE = 'Відео створено за допомогою ШІ'

def build_prompt(topic: dict, facts: dict) -> str
def parse_script(text: str) -> dict
def check_script(script: dict, facts: dict) -> list[str]
```
- `build_prompt` — текст для моделі: тема, **перелік фактів** (характеристики з каталогу) і вимоги:
  українською, лише з фактів, 3–5 пунктів, гачок до `MAX_HOOK` символів, без обіцянок лікування,
  повернути **JSON** `{"hook": str, "points": [str], "cta": str}`. У тексті промпту мають бути
  назва теми, усі ключі `facts` і слово «JSON».
- `parse_script(text)` — витягти JSON навіть якщо він у ```-огорожі; повертає
  `{'hook','points','cta','disclosure': DISCLOSURE}`; некоректний JSON, відсутні ключі або
  `points` не список рядків → `ValueError`.
- `check_script(script, facts)` → список **проблем** (порожній список = сценарій придатний):
  * `'гачок задовгий'`, `'пункт задовгий: <перші 30 символів>'`;
  * `'мало пунктів'` (<3) / `'забагато пунктів'` (>5);
  * `'заборонене твердження: <слово>'` — будь-яке з `BANNED` (без урахування регістру);
  * `'число не з фактів: <число>'` — **будь-яке число з одиницею** (мл, г, кг, см, мм, шт, %, °)
    у тексті сценарію, якого немає серед значень `facts` (порівнювати нормалізовано: кома ↔ крапка,
    пробіли всередині числа прибрати);
  * `'нема позначки ШІ'`, якщо `script['disclosure']` не містить `DISCLOSURE`;
  * `'контакти у тексті'`, якщо `tg_dispatcher.privacy.mask_private` змінює текст (телефон/email).

## 5. `content/subtitles.py`

```python
CPS = 15.0            # символів за секунду
MIN_SEC = 1.2
def split_lines(text: str, width: int = 32) -> list[str]
def timings(chunks: list[str], *, start: float = 0.0) -> list[tuple[float, float, str]]
def to_srt(items: list[tuple[float, float, str]]) -> str
```
- `split_lines` — розбиття по словах, рядок ≤ `width`; слово довше за `width` не ріжеться.
- `timings` — тривалість шматка `max(MIN_SEC, len(текст) / CPS)`, без проміжків; час — секунди.
- `to_srt` — стандартний SRT: номер, `HH:MM:SS,mmm --> HH:MM:SS,mmm`, текст, порожній рядок.

## 6. `content/ffmpeg_cmd.py` — побудова команди (не запуск)

```python
SIZE = (1080, 1920)
def slideshow(images: list[str], durations: list[float], out: str, *, audio: str | None = None,
              srt: str | None = None, size: tuple[int, int] = SIZE, fps: int = 30) -> list[str]
def total_duration(durations: list[float]) -> float
```
- Перевірки (усі → `ValueError`): порожній `images`; різна довжина `images`/`durations`;
  будь-яка тривалість ≤ 0; сума > 60 с (ліміт коротких відео).
- Команда: `['ffmpeg', '-y', ...]`; кожне зображення — `-loop 1 -t <d> -i <шлях>`;
  аудіо — окремим `-i`; фільтр: кожен потік `scale=<W>:<H>:force_original_aspect_ratio=decrease`,
  `pad=<W>:<H>:(ow-iw)/2:(oh-ih)/2`, `setsar=1`, далі `concat=n=<N>:v=1:a=0`;
  якщо є `srt` — до вихідного відеопотоку додається `subtitles=<шлях>`;
  завершення: `-r <fps>`, `-c:v libx264`, `-pix_fmt yuv420p`, `-shortest` (лише з аудіо), `out`.
- Шляхи у `-i` — **як передані** (без лапок); екранування — справа запускача.

## 7. Приймання

```
venv/bin/python -m pytest tests/test_content.py -q      → зелені
venv/bin/python -m pytest tests/ -q -k "not content"    → зелені
```
Звіт `docs/reports/TASK-18-report.md` з «Самостійними рішеннями».

## 8. Відповідь на питання виконавця (20.09.2026, план Codex)

**`merge`:** спершу **прибрати дублікати за `article` між групами — виграє та група, що передана
раніше** (питання важливіші за товари: це жива потреба покупця), і лише потім чергувати теми,
що лишились. Саме цього чекає тест.
