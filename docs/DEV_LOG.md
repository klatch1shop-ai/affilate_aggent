# DEV_LOG — Журнал розробки

> Формат: `## YYYY-MM-DD — <агент/автор> — <тема>`
> Кожен агент або оператор дописує підсумок своєї сесії в кінець файлу.
> Один запис = одна завершена задача або сесія.

---

## 2026-06-27 — orchestrator — Ініціалізація конфігів агентів та skills

**Що зроблено:**

Повний аналіз репозиторію (`affilate_aggent`, гілка `main`, коміт `2ef4fa3`) і створення структури Claude Code агентів:

**Створені файли:**

`.claude/agents/` — системні промпти для 5 агент-чатів:
- `epicentr-agent.md` — Єпіцентр: генератор Carvol XML, постобробка, маппінг категорій/атрибутів, замовлення
- `rozetka-agent.md` — Розетка + Катран: замовлення, GitHub-синк фідів, tg_dispatcher, TTN-матчинг
- `prom-agent.md` — Prom.ua: price_engine, щоденне оновлення цін, замовлення, XML каталогу Віктора
- `khoroshop-agent.md` — Khoroshop: заглушка (напрямок не реалізовано), план MVP
- `orchestrator.md` — координація системи, моніторинг сервера, daemon-перезапуски, git-правила

`.claude/skills/` — покрокові інструкції типових операцій:
- `epicentr/SKILL.md` — 7 skills: генерація XML (pipeline B), синхронізація цін, маппінг, attrs, daemon, якість
- `rozetka/SKILL.md` — 10 skills: daemon-перевірки, перезапуски, pipeline A/C, валідація, ТТН, Катран
- `prom/SKILL.md` — 10 skills: оновлення цін, price_engine, daemon, генерація XML, CPA, синхронізація
- `khoroshop/SKILL.md` — template: дослідження фіду, шаблон генератора, age-gate R&D

`docs/DEV_LOG.md` — цей файл.

**Ключові рішення зафіксовані в конфігах:**
- `shared/utils/pricing.py` формула: **залишити mark-up** (`rrc * (1+cpa)`), НЕ змінювати на gross-up
- Категорія 2883 в Єпіцентрі: **2848** (LED-лампи), джерело правди — кореневий `epicentr_postprocess.py`
- `tools/epicentr_postprocess.py` — застарілий (2883→2874), не використовувати

**Основа для конфігів:**
Дамп документації в `docs_dump/` (SYSTEM.md v1.1, TOOLS_CATALOG.md v1.0, SCRAPING.md v1.0, DUMP_INDEX.md, DUMP_DB_SCHEMA.md, DUMP_ENV_TEMPLATE.md, DUMP_GIT_LOG.md, SERVER_GAPS.md) + читання живого коду `pricing.py`, `price_engine.py`, `price_audit.py`.

**Коміт:** `feat: add 5 agent configs (epicentr/rozetka/prom/khoroshop/orchestrator) + skills + dev log`

---

<!-- Нові записи дописувати нижче -->
