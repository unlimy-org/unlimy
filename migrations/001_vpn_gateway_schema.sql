-- Unified schema for VPN gateway + Telegram bot
-- Kept in sync with node-cluster/postgres/init/01-schema.sql
-- All CREATE IF NOT EXISTS — safe to run after docker init scripts.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS users (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tg_id      BIGINT UNIQUE NOT NULL,
    username   VARCHAR(255),
    first_name VARCHAR(255),
    language   VARCHAR(16) DEFAULT 'en',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS plans (
    id             BIGSERIAL PRIMARY KEY,
    name           VARCHAR(128) NOT NULL,
    duration_days  INTEGER NOT NULL CHECK (duration_days > 0),
    price_usd      NUMERIC(10, 2) NOT NULL CHECK (price_usd >= 0),
    device_limit   INTEGER NOT NULL DEFAULT 1 CHECK (device_limit >= 0),
    UNIQUE(name, duration_days)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_plans_name_duration ON plans(name, duration_days);

CREATE TABLE IF NOT EXISTS servers (
    id          BIGSERIAL PRIMARY KEY,
    name        VARCHAR(64) UNIQUE NOT NULL,
    country     VARCHAR(64) NOT NULL,
    ip_address  VARCHAR(45) NOT NULL,
    ram         VARCHAR(32),
    cpu         VARCHAR(32),
    disk        VARCHAR(32),
    status      VARCHAR(32) NOT NULL DEFAULT 'active',
    base_url    VARCHAR(512) NOT NULL,
    username    VARCHAR(255) NOT NULL,
    password    VARCHAR(255) NOT NULL,
    login_path  VARCHAR(128) NOT NULL DEFAULT '/login',
    api_prefix  VARCHAR(128) NOT NULL DEFAULT '/panel/api',
    public_host VARCHAR(255),
    weight      INTEGER NOT NULL DEFAULT 1 CHECK (weight >= 1 AND weight <= 100),
    enabled     BOOLEAN NOT NULL DEFAULT true,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS orders (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id             BIGINT NOT NULL REFERENCES plans(id),
    server_id           BIGINT REFERENCES servers(id) ON DELETE SET NULL,
    protocol            VARCHAR(32) NOT NULL DEFAULT 'vless',
    amount_usd          NUMERIC(10, 2) NOT NULL CHECK (amount_usd >= 0),
    status              VARCHAR(32) NOT NULL DEFAULT 'pending',
    subscription_token  VARCHAR(64) UNIQUE,
    external_order_id   VARCHAR(255),
    payment_method      VARCHAR(64) NOT NULL DEFAULT 'stars',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS connections (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_id   BIGINT NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    order_id    BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    protocol    VARCHAR(32) NOT NULL DEFAULT 'vless',
    client_uuid VARCHAR(64) NOT NULL,
    inbound_id  INTEGER NOT NULL,
    total_gb    BIGINT NOT NULL DEFAULT 0,
    limit_ip    INTEGER NOT NULL DEFAULT 0,
    vless_uri   TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id         BIGSERIAL PRIMARY KEY,
    order_id   BIGINT NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    provider   VARCHAR(64) NOT NULL,
    amount_usd NUMERIC(10, 2) NOT NULL CHECK (amount_usd >= 0),
    status     VARCHAR(32) NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS settings (
    key   VARCHAR(128) PRIMARY KEY,
    value TEXT
);

-- Support (bot-only tables)
CREATE TABLE IF NOT EXISTS support_tickets (
    id         BIGSERIAL PRIMARY KEY,
    tg_id      BIGINT NOT NULL,
    status     VARCHAR(32) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS support_ticket_messages (
    id           BIGSERIAL PRIMARY KEY,
    ticket_id    BIGINT NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
    sender_tg_id BIGINT NOT NULL,
    body         TEXT NOT NULL,
    is_admin     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_connections_user_id ON connections(user_id);
CREATE INDEX IF NOT EXISTS idx_connections_order_id ON connections(order_id);
CREATE INDEX IF NOT EXISTS idx_connections_expires_at ON connections(expires_at);
CREATE INDEX IF NOT EXISTS idx_connections_client_uuid ON connections(client_uuid);
CREATE INDEX IF NOT EXISTS idx_payments_order_id ON payments(order_id);
CREATE INDEX IF NOT EXISTS idx_servers_status ON servers(status);
CREATE INDEX IF NOT EXISTS idx_servers_country ON servers(country);
CREATE UNIQUE INDEX IF NOT EXISTS idx_servers_name ON servers(name);
CREATE INDEX IF NOT EXISTS idx_support_tickets_tg_id ON support_tickets(tg_id);
