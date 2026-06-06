-- migrate_browser_automation.sql
-- Таблиці для browser automation: сесії, ціни конкурентів, лог навчання
-- Запуск: docker exec -i agent_postgres psql -U agentadmin -d agentdb < migrate_browser_automation.sql

-- =============================================
-- 1. Сесії браузера (cookies, tokens, UA)
-- =============================================
CREATE TABLE IF NOT EXISTS browser_sessions (
    id              SERIAL PRIMARY KEY,
    site            VARCHAR(50) UNIQUE NOT NULL,  -- epicentr/rozetka/prom/grandinstrument
    account_id      VARCHAR(50),                   -- якщо кілька акаунтів
    cookies         JSONB,                         -- всі cookies
    local_storage   JSONB,                         -- localStorage (токени)
    headers         JSONB,                         -- Bearer токени
    user_agent      TEXT,                          -- фіксований UA
    proxy_used      VARCHAR(100),                  -- через який IP
    is_active       BOOLEAN DEFAULT TRUE,
    valid_until     TIMESTAMP,
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- =============================================
-- 2. Ціни конкурентів
-- =============================================
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

CREATE INDEX IF NOT EXISTS idx_competitor_sku
    ON competitor_prices(sku);
CREATE INDEX IF NOT EXISTS idx_competitor_marketplace
    ON competitor_prices(marketplace, sku);
CREATE INDEX IF NOT EXISTS idx_competitor_date
    ON competitor_prices(checked_at DESC);

-- Представлення: актуальні ціни конкурентів vs наші
CREATE OR REPLACE VIEW v_competitor_analysis AS
SELECT
    cp.sku,
    mp.name_uk,
    mp.price_our                        AS our_price,
    MIN(cp.price)                       AS min_competitor_price,
    MAX(cp.price)                       AS max_competitor_price,
    ROUND(AVG(cp.price), 2)             AS avg_competitor_price,
    COUNT(DISTINCT cp.competitor_name)  AS competitors_count,
    ROUND(mp.price_our - MIN(cp.price), 2) AS price_diff,
    CASE
        WHEN mp.price_our > MIN(cp.price) THEN 'дорожче'
        WHEN mp.price_our < MIN(cp.price) THEN 'дешевше'
        ELSE 'однаково'
    END                                 AS position,
    MAX(cp.checked_at)                  AS last_checked
FROM competitor_prices cp
JOIN my_products mp ON cp.sku = mp.sku
WHERE cp.checked_at >= NOW() - INTERVAL '24 hours'
GROUP BY cp.sku, mp.name_uk, mp.price_our;

-- =============================================
-- 3. Лог /learn команд (навчання агента через Telegram)
-- =============================================
CREATE TABLE IF NOT EXISTS skill_updates (
    id          SERIAL PRIMARY KEY,
    skill_file  VARCHAR(100) NOT NULL,  -- назва .md файлу
    instruction TEXT NOT NULL,          -- текст /learn команди
    applied_at  TIMESTAMP DEFAULT NOW(),
    applied_by  VARCHAR(50),            -- telegram user_id
    success     BOOLEAN DEFAULT TRUE,
    notes       TEXT                    -- що саме змінено
);

-- =============================================
-- 4. Маппінг артикулів Єпіцентру
-- =============================================
CREATE TABLE IF NOT EXISTS epicentr_sku_mapping (
    id                  SERIAL PRIMARY KEY,
    our_sku             VARCHAR(50) NOT NULL,    -- наш SKU (TOPTUL)
    epicentr_article    VARCHAR(50),             -- внутрішній ID Єпіцентру
    epicentr_product_id BIGINT,                  -- числовий ID товару
    epicentr_url        VARCHAR(500),            -- URL в кабінеті
    status              VARCHAR(20) DEFAULT 'draft', -- draft/active/rejected
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_epicentr_mapping_sku
    ON epicentr_sku_mapping(our_sku);
CREATE INDEX IF NOT EXISTS idx_epicentr_mapping_article
    ON epicentr_sku_mapping(epicentr_article);

-- =============================================
-- 5. Лог дій браузера (аудит)
-- =============================================
CREATE TABLE IF NOT EXISTS browser_action_log (
    id          SERIAL PRIMARY KEY,
    site        VARCHAR(50),
    action      VARCHAR(100),       -- login/export/import/confirm_order
    status      VARCHAR(20),        -- success/error/skipped
    details     JSONB,              -- додаткові дані
    screenshot  VARCHAR(200),       -- шлях до скріншоту
    duration_ms INTEGER,            -- час виконання
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_browser_log_site
    ON browser_action_log(site, created_at DESC);
