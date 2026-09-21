# Аудит витрат контексту

## Коротко (5 рядків для власника)
1. `max_tokens` в Ollama-адаптері фактично ігнорується; черга Ollama теж не задає межі виходу (`shared/utils/llm_router.py:125`, `shared/utils/ollama_worker.py:21`).
2. Делегатор уже скорочує помилки до 1200 символів; твердження про повністю необмежений зворотний зв’язок неправильне (`tools/llm_delegate.py:174`).
3. Redis-стан і Qdrant-пошук уже є в коді; їхню роботу на сервері цей аудит не перевіряє (`orchestrator/orchestrator.py:39`, `embedding_service.py:59`).
4. Повна історія чату зростає у XML-помічнику; це конкретний кандидат на скорочення (`tools/ai_xml_generator.py:570`).
5. Виміряно символи й байти, а не оплачені токени; відсоток економії без порівняльного експерименту невідомий (команди М1–М3 нижче).

## А. Виміряне

### Межі та спосіб перевірки

Дата: 21.09.2026. Статичне читання локального коду, без імпорту бойових модулів, мережі, БД, `.env`, секретів і запуску агентів. Назви моделей нижче — **значення за замовчуванням у коді**, а не підтверджена конфігурація сервера. «Немає ліміту» означає, що застосунок його не передає; модель усе одно має власні обмеження. Коментарі про колишні експерименти не видаються за нові вимірювання.

Інвентаризація: `rg -n 'generateContent|chat/completions|messages.create|/api/generate|request_llm\(' --glob '*.{py,rs,ts,js,sh}' --glob '!venv/**' --glob '!**/target/**' --glob '!**/node_modules/**' --glob '!logs/**' --glob '!data/**' --glob '!output/**' --glob '!**/.git/**'`, потім пошук `ask(` і читання тіл функцій та їхніх викликачів. Тести й копії коду не є окремими робочими каналами. Вкладений `claw-code` наведений окремо від Python-системи.

### А1. Виклики моделей

У таблиці «JSON» — вимога саме чистого JSON. «Ні» часто означає навмисний текст, XML чи Python, а не дефект. У наведених Python-транспортах немає API-режиму JSON/schema; текстова вимога не гарантує формат.

| Транспорт, файл:рядок | Модель | Межа виходу | Temperature | JSON без обгортки |
|---|---|---|---|---|
| `shared/utils/llm_router.py:75` | `OMNIROUTE_MODEL`, default `auto` (:41) | **немає за замовчуванням**, optional `max_tokens` | не задана | ні |
| `shared/utils/llm_router.py:106` | `GEMINI_MODELS`: `gemini-flash-lite-latest`, `gemini-3.1-flash-lite`, `gemini-3-flash-preview`, `gemini-flash-latest` (:44) | **немає за замовчуванням**, optional `maxOutputTokens` | 0.3 | ні |
| `shared/utils/llm_router.py:127` | через selector: routing/text `llama3.2:3b`, code/analysis/default `qwen2.5:7b` (`shared/utils/model_selector.py:19`) | **немає навіть при переданому `max_tokens`** | не задана | ні |
| `shared/utils/ollama_worker.py:21` | аргумент `model` від викликача | **немає** | не задана | лише промпт викликача |
| `agents/scraper/category_classifier.py:308` | `qwen2.5:7b` (:13) | `num_predict=10` | 0 | ні, id |
| `tools/noire_desc_generator.py:266` | `qwen2.5:7b`, CLI `--model` (:423) | `num_predict=700` | аргумент default 0.7; виклик `0.6 + 0.1 * attempt` (:386) | ні, суцільний текст (:259) |
| `tools/prom_kw_calibrate.py:144` | `aya-expanse:8b` (:43) | `num_predict=npred`, default 90; варіант C — 70 (:199) | 0.2 | ні, фрази |
| `tools/toptul_rozetka_llm.py:89` | `NOIRE_MAP_MODEL`, default `aya-expanse:8b` (:46) | `num_predict=12` | 0.1 | ні, число (:60) |
| `tools/noire_ru_translate.py:121` | `NOIRE_TRANSLATE_MODEL`, default `gemma3:4b` (:50) | `num_predict=1400` | 0.1 | ні, переклад |
| `tools/prom_desc_rewrite.py:197` | `NOIRE_REWRITE_MODEL`, default `aya-expanse:8b` (:48) | `num_predict=400` | 0.3 | ні, текст |
| `tools/nvidia_nim.py:86` | аргумент; CLI обирає доступну через `pick_model` (:71); filters фіксує `nvidia/nemotron-3-super-120b-a12b` (`tools/toptul_llm_filters.py:36`) | default 1400; filters 3000 (:138) | 0.1 | ні |
| `tools/toptul_translate.py:225` | `NOIRE_TRANSLATE_MODEL`, далі `nvidia/nemotron-3-super-120b-a12b`, `mistralai/mistral-nemotron`, `deepseek-ai/deepseek-v4-flash-0731` (:44) | 3000, повтор 8000 (:221) | 0 | ні, пари тексту |
| `tools/toptul_desc_translate.py:294` | такий самий список (:119) | аргумент `tokens`; виклики 6000 (:685, :1043), `budget_for(chars*2,16000)` (:748), `budget_for(len(s),12000)*mul` (:790), `budget_for(len(src)*2,4000)` (:905); формула `min(24000,max(floor,chars*4))` (:589) | 0 | ні, переклад/пари |
| `tools/toptul_rozetka_validate.py:96` | `NOIRE_VALIDATE_MODEL`, default `nvidia/llama-3.3-nemotron-super-49b-v1.5` (:57) | 3000, 6000, 6000 (:115) | 0 | лише **останній рядок** JSON (:72), не весь вихід |
| `tools/ai_xml_generator.py:492` | `claude-haiku-4-5-20251001` | 2048 | не задана | ні, XML/чат |

