# nails-agent-platform

AI nail trend analysis + consumer try-on. A FastAPI backend, two Streamlit
front-ends (merchant default / consumer interim), SQLite for state, and
ComfyUI Cloud for real try-on generation.

## Architecture (post-merge)

```
                       FastAPI :8000  (nails_agent.api.main)
                       ├── /chat /pipeline/* /memory/* /tryon  (merchant)
                       └── /hand/analyze /sessions/* /styles    (consumer)
                                        │
                                        ▼
                       nails_agent.services.*    ←  business logic
                       ├── hand_analyzer         (MediaPipe + rules)
                       ├── style_library         (SQLite reader)
                       ├── recommendation        (round 1 + 2)
                       ├── session_service       (SQLite-backed)
                       └── interaction           (real ComfyUI try-on)
                                        │
                                        ▼
                       SQLite at ~/.nails_agent/memory.db
                       Uploads at ~/.nails_agent/uploads/

  Routes via Caddy on :8080
    /          → merchant Streamlit  (demo/app.py)
    /user/     → consumer Streamlit  (demo_v1/app.py — interim, until JS rewrite)
    /api/      → FastAPI
```

## First-time setup

```bash
pip install -e ".[demo,consumer,dev]"          # consumer extras pull MediaPipe + OpenCV

# Seed SQLite from data/*.json (idempotent — safe to re-run)
python -m nails_agent.services.seed_loader

# Verify
sqlite3 ~/.nails_agent/memory.db ".tables"
```

`data/` holds the merged style library + reference profiles + visual features.
`demo_v1/data/` and `demo_v1/outputs/` are kept temporarily for migration
safety; once SQLite parity is confirmed they can go.

## Running locally

```bash
./scripts/dev.sh
```

That starts FastAPI, both Streamlit apps, and Caddy. Hit:

- `http://localhost:8080/`        — merchant (trends / campaigns)
- `http://localhost:8080/user/`   — consumer try-on
- `http://localhost:8080/api/health`

Logs go to `logs/<svc>.log`. Ctrl-C stops everything.

If you don't have Caddy installed, the script falls back to direct ports:

- merchant `:8501`, consumer `:8503`, API `:8000`

## Environment

| Var | Default | Notes |
|---|---|---|
| `COMFYUI_API_KEY` | – | Required for real try-on. Without it `interaction.run_tryon` returns a failed job. |
| `NAILS_API_BASE` | `http://localhost:8000` | Consumer Streamlit uses this to reach FastAPI. |
| `NAILS_DATA_DIR_V2` | `<repo>/data` | Where seed JSONs live. |
| `NAILS_TRYON_WORKFLOW` | `workflows/nail_tryon_klein_9b.json` | ComfyUI workflow used by `/sessions/{id}/tryon`. |

## Consumer flow (end-to-end test)

```bash
# 1) Hand analysis
curl -s -F image=@demo_v1/images/image001.png http://localhost:8000/hand/analyze | jq '{ok,hand_shape,skin_tone,undertone}'

# 2) Create session (also auto-generates Round 1)
SID=$(curl -s -F image=@demo_v1/images/image001.png http://localhost:8000/sessions | jq -r .session.session_id)
echo "session: $SID"

# 3) Round 1 recommendations
curl -s -X POST http://localhost:8000/sessions/$SID/recommendations/round1 | jq '.items[0:3] | .[] | {rank,style_id,total_score,reason_tags}'

# 4) Record a click
curl -s -X POST http://localhost:8000/sessions/$SID/events \
  -H 'content-type: application/json' \
  -d '{"style_id":"STYLE001","event_type":"click"}' | jq

# 5) Round 2 (requires at least one event)
curl -s -X POST http://localhost:8000/sessions/$SID/recommendations/round2 | jq '.items[0:3]'

# 6) Real try-on (requires COMFYUI_API_KEY in env)
curl -s -X POST http://localhost:8000/sessions/$SID/tryon \
  -H 'content-type: application/json' \
  -d '{"style_id":"STYLE001"}' | jq '{status,result_image_url,duration_s,error_message}'
```

## Things that moved in the merge

| Old path | New path |
|---|---|
| `demo_v1/src/hand_analysis.py` | `nails_agent/services/hand_analyzer.py` |
| `demo_v1/src/recommendation.py` | `nails_agent/services/recommendation.py` |
| `demo_v1/src/session_service.py` | `nails_agent/services/session_service.py` |
| `demo_v1/src/interaction.py` | `nails_agent/services/interaction.py` (no more mock) |
| `demo_v1/src/storage.py` | deleted — SQLite now |
| `demo_v1/data/nail_styles_v1.json` | `data/nail_styles_v2.json` (merged with V0 lib) |
| `demo_v1/data/*.json` (others) | `data/*.json` |

The consumer Streamlit at `demo_v1/app.py` is now a thin client over the
FastAPI endpoints. It exists as the QA-able interim UI until the Next.js /
Vue rewrite ships; nothing in the platform depends on it.
