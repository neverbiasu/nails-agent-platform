# nails-agent-platform

AI nail trend analysis + consumer try-on. FastAPI backend, multi-agent pipeline (openai-agents SDK), SQLite for state, and ComfyUI Cloud for real try-on generation. Streamlit UIs are interim; Next.js frontend is in progress.

## Architecture

```
  ┌──────────────────────────────────────────────────────────────────┐
  │ B 端运营链路（POST /api/v1/trigger）                               │
  │                                                                  │
  │  TriggerGateway → Orchestrator.run_pipeline()                    │
  │       ↓ EventLog: TriggerEvent                                   │
  │  TrendScoutAgent (LLM) / trend_analyst (rule)                    │
  │       ↓ EventLog: TrendEvent                                     │
  │  ValueEvaluator + AssetGenerator (parallel)                      │
  │       ↓                                                          │
  │  CampaignAgent (LLM) / campaign_strategist (rule)                │
  │       ↓ EventLog: StrategyEvent                                  │
  │  Summarizer → CandidatePackage                                   │
  │       ↓ EventLog: SummaryEvent                                   │
  │  ReviewerGuardrail (rules + LLM) → ReviewDecision                │
  │       ↓ EventLog: ReviewEvent  candidate_packages(pending_human) │
  │  [HITL] POST /api/v1/review/approve                              │
  │       ↓ EventLog: HumanApprovalEvent                             │
  │  ActionExecutor → XHS draft / OpenClaw webhook                   │
  │       ↓ EventLog: ActionEvent                                    │
  └──────────────────────────────────────────────────────────────────┘

  ┌──────────────────────────────────────────────────────────────────┐
  │ C 端试戴链路                                                       │
  │                                                                  │
  │  POST /hand/analyze  → MediaPipe 手型 + 肤色分析                   │
  │  POST /sessions      → 创建会话 + 自动 Round1 推荐                 │
  │  POST /sessions/{id}/recommendations/round2  → 视觉相似度重排      │
  │  POST /api/v1/tryon/submit → ComfyUI FLUX.2 Klein 9B 渲染        │
  │  GET  /api/v1/tryon/{job_id} → 轮询结果                           │
  └──────────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────────┐
  │ 服务层                                                            │
  │  FastAPI :8000  →  SQLite ~/.nails_agent/memory.db               │
  │                    event_log + candidate_packages (MVP 新增)     │
  │  Streamlit B端 :8501  (过渡期，Next.js frontend 开发中)            │
  │  Streamlit C端 :8503  (过渡期)                                    │
  │  Caddy :8080  (聚合代理)                                          │
  └─────────────────────────────────────────────────────────────────┘
```

## First-time setup

```bash
pip install -e ".[demo,consumer,dev]"

# Seed SQLite style library (idempotent)
python -m nails_agent.services.seed_loader

# Verify tables
sqlite3 ~/.nails_agent/memory.db ".tables"
# → behavior_events   candidate_packages  event_log  ...
```

## Running locally

```bash
./scripts/dev.sh
```

Starts FastAPI, both Streamlit apps, and Caddy. Endpoints:

| URL | 服务 |
|-----|------|
| `http://localhost:8080/` | Merchant Streamlit dashboard |
| `http://localhost:8080/user/` | Consumer try-on |
| `http://localhost:8080/api/health` | FastAPI health check |

Without Caddy: merchant `:8501`, consumer `:8503`, API `:8000`.

## MVP API quick reference (B端)

```bash
# 触发 pipeline（返回 trigger_id）
curl -X POST http://localhost:8000/api/v1/trigger \
  -H 'content-type: application/json' \
  -d '{"source":"manual","keywords":["法式甲","猫眼"]}'

# 轮询 EventLog
curl "http://localhost:8000/api/v1/events?trigger_id=<trigger_id>"

# HITL 确认审查
curl -X POST http://localhost:8000/api/v1/review/approve \
  -H 'content-type: application/json' \
  -d '{"trigger_id":"<trigger_id>","decision":"pass"}'

# 执行发布
curl -X POST http://localhost:8000/api/v1/action/publish \
  -H 'content-type: application/json' \
  -d '{"trigger_id":"<trigger_id>","platform":"xhs"}'
```

## Consumer flow quick reference (C端)

```bash
# 1) Create session from hand photo
SID=$(curl -s -F image=@consumer/images/image001.png http://localhost:8000/sessions | jq -r .session.session_id)

# 2) Round 1 recommendations (auto-generated on session create)
curl -s "http://localhost:8000/sessions/$SID/recommendations/latest" | jq '.items[0:3]'

# 3) Try-on (flat API, for Next.js)
JID=$(curl -s -X POST http://localhost:8000/api/v1/tryon/submit \
  -H 'content-type: application/json' \
  -d "{\"image_base64\":\"$(base64 -i consumer/images/image001.png)\",\"style_id\":\"STYLE001\"}" | jq -r .job_id)

curl "http://localhost:8000/api/v1/tryon/$JID"   # poll until status=done
```

## Environment variables

| Var | Default | Notes |
|-----|---------|-------|
| `COMFYUI_API_KEY` | — | Required for real try-on rendering |
| `ANTHROPIC_API_KEY` | — | LLM review in ReviewerGuardrail layer 2 |
| `MODELSCOPE_API_KEY` | — | Primary LLM (Qwen3-235B) |
| `OPENROUTER_API_KEY` | — | Fallback LLM (Claude Sonnet) |
| `XHS_GO_BASE_URL` | `http://localhost:18060` | XHS Go service for draft creation |
| `OPENCLAW_WEBHOOK_URL` | — | OpenClaw message platform webhook |
| `NAILS_DATA_DIR` | `web/data` | Trend signals + style library JSON |
| `NAILS_OUTPUT_DIR` | `web/output` | Pipeline artifact output directory |

Without any LLM key, the pipeline runs in rule-based mode (no external API calls, CI-safe).

## Documentation

| Doc | 内容 |
|-----|------|
| [docs/develop/architecture.md](docs/develop/architecture.md) | 系统架构、9 角色 MAS、Memory Fabric |
| [docs/develop/agents.md](docs/develop/agents.md) | Agent 层详细规范（含 MVP 新增 5 个模块） |
| [docs/develop/api_reference.md](docs/develop/api_reference.md) | REST API 完整参考 |
| [docs/develop/developer_guide.md](docs/develop/developer_guide.md) | 本地开发、Next.js 前端启动 |
| [docs/develop/kanban.md](docs/develop/kanban.md) | KANBAN：MVP 任务跟踪（A0–A12, B0–B9） |
| [docs/index.md](docs/index.md) | 文档导航首页 |