Усі знайдені прикладні виклики черги Ollama нижче успадковують **відсутність ліміту й temperature** з `shared/utils/ollama_worker.py:21`:

| Файл:рядок виклику | Модель | JSON |
|---|---|---|
| `orchestrator/orchestrator.py:79` | `OLLAMA_MODEL` / `llama3.2:3b` (:56) | ні, Markdown |
| `orchestrator/orchestrator.py:132` | `OLLAMA_MODEL` / `llama3.2:3b` (:106) | так, промпт (:113, :126) |
| `agents/checker/acceptance_checker.py:38` | `OLLAMA_MODEL` / `llama3.2:3b` (:20) | так, промпт (:35) |
| `agents/checker/acceptance_checker.py:71` | `OLLAMA_MODEL` / `llama3.2:3b` (:52) | ні, скіл |
| `agents/dev/dev_agent.py:37`, `agents/dev/dev_agent.py:50` | `OLLAMA_DEV_MODEL` / `deepseek-coder:6.7b-instruct-q4_K_M` (:21, :40) | ні, код/аналіз |
| `agents/finance/finance_agent.py:142` | `OLLAMA_MODEL` / `llama3.2:3b` (:124) | ні |
| `agents/marketing/marketing_agent.py:73` | `OLLAMA_MODEL` / `llama3.2:3b` (:56) | ні |
| `agents/efficiency/efficiency_agent.py:94` | `OLLAMA_MODEL` / `llama3.2:3b` (:77) | ні |
| `agents/scraper/xml_generator.py:73` | аргумент або `OLLAMA_MODEL` / `llama3.2:3b` (:43) | ні |
| `agents/scraper/rozetka_card_agent.py:84` | `aya-expanse:8b` (:53) | ні |

Прикладні виклики router теж **не передають вихідного бюджету**: `tools/llm_delegate.py:130` (task=code, Python-блок; канал CLI default omniroute :103), `tools/llm_channel_bench.py:72` (task=text, канал аргумент), CLI `shared/utils/llm_router.py:228`, selftest `shared/utils/llm_router.py:182`. Реальний default chain router — `gemini,ollama` (:49), попри застаріле формулювання вступного docstring (:9). Модель/temperature успадковуються з таблиці транспортів. `tools/nvidia_nim.py:140`, `tools/toptul_llm_filters.py:138`, `tools/toptul_rozetka_second.py:84` використовують відповідні обмежені NIM-транспорти; `tools/toptul_rozetka_llm.py:126` і `tools/toptul_rozetka_validate.py:163` — відповідні функції `ask` у своїх файлах. HTML fetch `/api/generate` у `tools/ai_xml_generator.py:408` — внутрішній маршрут до того самого Anthropic-виклику, не додатковий провайдер.

Окремо: `embedding_service.py:18`, :41, :54 використовує локальний `SentenceTransformer("all-MiniLM-L6-v2")` для векторів. Це не генерація тексту; max output, temperature й JSON тут не застосовуються.

