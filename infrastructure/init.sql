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
