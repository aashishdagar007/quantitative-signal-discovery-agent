-- =============================================================
--  AI Trading System — PostgreSQL Initialization Script
--  Runs once when the postgres container is first created.
-- =============================================================

-- Ensure UTF-8 encoding
SET client_encoding = 'UTF8';

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- =============================================================
--  RBAC Roles Reference (enforced at application layer)
--  admin   — Full system access, user management, kill-switch
--  quant   — Strategy/model management, backtesting, AI Desk
--  trader  — View signals, manage own positions
--  viewer  — Read-only dashboard access
-- =============================================================

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    uuid        UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    username    VARCHAR(64) UNIQUE NOT NULL,
    email       VARCHAR(128) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role        VARCHAR(16) NOT NULL DEFAULT 'viewer'
                    CHECK (role IN ('admin', 'quant', 'trader', 'viewer')),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_login  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users (username);
CREATE INDEX IF NOT EXISTS idx_users_role     ON users (role);

-- Positions table
CREATE TABLE IF NOT EXISTS positions (
    id           SERIAL PRIMARY KEY,
    uuid         UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    symbol       VARCHAR(32) NOT NULL,
    asset_class  VARCHAR(16) NOT NULL CHECK (asset_class IN ('crypto', 'forex')),
    side         VARCHAR(8)  NOT NULL CHECK (side IN ('long', 'short')),
    quantity     NUMERIC(20, 8) NOT NULL,
    entry_price  NUMERIC(20, 8) NOT NULL,
    current_price NUMERIC(20, 8),
    status       VARCHAR(16) NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'closed', 'pending')),
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    opened_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_positions_symbol  ON positions (symbol);
CREATE INDEX IF NOT EXISTS idx_positions_status  ON positions (status);
CREATE INDEX IF NOT EXISTS idx_positions_user_id ON positions (user_id);

-- Orders table
CREATE TABLE IF NOT EXISTS orders (
    id           SERIAL PRIMARY KEY,
    uuid         UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    order_id     VARCHAR(64) UNIQUE,
    symbol       VARCHAR(32) NOT NULL,
    asset_class  VARCHAR(16) NOT NULL,
    side         VARCHAR(8)  NOT NULL,
    order_type   VARCHAR(16) NOT NULL DEFAULT 'market',
    quantity     NUMERIC(20, 8) NOT NULL,
    price        NUMERIC(20, 8),
    filled_price NUMERIC(20, 8),
    status       VARCHAR(16) NOT NULL DEFAULT 'pending',
    exchange     VARCHAR(32) NOT NULL DEFAULT 'binance',
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,
    position_id  INTEGER REFERENCES positions(id) ON DELETE SET NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at    TIMESTAMPTZ
);

-- AI Signals table
CREATE TABLE IF NOT EXISTS signals (
    id           SERIAL PRIMARY KEY,
    uuid         UUID DEFAULT uuid_generate_v4() UNIQUE NOT NULL,
    symbol       VARCHAR(32) NOT NULL,
    direction    VARCHAR(8)  NOT NULL CHECK (direction IN ('long', 'short', 'neutral')),
    confidence   NUMERIC(5, 2) NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    risk_score   NUMERIC(8, 6),
    consensus    TEXT,
    signature    TEXT,
    source       VARCHAR(32) NOT NULL DEFAULT 'ai_desk',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol     ON signals (symbol);
CREATE INDEX IF NOT EXISTS idx_signals_created_at ON signals (created_at DESC);

-- Audit Log (mirrors blockchain ledger for fast querying)
CREATE TABLE IF NOT EXISTS audit_log (
    id           SERIAL PRIMARY KEY,
    tx_id        VARCHAR(128) UNIQUE NOT NULL,
    block_index  INTEGER NOT NULL,
    event_type   VARCHAR(32) NOT NULL
                    CHECK (event_type IN ('trade', 'consensus', 'state_change', 'order', 'system')),
    payload      JSONB NOT NULL,
    block_hash   VARCHAR(256) NOT NULL,
    merkle_root  VARCHAR(256),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_type  ON audit_log (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at  ON audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_block_index ON audit_log (block_index);

-- ============================================================
--  Seed: Default admin + 4-person core development team
-- ============================================================
-- NOTE: Passwords are pre-hashed bcrypt placeholders.
--       The application will re-hash with production passwords
--       on first startup if users don't exist yet.
-- ============================================================
INSERT INTO users (username, email, hashed_password, role, is_active)
VALUES
    ('Lalit',   'lalit@trading.local',   '$2b$12$placeholder_hash_admin_lalit',   'admin',  TRUE),
    ('quant1',  'quant1@trading.local',  '$2b$12$placeholder_hash_quant1',        'quant',  TRUE),
    ('trader1', 'trader1@trading.local', '$2b$12$placeholder_hash_trader1',       'trader', TRUE),
    ('viewer1', 'viewer1@trading.local', '$2b$12$placeholder_hash_viewer1',       'viewer', TRUE)
ON CONFLICT (username) DO NOTHING;