Вкладений Rust-проєкт: `claw-code/rust/crates/api/src/providers/anthropic.rs:283`, :339 (send/stream, спільний POST :480) та `claw-code/rust/crates/api/src/providers/openai_compat.rs:168`, :223 (POST :281). Модель — `MessageRequest.model`, бюджет — обов’язковий `max_tokens: u32`, temperature — `Option<f64>` (`claw-code/rust/crates/api/src/types.rs:9`). OpenAI-сумісний payload передає бюджет як `max_completion_tokens` для gpt-5 або `max_tokens`, а temperature лише за умовами моделі (:1035, :1065 у `openai_compat.rs`). Загальної вимоги чистого JSON немає. Повний граф викликачів цього окремого CLI та його робоча конфігурація не досліджені; не зараховую його витрати до агентів дропшипінгу без доказу запуску.

### А2. Розміри інструкцій

М1 — виконана команда вимірювання (Unicode-символи, не байти й не токени):

```python
# venv/bin/python - <<'PY' ... PY
from pathlib import Path
paths = [Path('AGENTS.md'), Path('CLAUDE.md'),
         *Path('docs/tasks').glob('*.md'),
         *Path.home().glob('.claude/skills/*/SKILL.md')]
rows = [(len(p.read_text()), len(p.read_text().splitlines()), str(p))
        for p in paths if p.is_file()]
print(*sorted(rows, reverse=True)[:10], sep='\n')
print(*[r for r in rows if not r[2].startswith('docs/tasks/')], sep='\n')
```

Топ-10 спільного набору:

| Файл (`~` = `/home/tekken`) | Символів | Рядків |
|---|---:|---:|
| `~/.claude/skills/skill-creator/SKILL.md` | 32987 | 485 |
| `~/.claude/skills/watch/SKILL.md` | 23183 | 276 |
| `CLAUDE.md` | 16780 | 365 |
| `~/.claude/skills/codex-worker/SKILL.md` | 12741 | 209 |
| `~/.claude/skills/skill-doctor/SKILL.md` | 12182 | 222 |
| `docs/tasks/TASK-03-buyer-inbox.md` | 12015 | 258 |
| `~/.claude/skills/google-gemini-api/SKILL.md` | 10289 | 254 |
| `docs/tasks/TASK-05-api-adapters.md` | 9522 | 181 |
| `~/.claude/skills/mcp-builder/SKILL.md` | 9059 | 236 |
| `docs/tasks/TASK-04-epicentr-offers-sync.md` | 8809 | 168 |

Решта доступних скілів та AGENTS.md (М1):

| Файл | Символів | Рядків |
|---|---:|---:|
| `AGENTS.md` | 1622 | 36 |
| `~/.claude/skills/google-finding-google-skills/SKILL.md` | 6745 | 134 |
| `~/.claude/skills/skills-find/SKILL.md` | 2990 | 54 |
| `~/.claude/skills/video-analysis/SKILL.md` | 2101 | 36 |
| `~/.claude/skills/pdf/SKILL.md` | 8035 | 314 |
| `~/.claude/skills/obsidian-vault/SKILL.md` | 3034 | 51 |
| `~/.claude/skills/xlsx/SKILL.md` | 8542 | 99 |
| `~/.claude/skills/product-video/SKILL.md` | 3956 | 64 |

Окремий топ-10 завдань, команда: `sorted((len(p.read_text()), str(p)) for p in Path('docs/tasks').glob('*.md'))[::-1][:10]`:

| TASK / файл у `docs/tasks/` | Символів |
|---|---:|
| `TASK-03-buyer-inbox.md` | 12015 |
| `TASK-05-api-adapters.md` | 9522 |
| `TASK-04-epicentr-offers-sync.md` | 8809 |
| `TASK-34-rozetka-delivery-fit.md` | 7843 |
| `TASK-06-helper-services.md` | 7785 |
| `TASK-10-rozetka-read-v2.md` | 6431 |
| `TASK-09-intents-v2.md` | 6361 |
| `TASK-11-commands-v2.md` | 6106 |
| `TASK-13-confirm.md` | 6075 |
| `TASK-01-voice-intents.md` | 6068 |

Це місткість файлів, а не доказ автозавантаження всіх скілів у кожен запит. Приклад явного завантаження в runtime — `shared/utils/skill_loader.py:43`; вибір релевантних уривків — `shared/utils/skills_indexer.py:19`.

### А3. Довгий вивід і передавання тексту

М2 — підрахунок локальних зразків без виведення їхнього вмісту:

