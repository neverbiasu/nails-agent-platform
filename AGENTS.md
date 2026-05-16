# NailsAgent Platform — AI Agent 开发规范

适用于所有 AI coding agent：Claude Code、GitHub Copilot、OpenAI Codex、Cursor、Gemini CLI 等。

---

## 必读文件（每次 session 开始前）

| 文件 | 何时读 |
|---|---|
| `DESIGN.md` | 写任何 UI 组件前必须先读，所有颜色/字体/间距 token 在此定义 |
| `docs/design/pages-merchant.md` | 写 B端 Chat 相关页面前 |
| `docs/design/pages-consumer.md` | 写 C端 消费者相关页面前 |
| `docs/develop/api_reference.md` | 写涉及 API 调用的代码前 |
| `docs/develop/architecture.md` | 理解系统整体结构时 |

---

## 项目概览

美甲 AI 平台，分为两条独立链路：

- **B端**：运营商 AI Chat（`/merchant`）— 触发趋势 Pipeline、HITL 审批、查看 EventLog
- **C端**：消费者试戴（`/(user)`）— 内容发现、手型上传、AI 试戴、款式推荐

后端：Python（FastAPI + openai-agents SDK）  
前端（规划中）：Next.js 15 + Tailwind CSS v4 + shadcn/ui  
过渡期前端：Streamlit（`:8501` B端，`:8503` C端）

---

## 前端开发规范

1. **颜色全部引用 DESIGN.md token**，不裸写 hex；Tailwind 通过 `tailwind.config.ts` 映射 token。
2. **B端和 C端 layout 严格分离**：B端走 sidebar + chat area（Desktop 优先），C端走 mobile-first 瀑布流。
3. **字体**：中文用 PingFang SC，英文/数字用 Plus Jakarta Sans，技术内容（EventLog、API 数据）用 JetBrains Mono。
4. **图片容器固定宽高比**：C端款式卡片 3:4，试戴结果 1:1，一律 `object-fit: cover`。
5. **加载态必须有骨架屏**（`blushLight` + shimmer 动画），不留空白区域。
6. **组件结构参考** `docs/design/pages-*.md`，里面有精确的 ASCII 布局图和 Tailwind 代码片段。

---

## 后端开发规范

1. 每个 Agent 步骤完成后**立即写 `event_log` 表**，不批量写入。
2. `nails_agent/models/schemas.py` 是前后端共享类型文件，修改后同步更新前端 `lib/api/types.ts`。
3. **不 mock 数据库**，测试使用真实 SQLite（pytest 配置见 `pyproject.toml`）。
4. 新增 API 端点后同步更新 `docs/develop/api_reference.md`。

---

## Git 规范

- commit message 不加 `Co-Authored-By: <AI agent>` 行。
- push 前 pre-push hook 自动执行 `ruff check + ruff format + pytest`，失败则修复后再 commit。
- 不使用 `git push --force`；不跳过 hook（`--no-verify`）。
- 每次只做一个 KANBAN 任务，完成后写测试，再 push。

---

## 启动命令

```bash
# 安装 Python 依赖
pip install -e ".[consumer,demo,dev]"

# 启动全栈（XHS bridge + FastAPI + Streamlit + Caddy）
./scripts/dev.sh

# 端口说明
# :18060  XHS REST bridge（Node.js，供 Python 采集真实小红书数据）
# :8000   FastAPI（核心后端）
# :8501   B端 Chat UI（Streamlit，过渡期）
# :8503   C端 试戴（Streamlit，过渡期）
# :8080   Caddy 聚合反向代理（/→8501，/user/→8503，/api/→8000）

# XHS session 过期时重新登录
uv run python scripts/xhs_login.py --name nails

# 运行测试
pytest

# Lint / Format
ruff check .
ruff format .
```

---

## 平台适配说明

| Agent | 读取方式 |
|---|---|
| **Claude Code** | 自动读取项目根目录的 `AGENTS.md` |
| **GitHub Copilot** | 在 `.github/copilot-instructions.md` 中 `@` 引用本文件，或直接复制内容 |
| **OpenAI Codex** | 通过 `--context` 参数传入，或在 `codex.md` 中 include |
| **Cursor** | 在 `.cursorrules` 中 `@file:AGENTS.md` 引用 |
| **Gemini CLI** | 在 `GEMINI.md` 中 include 本文件内容 |
