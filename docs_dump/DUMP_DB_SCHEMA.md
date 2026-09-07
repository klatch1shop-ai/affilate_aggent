# DUMP_DB_SCHEMA.md — схема БД (з DDL-файлів репо)

> **СХЕМА ВЗЯТА З DDL-ФАЙЛІВ РЕПО, НЕ З ЖИВОЇ БД.** Доступу до живої `agentdb` немає — реальні колонки/кількості рядків заповнюються вручну (див. `SERVER_GAPS.md`).
> Таблиці, оголошені в репо: `agents, tasks, event_logs, products, alerts` (init.sql); `browser_sessions, competitor_prices, skill_updates, epicentr_sku_mapping, browser_action_log` (migrate_browser_automation.sql); `price_history, price_engine_config` (migrate_price_history.sql); `marketplace_api_methods` (infrastructure/api_methods.sql — 26KB INSERT-даних, тут не наведено).
> Views: `v_competitor_analysis, v_current_prices, v_weekly_changes`.
> ⚠️ Багато робочих таблиць (`my_products, carvol_products, katran_categories, *_cpa_rates, carvol_epicentr_cat_map, epicentr_brand_*, epicentr_required_attrs, rozetka_processed_orders, rozetka_category_mapping, toptul_epicentr_category_map` тощо) створюються кодом/вручну і **DDL для них у репо немає** — їх структура лише в живій БД (взяти через `\d+ <table>`, див. SERVER_GAPS.md).

---

## `infrastructure/init.sql`

```sql
CREATE TABLE IF NOT EXISTS agents (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,
    type        VARCHAR(50)  NOT NULL,
    status      VARCHAR(20)  NOT NULL DEFAULT 'idle',
    created_at  TIMESTAMP    DEFAULT NOW(),
    updated_at  TIMESTAMP    DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    agent_id        INTEGER REFERENCES agents(id),
    title           VARCHAR(255) NOT NULL,
    description     TEXT,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    priority        INTEGER DEFAULT 5,
    created_at      TIMESTAMP DEFAULT NOW(),
    started_at      TIMESTAMP,
    completed_at    TIMESTAMP,
    result          JSONB,
    error           TEXT
);

CREATE TABLE IF NOT EXISTS event_logs (
    id          BIGSERIAL PRIMARY KEY,
    agent_id    INTEGER REFERENCES agents(id),
    task_id     INTEGER REFERENCES tasks(id),
    level       VARCHAR(20) NOT NULL DEFAULT 'INFO',
    message     TEXT NOT NULL,
    metadata    JSONB,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS products (
    id              SERIAL PRIMARY KEY,
    external_id     VARCHAR(255),
    marketplace     VARCHAR(50) NOT NULL,
    title           VARCHAR(500),
    price           DECIMAL(12,2),
    old_price       DECIMAL(12,2),
    url             TEXT,
    category        VARCHAR(255),
    seller          VARCHAR(255),
    in_stock        BOOLEAN DEFAULT true,
    data            JSONB,
    scraped_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE(external_id, marketplace)
);

CREATE TABLE IF NOT EXISTS alerts (
    id          SERIAL PRIMARY KEY,
    level       VARCHAR(20) NOT NULL DEFAULT 'INFO',
    source      VARCHAR(100),
    title       VARCHAR(255) NOT NULL,
    message     TEXT,
    is_read     BOOLEAN DEFAULT false,
    created_at  TIMESTAMP DEFAULT NOW()
);

INSERT INTO agents (name, type, status) VALUES
    ('orchestrator',  'orchestrator', 'idle'),
    ('scraper',       'scraper',      'idle'),
    ('marketing',     'marketing',    'idle'),
    ('developer',     'developer',    'idle'),
    ('finance',       'finance',      'idle'),
    ('efficiency',    'efficiency',   'idle')
ON CONFLICT (name) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_event_logs_created_at ON event_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_products_marketplace ON products(marketplace);
CREATE INDEX IF NOT EXISTS idx_alerts_is_read ON alerts(is_read);
```

## `migrate_browser_automation.sql`