```python
from pathlib import Path
for p in [Path('exports/noire_epicentr.xml'), Path('shared/feeds/rozetka_feed.xml'),
          *Path('shared/skills/scraper').glob('*_api.md')]:
    chars = lines = 0
    with p.open() as f:
        for line in f:
            chars += len(line)
            lines += 1
    print(p, chars, lines)
```

| Джерело виводу / функція | Вимір або точна межа | Чи обрізається; чи потрапляє до LLM |
|---|---|---|
| `cat exports/noire_epicentr.xml` (лише оцінено через М2) | 59213365 символів, 690855 рядків | `cat` не обмежує; автоматичного надсилання цього фіду до LLM не встановлено |
| `cat shared/feeds/rozetka_feed.xml` (М2) | 25831167 символів, 151752 рядки | так само; `helper/feeds.py:11` читає блоками 65536 байтів і повертає тільки число (:15) |
| `read_api_doc`, `shared/mcp_servers/filesystem_mcp.py:67` | Prom 2799/101; Rozetka 2959/94; Epicentr 1314/62 (символи/рядки, М2) | повертає файл повністю (:72) |
| `read_skill`, `read_knowledge`, той самий MCP :53, :86 | залежить від файлу, явної межі немає | повний `f.read()` як TextContent; приватні knowledge-файли не читались |
| pytest у `tools/llm_delegate.py:90` | зберігає останні 4000 символів; повторний промпт максимум 1200 символів помилок + 1500 символів ТЗ (:174) | обрізання є; subprocess спочатку захоплює весь вивід (:93) |
| зовнішній launcher `/home/tekken/affiliate-sales-pilot/scripts/codex_task.py:190` | verify tail 1500, baseline tail 800 (:212), сукупні помилки в повторі 3000 (:367) | обрізання є; `run` :54 спочатку захоплює повний stdout+stderr |
| `git diff` | початкове дерево чисте (`git status --short` повернув порожній вивід); порожній diff — 0 символів/0 рядків | типовий diff іншої задачі не виміряний; загальної межі у git немає |
| SQL backup `ops/pg_backup.py:63` | **0 символів дампа до контексту** за маршрутом коду; stderr максимум 500 символів | `ops/run_pg_backup.py:30` пише stdout у файл; `pg_dump -Fc` (:10 у pg_backup) — бінарний дамп, його рядки не є метрикою тексту |
| XML-чат `tools/ai_xml_generator.py:570` | увесь `sess['messages']`, межі історії немає | повторює попередні повідомлення при кожному виклику; це вхідні токени, незалежні від max_tokens=2048 |

Живі «типові» SQL-дампи, історії покупців і бойові логи не знімались. Значення М2 — конкретні локальні файли, не середнє по виробничих запусках. Обсяг pytest поточного прогону наведений у звіті TASK-36; не можна переносити його на падіння тестів.

### А4. Повторне читання в одному прогоні

| Місце | Що повторюється | Наслідок |
|---|---|---|
| `shared/utils/skill_loader.py:45`, :50 | `list_skills` спочатку відкриває кожен файл заради першого рядка (:15), потім `load_all_skills` відкриває ті самі файли повністю | два відкриття кожного скіла; це I/O, не автоматично подвійні токени |
| `orchestrator/orchestrator.py:102`, :147 | двічі `get_system_snapshot()` на успішному маршруті | перший `snapshot` не використовується у full_prompt (:112); два читання Redis, не історія думок |
| `orchestrator/orchestrator.py:101`, :107 | завантажує всі скіли у `skills_context`, потім шукає релевантні; у prompt використано тільки `skills` (:117) | зайве повне файлове читання; це не двічі та сама вибірка, а дублювання підготовки контексту |
| `shared/utils/ollama_worker.py:55`, :56 | polling одного result_key кожні 0.5 секунди (:63) | очікування результату, а не багаторазовий LLM-запит; не варто рахувати як марнування токенів |
| `tools/ai_xml_generator.py:571`, :605 | та сама накопичена історія знову включається в кожен запит і генерацію | фактичне повторне передавання вхідного тексту; не повторне читання файлу |

### А5. Топ-15 файлів за байтами

М3 — `stat`, без читання вмісту. Виключені `venv`, `.git`, `output`, `data` на будь-якій глибині, символічні посилання та назви потенційних секретів. Враховані приховані кеші й артефакти збірки; це топ локального дерева, не лише tracked-файлів. Замір до створення документів аудиту.

