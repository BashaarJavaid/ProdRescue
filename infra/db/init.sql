-- ProdRescue schema bootstrap.
-- Runs automatically via /docker-entrypoint-initdb.d on first Postgres start.
-- NOTE: embedding dimension VECTOR(384) must match settings.embed_dim
-- (BAAI/bge-small-en-v1.5). Change both together if you swap embedding models.

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ── error_logs ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS error_logs (
  id          UUID        NOT NULL DEFAULT gen_random_uuid(),
  occurred_at TIMESTAMPTZ NOT NULL,
  service     TEXT        NOT NULL,
  message     TEXT        NOT NULL,
  stacktrace  TEXT,
  embedding   VECTOR(384),
  resolved    BOOLEAN     NOT NULL DEFAULT FALSE,
  metadata    JSONB       NOT NULL DEFAULT '{}',
  PRIMARY KEY (id, occurred_at)               -- hypertable PK must include the time column
);

SELECT create_hypertable('error_logs', 'occurred_at', if_not_exists => TRUE);

-- HNSW index for fast approximate nearest-neighbour cosine search.
CREATE INDEX IF NOT EXISTS error_logs_embedding_hnsw
  ON error_logs USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS error_logs_service_idx ON error_logs (service, occurred_at DESC);

-- ── harness_results ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS harness_results (
  run_id             UUID        NOT NULL DEFAULT gen_random_uuid(),
  log_id             UUID,
  recorded_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  passed             BOOLEAN     NOT NULL,
  coverage_delta     FLOAT       NOT NULL,   -- negative = deleted tests → block PR
  failed_assertions  TEXT[]      NOT NULL DEFAULT '{}',
  duration_ms        INTEGER     NOT NULL,
  teardown_clean     BOOLEAN     NOT NULL DEFAULT TRUE,
  retry_attempt      INTEGER     NOT NULL DEFAULT 0,
  patch_diff         TEXT,
  pr_url             TEXT,
  PRIMARY KEY (run_id, recorded_at)
);

SELECT create_hypertable('harness_results', 'recorded_at', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS harness_results_log_idx ON harness_results (log_id);
