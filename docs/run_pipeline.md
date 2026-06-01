# Running the full pipeline (with live XHS + agent logs)

`scripts/run_pipeline.sh` runs the complete 4-step nails pipeline and streams
**both** relevant log sources into one terminal so you can watch the scraper and
the agents at the same time:

| Prefix       | Source                                                              | File                |
|--------------|--------------------------------------------------------------------|---------------------|
| `[xhs-mcp]`  | the xiaohongshu-mcp REST bridge — Playwright browser, search calls, bot-challenge / timeout details | `logs/xhs_bridge.log` |
| `[agent]`    | the Python pipeline — TrendScout → value eval → campaign → report, including the fetcher and LLM-fallback log lines | `logs/pipeline.log`   |

The 4 steps:

```
Step 1/4  趋势分析     TrendScoutAgent  → collect XHS signals, enrich tags (rules → text LLM → VLM)
Step 2/4  价值评估+素材  value evaluation & asset generation
Step 3/4  运营策略     CampaignAgent    → specific style cards (颜色·风格·场景), P0/P1 priority
Step 4/4  运营报告     report.json + style_cards.json
```

## Quick start

```bash
# Headful scraper (default), auto-login if the session is stale, then run.
scripts/run_pipeline.sh
```

On a fresh machine the script will, in order:

1. **Start the XHS bridge** on `:18060` (or reuse one that's already running).
2. **Check login** via `/api/v1/login/status`. If you're not logged in, it
   launches the QR login — **scan it with your secondary XHS app** and confirm.
3. **Probe** a single search to warn early if XHS is bot-challenging the scraper.
4. **Stream** `logs/xhs_bridge.log` as `[xhs-mcp]` while the pipeline runs as
   `[agent]`, also persisting the agent stream to `logs/pipeline.log`.
5. **Clean up** the bridge on exit (unless you started it yourself or pass
   `--keep-bridge`).

When it finishes, the results are in `web/output/`:

```bash
cat web/output/report.json          # full operating report
cat web/output/style_cards.json     # the generated style cards
ls  web/output/images/latest/raw/   # captured post images (TREND_*; *_cell* for 9-grid posts)
```

## Options

| Flag               | Effect                                                                        |
|--------------------|-------------------------------------------------------------------------------|
| `--headful`        | Visible browser scraper (**default**) — much less likely to be bot-challenged |
| `--headless`       | Headless scraper (CI / no display)                                            |
| `--login`          | Force a QR re-login before running (refresh cookies)                          |
| `--keep-bridge`    | Leave the bridge running after the pipeline exits                             |
| `--output-dir DIR` | Pipeline output dir (default `web/output`)                                    |
| `--data-dir DIR`   | Pipeline data dir (default `web/data`)                                        |
| `-h`, `--help`     | Show usage                                                                     |

### Examples

```bash
scripts/run_pipeline.sh --login                  # refresh cookies first, then run
scripts/run_pipeline.sh --headless --keep-bridge # CI-style run, keep bridge up
scripts/run_pipeline.sh --output-dir /tmp/run1   # write artifacts elsewhere
```

## Environment variables

Read from the shell or from `.env` (auto-loaded):

| Variable                     | Meaning                                                       | Default |
|------------------------------|---------------------------------------------------------------|---------|
| `XHS_MCP_HEADLESS`           | `true`/`false` — overridden by `--headful` / `--headless`     | `false` |
| `NAILS_XHS_SEARCH_DELAY_MIN` | per-keyword search throttle floor (seconds)                   | `3`     |
| `NAILS_XHS_SEARCH_DELAY_MAX` | per-keyword search throttle ceiling (seconds)                 | `7`     |
| `XHS_BRIDGE_NODE`            | explicit Node.js binary for the bridge (ABI 131 / Node 23)    | auto    |

The per-keyword throttle paces searches so a single run can't burst-trip XHS's
rate limiter.

## Watching the logs separately

The combined stream is the easiest view, but each source is also a plain file:

```bash
tail -F logs/xhs_bridge.log   # just the xiaohongshu-mcp bridge
tail -F logs/pipeline.log     # just the agent pipeline
```

> **Note on reusing a bridge.** The live `[xhs-mcp]` stream comes from
> `logs/xhs_bridge.log`, which is captured when **this script launches the
> bridge**. If a bridge is already running on `:18060` (e.g. started by
> `dev.sh` or by hand), the script reuses it but cannot redirect its output, so
> `[xhs-mcp]` may stay quiet. To guarantee a live bridge stream, stop any
> existing bridge first (`pkill -f xhs_rest_bridge`) and let the script start
> its own.

## Troubleshooting

**"probe search returned 0 results" / empty signals.**
XHS bot-challenges long-lived or headless scraper sessions — `login/status` can
say `is_logged_in: true` while searches still return `total: 0` because the
short-lived scraper cookies (`websectiga` / `acw_tc`) have expired. Fix:

```bash
scripts/run_pipeline.sh --login      # resets the session via QR, then runs
```

If it persists, fully reset the bridge and its browsers, then re-login:

```bash
pkill -f xhs_rest_bridge; pkill -f chrome-headless-shell
scripts/run_pipeline.sh --login      # starts a fresh headful bridge + login
```

**Node.js / `better-sqlite3` ABI error when the bridge starts.**
xhs-mcp's native module is built for Node 23 (ABI 131). The script auto-prefers
an NVM `v23.*` install; otherwise set `XHS_BRIDGE_NODE` to a matching binary.

**LLM quota / no-provider errors.**
The agents fall back across a chain of text and vision models automatically;
you'll see `♻️ 配额受限，切换模型 → …` in the `[agent]` stream. No action needed.

## Relationship to `scripts/dev.sh`

`dev.sh` launches the long-running **web stack** (bridge + FastAPI + Chat UI +
C-end try-on + Caddy). `run_pipeline.sh` is for a **single end-to-end pipeline
run** with both log streams in view — use it to verify trend → campaign → report
output without standing up the whole web stack.
