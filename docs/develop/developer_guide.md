# 开发者指南

> 本地跑通 + 扩展系统的操作手册。  
> 系统设计来源：[Notion PRD v4](https://www.notion.so/faych/34e5f3c4a139801e806cd49a2af60591) | 完整架构：[architecture.md](architecture.md) | Agent 设计：[agents.md](agents.md)

---

## 1. 前置条件

| 工具 | 版本要求 | 用途 |
|------|---------|------|
| Python | ≥ 3.11 | 主运行时 |
| uv | 任意新版 | 推荐包管理器 |
| Caddy | 任意新版 | 反向代理（可选，不装只影响统一端口） |
| Google Chrome | 任意 | Douyin/XHS CDP 数据源（可选） |
| Go runtime | ≥ 1.21 | XHS-MCP server（可选） |
| COMFYUI_API_KEY | — | 真实 AI 试戴图像生成（可选） |

**最小必要条件**（可跑通 demo）：只需 Python + uv + 至少一个 API key（`MODELSCOPE_API_KEY` 或 `OPENROUTER_API_KEY`）。无 API key 时系统以纯规则模式运行，不调用 LLM。

---

## 2. 首次初始化

```bash
# 1. 克隆项目
git clone git@github.com:neverbiasu/nails-agent-platform.git
cd nails-agent-platform

# 2. 安装依赖（demo + consumer + dev 三组）
pip install -e ".[demo,consumer,dev]"
# 或使用 uv（推荐）
uv pip install -e ".[demo,consumer,dev]"

# 3. 复制环境变量模板
cp .env.example .env
# 编辑 .env，至少填写一项：
#   MODELSCOPE_API_KEY=your_key   ← 主 LLM（Qwen3-235B）
#   OPENROUTER_API_KEY=your_key   ← 备用 LLM（Claude）
#   COMFYUI_API_KEY=your_key      ← 真实试戴图像生成
```

**注意**：首次运行 FastAPI 时 SQLite 会自动初始化（建表）。如需预加载款式和参考手型种子数据：

```bash
uv run python -m nails_agent.services.seed_loader
# 验证
sqlite3 ~/.nails_agent/memory.db "SELECT COUNT(*) FROM nail_styles_v2;"
```

---

## 3. 本地启动

```bash
./scripts/dev.sh
```

启动内容：

| 进程 | 端口 | 日志 |
|------|------|------|
| FastAPI（uvicorn --reload） | `:8000` | `logs/api.log` |
| Merchant Streamlit（web/app.py） | `:8501` | `logs/merchant.log` |
| Consumer Streamlit（consumer/app.py） | `:8503` | `logs/consumer.log` |
| Caddy 反向代理（需安装） | `:8080` | `logs/caddy.log` |

**访问地址**：

| URL | 页面 |
|-----|------|
| `http://localhost:8080/` | 商户 Dashboard（趋势/运营/试戴） |
| `http://localhost:8080/user/` | 消费者试戴 |
| `http://localhost:8080/api/health` | API 健康检查 |
| `http://localhost:8501/` | 商户 Dashboard（无 Caddy 直连） |
| `http://localhost:8000/docs` | FastAPI Swagger UI |

**单独启动 Chat UI**（人机协作流水线）：

```bash
uv run streamlit run web/chat_app.py
```

**启动 XHS-MCP Go server**（可选，提供真实小红书数据）：

```bash
cd /tmp/xiaohongshu-mcp && go run .
# 首次需要扫码登录
cd /tmp/xiaohongshu-mcp && go run cmd/login/main.go
```

**启动 Chrome CDP**（可选，提供 Douyin/Instagram 数据）：

```bash
# macOS
open -a "Google Chrome" --args --remote-debugging-port=9222
# 然后在该 Chrome 中手动登录 douyin.com 和 instagram.com
```

**A11 — Instagram cookie 接入（可选，P2）**

Instagram fetcher 使用 `instaloader` 的 session 文件（Cookie-based，不依赖 CDP）：

```bash
# 1. 安装 instaloader（已包含在 [dev] extras）
pip install instaloader

# 2. 登录并保存 session（交互式，需要 Instagram 账号）
python - <<'EOF'
import instaloader
L = instaloader.Instaloader()
L.interactive_login("your_ig_username")          # 输入密码 + 双因子验证码
L.save_session_to_file()                         # 默认保存到 ~/.ig_session_<username>
import shutil, pathlib
shutil.copy(
    next(pathlib.Path.home().glob(".ig_session_*")),
    pathlib.Path.home() / ".ig_session.json",
)
print("Session saved → ~/.ig_session.json")
EOF

# 3. 验证：运行 smoke test（跳过若文件不存在）
python -c "
from nails_agent.tools.fetchers.instagram_fetcher import InstagramFetcher
f = InstagramFetcher()
print('available:', f.is_available())
"
```

**注意事项：**
- `~/.ig_session.json` 只需生成一次，Cookie 有效期约 90 天。
- 过期后重新执行上面的第 2 步。
- CI/CD 环境中 Instagram 数据源会自动 fallback 到 mock，不影响测试。
- `SignalCollector` 在所有真实数据源均不可用时才使用 mock fallback。

---

## 4. 环境变量速查

| 变量 | 默认值 | 必需场景 |
|------|--------|---------|
| `MODELSCOPE_API_KEY` | — | LLM 主后端（Qwen3） |
| `OPENROUTER_API_KEY` | — | LLM 备用后端（Claude） |
| `NAILS_MODELSCOPE_MODEL` | `Qwen/Qwen3-235B-A22B-Instruct-2507` | 更换 ModelScope 模型 |
| `NAILS_OPENROUTER_MODEL` | `anthropic/claude-sonnet-4-5` | 更换 OpenRouter 模型 |
| `COMFYUI_API_KEY` | — | 真实 AI 试戴图像生成 |
| `CHROME_CDP_URL` | `http://localhost:9222` | Douyin / Instagram CDP 数据源 |
| `MODELSCOPE_BASE_URL` | `https://api-inference.modelscope.cn/v1` | 代理 / 私有部署时替换 |
| `NAILS_DATA_DIR` | `web/data` | 款式库和种子数据路径 |
| `NAILS_OUTPUT_DIR` | `web/output` | Agents 写盘路径（生产环境改此项） |
| `NAILS_API_BASE` | `http://localhost:8000` | Consumer Streamlit → FastAPI 地址 |
| `TIKHUB_API_KEY` | — | 付费 TikHub 数据源（可选） |
| `TELEGRAM_BOT_TOKEN` | — | Telegram 机器人（可选） |

**优先级说明**：  
`agent_config.py` 按 `MODELSCOPE_API_KEY → OPENROUTER_API_KEY` 顺序检测，两者都没有则使用规则模式（全链路无 LLM 调用，适合 CI）。

---

## 5. 平台扩展指南

> 完整 9 角色 MAS 设计见 [agents.md](agents.md)；下方各节对应最常见的扩展场景。

### 5a. 新增 Agent Tool

1. **在 `nail_tools.py` 添加函数**，用 `@function_tool` 装饰：

```python
# nails_agent/agents/nail_tools.py
from agents import function_tool

@function_tool
def search_pinterest(tags: list[str], limit: int = 20) -> str:
    """Search Pinterest for nail inspiration images."""
    # 返回值必须是字符串（通常是 JSON）
    ...
    return json.dumps({"count": N, "signals": [...]})
```

   - 如果参数包含 `list[dict]`（LLM 动态组装），加 `@function_tool(strict_mode=False)`
   - **docstring 即工具描述**，Qwen3 看到的就是这段文字，写清楚参数含义

2. **在 `nail_agents.py` 注册到目标 Agent**：

```python
from nails_agent.agents.nail_tools import search_pinterest

@lru_cache(maxsize=1)
def get_trend_scout_agent() -> Agent:
    return Agent(
        ...
        tools=[..., search_pinterest],   # ← 添加
    )
```

3. **清除 lru_cache**（如果在同一进程内测试改动）：
```python
get_trend_scout_agent.cache_clear()
```

4. **独立测试 tool 函数**：tool 是普通 Python 函数，直接调用即可，不需要启动 Agent。

---

### 5b. 新增数据源

1. **在 `nails_agent/tools/fetchers/` 新建 fetcher 类**，必须返回 `List[TrendSignal]`：

```python
# nails_agent/tools/fetchers/pinterest_fetcher.py
from nails_agent.models.schemas import TrendSignal

class PinterestFetcher:
    def is_available(self) -> bool:
        """不能有副作用，不能登录/打开浏览器。"""
        return bool(os.environ.get("PINTEREST_SESSION"))

    def search(self, tags: list[str], limit: int = 20) -> list[TrendSignal]:
        ...
```

2. **在 `signal_collector.py` 注册**：

```python
# source_status() 中添加
status["pinterest"] = self._get_pinterest().is_available()

# collect() 中添加
if use_pinterest and pinterest.is_available():
    futures.append(executor.submit(pinterest.search, tags, limit_per_kw))
```

3. **在 `nail_tools.py` 包装成 `@function_tool`**（可选，供 TrendScoutAgent 直接调用）

---

### 5c. 修改 4 步流水线

**新增并行子步骤**（在 `nails_agent/agents/orchestrator.py` Step 2 区域）：

```python
with ThreadPoolExecutor(max_workers=3) as ex:  # 改为 3
    f_value  = ex.submit(value_evaluator.evaluate, analysis, library)
    f_assets = ex.submit(asset_generator.generate, analysis)
    f_new    = ex.submit(my_new_worker.process, analysis)  # ← 新增

value_result = f_value.result()
asset_result = f_assets.result()
new_result   = f_new.result()
```

**新增串行步骤**（在任意两步之间）：

```python
# 在 Step 3 之前插入
if progress_cb: progress_cb("⚙️ 运行新步骤…")
new_result = my_step.run(value_result, asset_result)
self._persist_new_step(state.pipeline_id, new_result)
state.new_step_result = new_result   # 需在 PipelineState schema 添加此字段
```

复制 `_persist_*` 模式（SQLite MemoryEntry + JSON 写盘）保证一致性：

```python
def _persist_new_step(self, pid: str, result) -> None:
    entries = [MemoryEntry(pipeline_id=pid, produced_by="my_worker", kind="my_kind", ...)]
    self.memory.save_many(entries)
    path = Path(self.output_dir) / "my_step.json"
    path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
```

---

### 5d. 新增 Chat UI Checkpoint

**场景**：在 Step 4 报告生成后增加一个"确认发布"的 Checkpoint。

1. **`chat_events.py`**：在 `Phase` Literal 类型中添加新相名称：

```python
Phase = Literal[
    ..., "strategy_review", "reporting", "publish_review", "done", ...
]
```

2. **`chat_runner.py`**：实现新 phase 方法 + 在前序 phase 末尾 emit checkpoint：

```python
def _phase_reporting(self, store) -> List[ChatEvent]:
    events = [...]
    # 在最后一行发出新 checkpoint（替代原来直接进入 done）
    events.append(make_checkpoint(
        phase="reporting",
        prompt="报告已生成，是否立即发布到各平台？",
        choices=[
            CheckpointChoice(id="publish", label="✅ 发布", style="primary", priority="P0"),
            CheckpointChoice(id="skip", label="⏩ 跳过", style="secondary", priority="P1"),
        ],
    ))
    return events

def _phase_publish_review(self, store) -> List[ChatEvent]:
    # 实际发布逻辑
    ...
```

3. **`_handle_choice()`**：添加新的路由：

```python
if cp == "reporting" and choice == "publish":
    return [echo, *self._phase_publish_review(store)]
if cp == "reporting" and choice == "skip":
    store["phase"] = "done"
    return [echo, make_message("assistant", "已跳过发布。")]
```

**无需修改 `chat_app.py` 或 `chat_render.py`**：渲染器对所有 `CheckpointPayload` 通用处理。

---

### 5f. 实现 Action Executor（K4 闭环）

**场景**：PRD v4 设计了第 9 个 Agent 角色 — Action Executor，负责将审核通过的运营计划自动发布到各平台。

1. **在 `nail_tools.py` 添加发布 tools**：

```python
@function_tool
def publish_to_xhs(style_card_json: str, scheduled_at: str) -> str:
    """发布款式文案到小红书。scheduled_at: ISO 8601 时间字符串。"""
    import json
    from nails_agent.tools.fetchers.xhs_fetcher import XHSFetcher
    card = json.loads(style_card_json)
    fetcher = XHSFetcher()
    job_id = fetcher.create_draft(card["xhs_copy"], card["style_name"])
    return json.dumps({"job_id": job_id, "status": "pending"})
```

2. **在 `nail_agents.py` 新建 ActionExecutorAgent**（或复用 orchestrator 直接调用 tools）：

```python
@lru_cache(maxsize=1)
def get_action_executor_agent() -> Agent:
    return Agent(
        name="ActionExecutorAgent",
        model=make_model(),
        tools=[publish_to_xhs, publish_to_douyin],
        instructions="将 campaign.json 中的运营卡片按排期发布，每次发布后记录结果。",
    )
```

3. **在 `chat_runner.py` 接入**：在 `reporting → done` 路由中调用：

```python
if cp == "reporting" and choice == "publish":
    events.extend(self._phase_action_execute(store))
```

4. **写 SQLite**：新建 `publish_jobs` 表，追踪发布状态（参考 `tryon_jobs` 表结构）。

---

### 5e. 调整评分权重

详细数学公式见 [`docs/scoring_formulas.md`](scoring_formulas.md)。

代码位置（`nails_agent/agents/workers/value_evaluator.py`）：

```python
# 互动量权重（composite_score 计算）
_LIKES_W    = 1.0
_COLLECTS_W = 1.5
_SHARES_W   = 2.0
_COMMENTS_W = 0.5

# 新鲜度衰减半衰期（小时）
_FRESHNESS_HALF_LIFE_H = 168   # 7 天；改为 72 = 3 天半衰期

# 优先级综合权重
_HEAT_W  = 0.45
_FRESH_W = 0.30
_GAP_W   = 0.25
```

---

## 6. 运行测试

```bash
pytest tests/ -v --asyncio-mode=auto
```

| 测试类型 | 需要 API key | 覆盖范围 |
|---------|------------|---------|
| Worker 单元测试 | 否 | trend_analyst, value_evaluator, summarizer |
| Tool 单元测试 | 否 | signal_collector（mock 数据） |
| Agent 集成测试 | 是 | TrendScoutAgent, CampaignAgent（真实 LLM 调用） |
| API 测试 | 否 | FastAPI 端点（httpx AsyncClient） |

---

## 7. 代码风格

```bash
ruff check .     # lint
ruff format .    # format
```

配置（`pyproject.toml`）：

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
```

---

## 8. Apple Silicon 注意事项

`MediaPipe 0.10.14+` 已提供原生 `macosx_11_0_arm64` wheel，**无需 Rosetta**，直接安装即可：

```bash
pip install -e ".[demo,consumer,dev]"
```

如果 `POST /hand/analyze` 返回 `503`，检查 mediapipe 是否可 import：

```bash
python -c "import mediapipe; print(mediapipe.__version__)"
```

> **注意**：`mediapipe` 在 `[consumer]` extra 中，`pip install -e .`（不带 extra）不会安装它。
> 务必使用 `.[demo,consumer,dev]` 完整安装。

---

## 9. Next.js 前端开发

> Streamlit (`web/`, `consumer/`) 为过渡期实现。MVP 后由单一 Next.js 应用替代。

### 9.1 初始化（Track B 周一执行）

```bash
# 在仓库根目录
npx create-next-app@latest frontend --typescript --tailwind --app --src-dir --import-alias "@/*"
cd frontend
npx shadcn@latest init
npm install zustand @tanstack/react-query react-hook-form zod react-dropzone
```

### 9.2 路由结构

```
frontend/app/
├── (merchant)/          # B端 route group（商家运营）
│   ├── layout.tsx
│   ├── page.tsx         # Chat UI 入口
│   ├── pipeline/        # Pipeline 触发 + EventLog 轨迹
│   └── campaign/        # CandidatePackage 展示 + HITL 审查
└── (user)/              # C端 route group（消费者试戴）
    ├── layout.tsx
    ├── page.tsx          # 款式浏览
    ├── upload/           # 手图上传（react-dropzone）
    ├── tryon/            # 试戴轮询（TanStack Query）
    └── recommend/        # 相似款 + 收藏（FeedbackEvent）
```

### 9.3 开发启动

```bash
cd frontend && npm run dev   # 启动 :3000
```

开发阶段 Next.js 直接访问 `http://localhost:3000`，Caddy 不修改（Streamlit 仍在 :8501/:8503）。

### 9.4 API Client

```typescript
// frontend/lib/api/client.ts
const BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000"

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json() as Promise<T>
}
```

类型定义见 [api_reference.md §TypeScript类型](api_reference.md#typescript-类型)。

### 9.5 EventLog 实时轨迹（TanStack Query）

```typescript
// 在 /merchant/pipeline 页面
const { data } = useQuery({
  queryKey: ["events", triggerId],
  queryFn: () => apiFetch<{ events: EventLogEntry[] }>(`/api/v1/events?trigger_id=${triggerId}&limit=50`),
  refetchInterval: 2000,  // 每 2s 轮询
  enabled: !!triggerId,
})
```

### 9.6 试戴轮询（TanStack Query）

```typescript
// 在 /user/tryon 页面
const { data: job } = useQuery({
  queryKey: ["tryon", jobId],
  queryFn: () => apiFetch<TryOnJob>(`/api/v1/tryon/${jobId}`),
  refetchInterval: (q) => q.state.data?.status === "done" ? false : 3000,
  enabled: !!jobId,
})
```

### 9.7 FastAPI CORS 配置

Next.js (:3000) 调用 FastAPI (:8000) 需要开放 CORS，在 `nails_agent/api/main.py` 中：

```python
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 关键参考文件

- [`scripts/dev.sh`](../../scripts/dev.sh) — 本地启动脚本（进程 + 日志位置）
- [`.env.example`](../../.env.example) — 环境变量模板
- [`pyproject.toml`](../../pyproject.toml) — 依赖组（demo / consumer / dev）
- [`nails_agent/agents/nail_tools.py`](../../nails_agent/agents/nail_tools.py) — 扩展 tool 参考
- [`nails_agent/tools/fetchers/signal_collector.py`](../../nails_agent/tools/fetchers/signal_collector.py) — 数据源注册
- [`nails_agent/agents/orchestrator.py`](../../nails_agent/agents/orchestrator.py) — 4 步流水线
- [`docs/acceptance_plan.md`](acceptance_plan.md) — 集成验收 checklist（curl 命令）
- [`docs/scoring_formulas.md`](scoring_formulas.md) — 价值评估评分公式
