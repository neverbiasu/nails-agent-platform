# NailsAgent Platform — Claude 开发规范

## 必读文件（每次 session 开始前）

| 文件 | 何时读 |
|---|---|
| `DESIGN.md` | 写任何 UI 组件前必须先读 |
| `docs/design/pages-merchant.md` | 写 B端 Chat 相关页面前 |
| `docs/design/pages-consumer.md` | 写 C端 消费者相关页面前 |
| `.claude/plans/session-adaptive-willow.md` | 了解项目整体架构和 KANBAN |
| `docs/develop/api_reference.md` | 写涉及 API 调用的代码前 |

## 前端开发规范

1. **颜色全部引用 DESIGN.md token**，不裸写 hex。Tailwind 中通过 `tailwind.config.ts` 映射 token。
2. **B端和C端 layout 不混用**：B端走 sidebar + chat area，C端走 mobile-first 瀑布流。
3. **字体**：中文用 PingFang SC，英文/数字用 Plus Jakarta Sans，技术内容用 JetBrains Mono。
4. **图片容器固定宽高比**（C端 3:4，试戴结果 1:1），`object-fit: cover`。
5. **加载态必须有骨架屏**，不留空白，不用 spinner（试戴结果除外）。

## 后端开发规范

1. 每个 Agent 步骤完成后立即写 `event_log` 表，不批量写。
2. `models/schemas.py` 是共享类型文件，改动后通知前端同步 TypeScript 类型。
3. 不 mock 数据库，测试用真实 SQLite（见 `pyproject.toml` pytest 配置）。

## Git 规范

- 不在 commit message 里加 `Co-Authored-By: Claude` 行。
- push 前 pre-push hook 自动跑 ruff + pytest，失败则修复后再 commit。
- 不用 `git push --force`。

## 启动命令

```bash
# 安装依赖
pip install -e ".[consumer,demo,dev]"

# 启动全栈（XHS bridge + FastAPI + ChatUI + C端 + Caddy）
./scripts/dev.sh

# 端口说明
# :18060  XHS REST bridge
# :8000   FastAPI
# :8501   B端 Chat UI（Streamlit，过渡期）
# :8503   C端 试戴（Streamlit，过渡期）
# :8080   Caddy 聚合代理

# XHS 登录（cookie 过期时）
uv run python scripts/xhs_login.py --name nails
```
