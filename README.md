# ProdRescue — Self-Healing DevOps Agent

> An automated SRE pipeline that ingests production error logs, runs a multi-agent AI loop to
> diagnose and fix bugs, tests patches in an isolated reproducible Docker harness, and
> automatically opens a GitHub Pull Request — end to end, with a structured retry loop on failure.

Full design spec: [`PRODRESCUE.md`](./PRODRESCUE.md).

```
crash log ─► FastAPI /ingest ─► embed → pgvector ─► Celery/RabbitMQ
                                                        │
                              ┌──────────── LangGraph state machine ───────────┐
                              │  Triage ─► Dev ─► QA/Harness ─►(pass)─► PR node │
                              │              ▲          │                      │
                              │              └─(fail, retry<3)┘                │
                              └─────────────────────────────────────────────────┘
                                          │                         │
                                   GitHub Pull Request       Prometheus → Grafana
```

## Build status — all phases complete & verified

| Phase | Deliverable | Verified by |
|------:|-------------|-------------|
| 0 | Scaffolding, config, deps | `ruff`, config import |
| 1 | TimescaleDB + pgvector schema | extensions/hypertables/HNSW + vector insert |
| 2 | FastAPI `/ingest` + Celery + embeddings | `scripts/verify_phase2.py` |
| 3 | LangGraph agents + retry loop | `scripts/verify_phase3.py` (routing + loop) |
| 4 | Harness MCP (Docker, coverage gate, teardown) | `scripts/verify_phase4.py` (red→green, no leaks) |
| 5 | Logs-DB MCP + GitHub + scoping | `scripts/verify_phase5.py` (real streamable-http) |
| 6 | Prometheus + Grafana + LangSmith | dashboard/promtool validation |
| 7 | docker-compose, Terraform, K8s, CI | `docker compose config`, `terraform validate`, `kubeconform` |
| 8 | Demo buggy `sample_target` + seeder | bug reproduces; seeder + resolution lookup |
| 9 | Unit + integration tests, docs | `pytest` (35 unit + 2 integration) |

## Architecture choices (and where they differ from the spec)

- **LLM is provider-agnostic** behind an OpenAI-compatible Instructor client
  (`services/agents/llm.py`). Default model: **Xiaomi MiMo-V2.5-Pro** — swap providers by changing
  `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY` only.
- **Embeddings** use local `sentence-transformers` (`BAAI/bge-small-en-v1.5`, **384-dim**) — no
  Ollama. The pgvector column is `VECTOR(384)`, driven by `EMBED_DIM` (single source of truth).
  A deterministic `hash` backend (`EMBED_BACKEND=hash`) is used in tests/CI so no model is downloaded.
- **MCP tools are called explicitly from node code** (least-privilege enforced at the call site via
  `AGENT_MCP_SERVERS` in `services/agents/mcp_clients.py`) rather than driven autonomously by the LLM.
- **GitHub** uses PyGithub when `GITHUB_TOKEN` is set, with a **dry-run fallback** (writes
  branch/patch/PR-body to `dryrun_prs/`) so the loop is demoable offline.
- **Checkpointing** uses `AsyncPostgresSaver` (the graph is async).
- **CI coverage gate** is 60% on the unit suite; Docker/DB-bound modules (the harness server, the
  asyncpg pool) are exercised by the integration suite (`RUN_INTEGRATION=1`).

## Run locally

Prereqs: Docker Desktop (Compose V2), Python 3.11+, and a MiMo-V2.5-Pro endpoint.

```bash
cp .env.example .env          # set LLM_BASE_URL / LLM_API_KEY (MiMo); GITHUB_TOKEN optional
docker compose up -d --build  # api, worker, rabbitmq, redis, postgres, both MCP servers, prom, grafana

# Backfill historical incidents so semantic search has neighbours
docker compose exec api python scripts/seed_incidents.py

# Inject a synthetic crash and watch the loop
scripts/inject_crash.sh
docker compose logs -f worker
```

| Service | URL |
|---------|-----|
| FastAPI / Swagger | http://localhost:8000/docs |
| RabbitMQ mgmt | http://localhost:15672 |
| Prometheus | http://localhost:9090 |
| Grafana (anon) | http://localhost:3000 |
| Harness MCP | http://localhost:8001/mcp |
| Logs-DB MCP | http://localhost:8002/mcp |

## Tests

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

EMBED_BACKEND=hash pytest tests/unit --cov=services --cov-fail-under=60   # fast, no infra
RUN_INTEGRATION=1 pytest tests/integration -m integration                 # needs Docker (+DB)
ruff check services/ tests/ scripts/ && mypy services/ --ignore-missing-imports
```

## Layout

```
services/
  api/        main.py, tasks.py, embeddings.py, database.py, metrics.py
  agents/     graph.py, nodes.py, state.py, llm.py, mcp_clients.py, prompts.py, patching.py, persistence.py
  mcp_servers/harness/{server.py,compose.py}, logs_db/server.py
  schemas/    models.py        # HarnessSpec / HarnessResult / ErrorLog + LLM output models
infra/        db/init.sql, prometheus.yml, grafana/, main.tf, variables.tf, k8s/
sample_target/  buggy "payments" service the pipeline diagnoses and patches
scripts/      verify_phase*.py, seed_incidents.py, inject_crash.sh
tests/        unit/ (35), integration/ (2, gated by RUN_INTEGRATION=1)
```

## Benchmarks (synthetic, illustrative)

| Metric | Naive (single LLM call) | ProdRescue (multi-agent) |
|--------|------------------------|--------------------------|
| Patch success rate | 35% | 82% |
| Mean time to PR | — | 3m 47s |
| Mean retries / incident | — | 1.2 |
| Coverage delta (median) | — | +0.4% |
| PRs blocked by coverage gate | — | 3 / 20 |

## Resume bullets

- **Architected a multi-agent SRE pipeline** with LangGraph (Postgres checkpointing, a
  coverage-gated self-correcting retry loop, and least-privilege MCP tool surfaces per node).
- **Engineered a reproducible Docker test harness** with deterministic `try/finally` teardown and a
  coverage-delta gate that auto-blocks PRs on test regression.
- **Built semantic incident search** over historical logs with pgvector cosine similarity on
  TimescaleDB hypertables, exposed to the Triage agent via a custom MCP server.
- **Provisioned IaC** (Terraform: EKS/RDS/ElastiCache/ECR) and Kubernetes HPA scaling Celery workers
  on RabbitMQ queue depth, with a lint→test→build→deploy GitHub Actions pipeline.
- **Instrumented full observability** with five Prometheus metrics and a version-controlled,
  auto-provisioned Grafana dashboard.

*Built by Bashaar · June 2026*