```sql
-- migrate_browser_automation.sql
-- Таблиці для browser automation: сесії, ціни конкурентів, лог навчання
-- Запуск: docker exec -i agent_postgres psql -U agentadmin -d agentdb < migrate_browser_automation.sql

-- 1. Сесії браузера (cookies, tokens, UA)
CREATE TABLE IF NOT EXISTS browser_sessions (
    id              SERIAL PRIMARY KEY,
    site            VARCHAR(50) UNIQUE NOT NULL,  -- epicentr/rozetka/prom/grandinstrument
    account_id      VARCHAR(50),
    cookies         JSONB,
    local_storage   JSONB,
    headers         JSONB,
    user_agent      TEXT,
    proxy_used      VARCHAR(100),
    is_active       BOOLEAN DEFAULT TRUE,
    valid_until     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- 2. Ціни конкурентів
CREATE TABLE IF NOT EXISTS competitor_prices (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(50) NOT NULL,
    marketplace     VARCHAR(20) NOT NULL,   -- prom/rozetka/epicentr
    competitor_name VARCHAR(100),
    competitor_url  VARCHAR(500),
    price           NUMERIC(12,2),
    in_stock        BOOLEAN DEFAULT TRUE,
    checked_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_competitor_sku ON competitor_prices(sku);
CREATE INDEX IF NOT EXISTS idx_competitor_marketplace ON competitor_prices(marketplace, sku);
CREATE INDEX IF NOT EXISTS idx_competitor_date ON competitor_prices(checked_at DESC);

CREATE OR REPLACE VIEW v_competitor_analysis AS
SELECT
    cp.sku, mp.name_uk, mp.price_our AS our_price,
    MIN(cp.price) AS min_competitor_price,
    MAX(cp.price) AS max_competitor_price,
    ROUND(AVG(cp.price), 2) AS avg_competitor_price,
    COUNT(DISTINCT cp.competitor_name) AS competitors_count,
    ROUND(mp.price_our - MIN(cp.price), 2) AS price_diff,
    CASE WHEN mp.price_our > MIN(cp.price) THEN 'дорожче'
         WHEN mp.price_our < MIN(cp.price) THEN 'дешевше'
         ELSE 'однаково' END AS position,
    MAX(cp.checked_at) AS last_checked
FROM competitor_prices cp
JOIN my_products mp ON cp.sku = mp.sku
WHERE cp.checked_at >= NOW() - INTERVAL '24 hours'
GROUP BY cp.sku, mp.name_uk, mp.price_our;

-- 3. Лог /learn команд
CREATE TABLE IF NOT EXISTS skill_updates (
    id          SERIAL PRIMARY KEY,
    skill_file  VARCHAR(100) NOT NULL,
    instruction TEXT NOT NULL,
    applied_at  TIMESTAMP DEFAULT NOW(),
    applied_by  VARCHAR(50),
    success     BOOLEAN DEFAULT TRUE,
    notes       TEXT
);

-- 4. Маппінг артикулів Єпіцентру
CREATE TABLE IF NOT EXISTS epicentr_sku_mapping (
    id                  SERIAL PRIMARY KEY,
    our_sku             VARCHAR(50) NOT NULL,
    epicentr_article    VARCHAR(50),
    epicentr_product_id BIGINT,
    epicentr_url        VARCHAR(500),
    status              VARCHAR(20) DEFAULT 'draft',
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_epicentr_mapping_sku ON epicentr_sku_mapping(our_sku);
CREATE INDEX IF NOT EXISTS idx_epicentr_mapping_article ON epicentr_sku_mapping(epicentr_article);

-- 5. Лог дій браузера (аудит)
CREATE TABLE IF NOT EXISTS browser_action_log (
    id          SERIAL PRIMARY KEY,
    site        VARCHAR(50),
    action      VARCHAR(100),
    status      VARCHAR(20),
    details     JSONB,
    screenshot  VARCHAR(200),
    duration_ms INTEGER,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_browser_log_site ON browser_action_log(site, created_at DESC);
```

## `migrate_price_history.sql`