```python
from pathlib import Path
import os
rows = []
for base, dirs, files in os.walk('.'):
    dirs[:] = [d for d in dirs if d not in {'venv', '.git', 'output', 'data'}]
    for name in files:
        p = Path(base) / name
        if p.is_symlink() or name.startswith('.env') or any(
            x in name.lower() for x in ('secret', 'token', 'credential')):
            continue
        rows.append((p.stat().st_size, str(p)))
print(*sorted(rows, reverse=True)[:15], sep='\n')
```

| Файл | Байтів |
|---|---:|
| `exports/noire_epicentr.xml` | 76026697 |
| `exports/carvol_epicentr_new.xml` | 46382904 |
| `exports/carvol_epicentr.xml` | 44686148 |
| `shared/feeds/rozetka_feed.xml` | 40677503 |
| `.cache/toptul.xml` | 38425912 |
| `exports/victor_11_06.xml` | 22942743 |
| `exports/final_full.xml` | 22942743 |
| `claw-code/rust/target/release/deps/claw-cc5eead691d89c88` | 17567968 |
| `claw-code/rust/target/release/claw` | 17567968 |
| `claw-code/rust/target/release/libruntime.rlib` | 16992030 |
| `claw-code/rust/target/release/deps/libruntime-4d0d5cfc48a5de18.rlib` | 16992030 |
| `fixed_toptul.xml` | 16540970 |
| `.cache/sexopt_profile/startupCache/scriptCache-current.bin` | 13553864 |
| `shared/feeds/epicentr_feed.xml` | 12850302 |
| `claw-code/rust/target/release/deps/libruntime-4d0d5cfc48a5de18.rmeta` | 11799633 |

## Б. Перевірка чужих порад

Вердикт стосується буквального твердження про нашу Python-систему, а не загальної корисності технології. Відсутність доказу економії не дорівнює доказу нульової користі.

| № | Твердження | Вердикт і доказ |
|---|---|---|
| 1 | Агенти пересилають історію думок | **неправда** для перевіреного маршруту: передають type/description/priority/context/source/timestamp (`orchestrator/orchestrator.py:176`), не transcript. Router відкидає reasoning_content/ thought (`shared/utils/llm_router.py:79`, :118). Виняток: валідатор може локально парсити reasoning_content (`tools/toptul_rozetka_validate.py:101`), що не є обміном історіями між агентами. |
| 2 | Треба додати спільний стан, бо дані йдуть у prompt | **неправда** як діагноз відсутнього стану: Redis snapshot уже є (`orchestrator/orchestrator.py:39`), стан агентів читається SQL (:47). Дані справді вставляються у prompt (`agents/finance/finance_agent.py:133`), але наявність БД не звільняє модель від отримання потрібних фактів. |
| 3 | Потрібен LangGraph/CrewAI для стану | **не стосується нас** як обов’язкова умова: стан/черги вже обслуговує власний код (`orchestrator/orchestrator.py:152`, :185); конкретної проблеми, яку вирішує заміна фреймворку, тут не доведено. |
| 4 | Диф замість файлу дасть до 90% економії входу | **неправда** як виміряний результат для нас. Делегатор просить повний файл **на виході** (:50 у `tools/llm_delegate.py`), повторний **вхід** — коротке ТЗ й помилки (:176), без попереднього повного коду. Диф може бути корисний в іншому циклі редагування, але 90% не виміряно. |
| 5 | Усім агентам max_output_tokens 150–300 | **неправда** як універсальна межа: генератор повного Python-файлу (`tools/llm_delegate.py:50`), XML 2048 (`tools/ai_xml_generator.py:494`), NIM з повторами 3000/8000 (`tools/toptul_translate.py:221`) мають різні вимоги. Для короткої маршрутизації (:126 у orchestrator) бюджет варто випробувати окремо. |
| 6 | Потрібна векторна база замість логу | **неправда** як твердження про її відсутність: Qdrant уже має agent_memory/agent_skills (`embedding_service.py:17`, :20), пошук :59 і застосування `shared/utils/skills_indexer.py:45`. Історія XML-чату — окреме джерело зростання, не доказ потреби ще однієї бази. |
| 7 | Оркестратор має лишати 3 перші + 5 останніх рядків | **не стосується нас** як універсальна формула: runtime-оркестратор маршрутизує завдання (:100), а CLI-делегатори вже мають межі 4000/1200 та 1500/3000 символів (А3). Довільний рядок XML може бути великим; краще ліміт символів і структурований список помилок, не фіксовані 8 рядків. |
| 8 | Гарячий system prompt треба кешувати Gemini Context Caching | **не стосується нас** як доведений першочерговий крок: Gemini body містить один user text, без окремого system/cachedContent (`shared/utils/llm_router.py:100`); повторний промпт делегатора змінюється (:176). Кандидат на стабільний system є в Anthropic XML-чаті (:495), але це інший канал. Пороги, ціна й користь Gemini-кешу без мережі/usage не перевірені. |

