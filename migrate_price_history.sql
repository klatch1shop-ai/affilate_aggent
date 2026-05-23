-- migrate_price_history.sql
-- Створення таблиці history цін та індексів
-- Запуск: psql -U agentadmin -d agentdb -f migrate_price_history.sql

-- Таблиця history цін
CREATE TABLE IF NOT EXISTS price_history (
    id              SERIAL PRIMARY KEY,
    sku             VARCHAR(50) NOT NULL,
    date            DATE NOT NULL DEFAULT CURRENT_DATE,
    feed_price      NUMERIC(12,2) NOT NULL,   -- ціна з фіду TOPTUL (РРЦ)
    our_price       NUMERIC(12,2) NOT NULL,   -- наша ціна на маркетплейсі
    prev_feed_price NUMERIC(12,2),            -- попередня ціна фіду
    prev_our_price  NUMERIC(12,2),            -- попередня наша ціна
    feed_diff_pct   NUMERIC(6,2),             -- % зміни ціни фіду
    our_diff_pct    NUMERIC(6,2),             -- % зміни нашої ціни
    cpa_rate        NUMERIC(6,2),             -- CPA % що застосовано
    cpa_source      VARCHAR(255),             -- джерело CPA (category/group/default)
    available       BOOLEAN DEFAULT TRUE,     -- доступний у фіді
    stock           VARCHAR(10),              -- залишок (*, **, ***, ****)
    is_change       BOOLEAN DEFAULT FALSE,    -- чи є зміна відносно попереднього дня
    is_alert        BOOLEAN DEFAULT FALSE,    -- чи перевищує поріг алерту
    alert_reason    VARCHAR(255),             -- причина алерту
    prom_updated    BOOLEAN DEFAULT FALSE,    -- чи оновлено ціну на Prom
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Унікальний індекс: один запис на товар на день
CREATE UNIQUE INDEX IF NOT EXISTS idx_price_history_sku_date
    ON price_history (sku, date);

-- Індекс для швидкого пошуку по SKU
CREATE INDEX IF NOT EXISTS idx_price_history_sku
    ON price_history (sku);

-- Індекс для аналітики по датах
CREATE INDEX IF NOT EXISTS idx_price_history_date
    ON price_history (date);

-- Індекс для алертів
CREATE INDEX IF NOT EXISTS idx_price_history_alerts
    ON price_history (date, is_alert)
    WHERE is_alert = TRUE;

-- Індекс для змін
CREATE INDEX IF NOT EXISTS idx_price_history_changes
    ON price_history (date, is_change)
    WHERE is_change = TRUE;

-- Таблиця налаштувань цінового двигуна
CREATE TABLE IF NOT EXISTS price_engine_config (
    key             VARCHAR(100) PRIMARY KEY,
    value           TEXT NOT NULL,
    description     TEXT,
    updated_at      TIMESTAMP DEFAULT NOW()
);

-- Початкові налаштування
INSERT INTO price_engine_config (key, value, description) VALUES
    ('alert_threshold_pct',  '20',    'Поріг алерту у % зміни ціни'),
    ('alert_threshold_high', '15',    'Поріг алерту для товарів > high_price_threshold грн'),
    ('high_price_threshold', '1000',  'Ціна товару що вважається "дорогим" (грн)'),
    ('min_price',            '40',    'Мінімальна ціна продажу (грн)'),
    ('round_to',             '10',    'Крок округлення ціни (грн)'),
    ('history_days_keep',    '365',   'Скільки днів зберігати history'),
    ('stock_premium_pct',    '0',     '% надбавки для товарів з **** залишком (0 = вимкнено)'),
    ('last_full_sync',       'never', 'Дата останнього повного синку')
ON CONFLICT (key) DO NOTHING;

-- Представлення для аналітики: остання ціна кожного товару
CREATE OR REPLACE VIEW v_current_prices AS
SELECT DISTINCT ON (sku)
    sku,
    date,
    feed_price,
    our_price,
    cpa_rate,
    available,
    stock,
    feed_diff_pct,
    our_diff_pct,
    is_alert
FROM price_history
ORDER BY sku, date DESC;

-- Представлення для тижневої аналітики
CREATE OR REPLACE VIEW v_weekly_changes AS
SELECT
    sku,
    MIN(feed_price) as min_feed_price,
    MAX(feed_price) as max_feed_price,
    MIN(our_price)  as min_our_price,
    MAX(our_price)  as max_our_price,
    COUNT(*) FILTER (WHERE is_change) as change_count,
    COUNT(*) FILTER (WHERE is_alert)  as alert_count,
    COUNT(*) FILTER (WHERE NOT available) as unavailable_days,
    ROUND(AVG(feed_diff_pct) FILTER (WHERE feed_diff_pct IS NOT NULL), 2) as avg_daily_change
FROM price_history
WHERE date >= CURRENT_DATE - INTERVAL '7 days'
GROUP BY sku;

RAISE NOTICE 'Міграція price_history завершена успішно';