```sql
-- migrate_price_history.sql — таблиця history цін та індекси
CREATE TABLE IF NOT EXISTS price_history (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(50) NOT NULL,
    date            DATE NOT NULL DEFAULT CURRENT_DATE,
    feed_price      NUMERIC(12,2) NOT NULL,   -- ціна з фіду TOPTUL (РРЦ)
    our_price       NUMERIC(12,2) NOT NULL,   -- наша ціна на маркетплейсі
    prev_feed_price NUMERIC(12,2),
    prev_our_price  NUMERIC(12,2),
    feed_diff_pct   NUMERIC(6,2),
    our_diff_pct    NUMERIC(6,2),
    cpa_rate        NUMERIC(6,2),
    cpa_source      VARCHAR(255),
    available       BOOLEAN DEFAULT TRUE,
    stock           VARCHAR(10),              -- *, **, ***, ****
    is_change       BOOLEAN DEFAULT FALSE,
    is_alert        BOOLEAN DEFAULT FALSE,
    alert_reason    VARCHAR(255),
    prom_updated    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_sku_date ON price_history (sku, date);
CREATE INDEX IF NOT EXISTS idx_price_history_sku ON price_history (sku);
CREATE INDEX IF NOT EXISTS idx_price_history_date ON price_history (date);
CREATE INDEX IF NOT EXISTS idx_price_history_alerts ON price_history (date, is_alert) WHERE is_alert = TRUE;
CREATE INDEX IF NOT EXISTS idx_price_history_changes ON price_history (date, is_change) WHERE is_change = TRUE;

CREATE TABLE IF NOT EXISTS price_engine_config (
    key             VARCHAR(100) PRIMARY KEY,
    value           TEXT NOT NULL,
    description     TEXT,
    updated_at      TIMESTAMP DEFAULT NOW()
);
INSERT INTO price_engine_config (key, value, description) VALUES
    ('alert_threshold_pct',  '20',    'Поріг алерту у % зміни ціни'),
    ('alert_threshold_high', '15',    'Поріг алерту для товарів > high_price_threshold грн'),
    ('high_price_threshold', '1000',  'Ціна товару що вважається "дорогим" (грн)'),
    ('min_price',            '40',    'Мінімальна ціна продажу (грн)'),
    ('round_to',             '10',    'Крок округлення ціни (грн)'),
    ('history_days_keep',    '365',   'Скільки днів зберігати history'),
    ('stock_premium_pct',    '0',     '% надбавки для товарів з **** залишком'),
    ('last_full_sync',       'never', 'Дата останнього повного синку')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE VIEW v_current_prices AS
SELECT DISTINCT ON (sku)
    sku, date, feed_price, our_price, cpa_rate, available, stock, feed_diff_pct, our_diff_pct, is_alert
FROM price_history ORDER BY sku, date DESC;

CREATE OR REPLACE VIEW v_weekly_changes AS
SELECT sku,
    MIN(feed_price) as min_feed_price, MAX(feed_price) as max_feed_price,
    MIN(our_price) as min_our_price, MAX(our_price) as max_our_price,
    COUNT(*) FILTER (WHERE is_change) as change_count,
    COUNT(*) FILTER (WHERE is_alert) as alert_count,
    COUNT(*) FILTER (WHERE NOT available) as unavailable_days,
    ROUND(AVG(feed_diff_pct) FILTER (WHERE feed_diff_pct IS NOT NULL), 2) as avg_daily_change
FROM price_history WHERE date >= CURRENT_DATE - INTERVAL '7 days' GROUP BY sku;
```

## `update_db_schema.py`

```python
import psycopg2, os
from dotenv import load_dotenv
load_dotenv()
DB_CONFIG = {"host": os.getenv("DB_HOST"), "port": os.getenv("DB_PORT", 5432),
    "database": os.getenv("DB_NAME"), "user": os.getenv("DB_USER"), "password": os.getenv("DB_PASSWORD")}

def update():
    conn = psycopg2.connect(**DB_CONFIG); cur = conn.cursor()
    cur.execute("""
        ALTER TABLE products
        ADD COLUMN IF NOT EXISTS title_epicentr TEXT,
        ADD COLUMN IF NOT EXISTS description_epicentr TEXT,
        ADD COLUMN IF NOT EXISTS specs_json JSONB,
        ADD COLUMN IF NOT EXISTS category_epicentr TEXT;
    """)
    conn.commit(); cur.close(); conn.close()
    print("✅ Таблиця 'products' оновлена.")

if __name__ == "__main__":
    update()
```

> `infrastructure/api_methods.sql` (26KB) — `CREATE TABLE marketplace_api_methods` + ~123 INSERT-рядки API-методів; повний текст — у репо/working-folder дампі, тут не наведено через обсяг даних.