Розбіжність із консультацією: формулювання «довгий вивід — не зроблено» у `docs/research/EFFICIENCY_CONSULT.md:22` надто загальне: обидва перевірені делегатори вже обрізають вивід (А3). Не доведено, що всі CLI-виводи автоматично потрапляють до промптів.

## В. Що робити нам

Порядок — інженерна оцінка ефекту/складності, **не виміряна економія**. Усі пункти — пропозиції окремих завдань менеджеру. За `AGENTS.md:20` поточний крок не дозволяє змінювати бойові `tools/`, `agents/`, `shared/`; тут нічого не виправлено. Жоден пункт не потребує публікації товарів або зовнішніх дій без дозволу.

1. **Провести бюджет до Ollama.** `shared/utils/llm_router.py:125`, `shared/utils/ollama_worker.py:21`: передавати необов’язковий бюджет у `options.num_predict`, протягнути його через задачу черги; окремі значення для маршрутизації, тексту й коду. Перевірка: підроблений транспорт фіксує payload, потім дозволений менеджером порівняльний прогін рахує валідні результати, обрізані відповіді, вихідні токени й повтори на незмінному наборі.
2. **Додати облік usage, перш ніж обіцяти відсотки.** `shared/utils/llm_router.py:162`: нині є тільки prompt_len/text_len/ms; збирати доступні лічильники провайдера й причину завершення, без тексту промптів та приватних даних. Перевірка: фікстури відповідей і агрегація токенів на одну успішну задачу, включно з невдалими спробами.
3. **Обмежити історію XML-помічника.** `tools/ai_xml_generator.py:570`: тримати погоджені вимоги окремо та передавати лише потрібні останні репліки; не втрачати початкові джерела/обмеження. Перевірка: для однакового сценарію порівняти суму символів messages на кожному ході та коректність XML; кількість ходів фіксувати в експерименті.
4. **Зберігати повний лог перевірки окремо, віддавати структуровані помилки.** `tools/llm_delegate.py:90` і `/home/tekken/affiliate-sales-pilot/scripts/codex_task.py:190`: зберегти чинні межі, додати шлях до повного артефакту та перелік FAILED замість лише хвоста. Перевірка на синтетичному довгому падінні: усі ідентифікатори помилок доступні, preview обмежений, повний лог відтворюється. Інший репозиторій також потребує окремого дозволеного завдання.
5. **Дати MCP читання уривків.** `shared/mcp_servers/filesystem_mcp.py:53`, :72, :86: параметри offset/limit і явні total/truncated; маскувати приватне до скорочення. Перевірка: зразки А3, точні довжини TextContent, відсутність пропусків/дублів при послідовному читанні сторінок.
6. **Прибрати зайві читання в route_task.** `orchestrator/orchestrator.py:101`, :102 та `shared/utils/skill_loader.py:45`: прибрати невикористані результати, уникнути подвійного відкриття при повному завантаженні. Перевірка: підроблені reader/Redis рахують виклики; prompt і рішення не змінюються. Очікуваний виграш — I/O та затримка, не доведена економія токенів.

## Не перевірено і чому

- Реальні секретні налаштування, активні серверні служби, API, дані БД, частоти задач і вартість: заборона зовнішніх дій та читання секретів (`AGENTS.md:23`, :24). Статично наявний модуль не означає, що він запущений.
- Токени провайдерів, кеш-хіти та відсотки економії: router журналює символи, а не usage (`shared/utils/llm_router.py:162`); історичні приватні журнали не читались. Ділення символів на умовні «4» не застосовано.
- Реальний типовий diff, великі падіння pytest, розмір бойового SQL-дампа: немає дозволеного репрезентативного знімка; таблиця А3 дає локальні виміри й статичні межі замість вигаданих середніх.
- Автозавантаження всіх Claude-скілів і вартість зовнішньої менеджерської сесії: М1 вимірює тільки файли; не читались сесії менеджера.
- У вкладеному `claw-code` перевірено провайдерні транспорти, але не повний runtime-граф, конфігурацію кожного викликача й тести Rust. Python-завдання не доводить активного використання цього CLI.
