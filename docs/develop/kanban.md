# KANBAN — Nails Agent Platform

> 更新日期：2026-05-17  
> MVP 截止日期：**2026-05-24（周六）**

---

## 图例

| 标记 | 含义 |
|------|------|
| ✅ 已完成 | 任务已合并至主分支，验收通过 |
| 🔲 待开始 | 尚未动工 |
| 🚧 进行中 | 已开工，未合并 |
| ⏸ 阻塞 | 等待外部依赖或决策 |

---

## Track A — 后端 / 数据 / 架构

| ID | 任务 | 负责人 | 优先级 | 依赖 | 状态 | 完成标志 |
|----|------|--------|--------|------|------|----------|
| A0 | docs/develop/ 初始化：ARCHITECTURE、AGENTS、API_REFERENCE、DEVELOPER_GUIDE | — | P0 | — | ✅ 已完成 | 4 个文档文件存在且内容完整 |
| A1 | Memory 层：event_log.py、schemas.py（8 个 Pydantic 模型）、store.py（2 张新表） | — | P0 | A0 | ✅ 已完成 | `TriggerEvent`、`TrendEvent` 等模型可 import；DB 迁移成功 |
| A2 | TriggerGateway + API：POST /api/v1/trigger、GET /api/v1/events | — | P0 | A1 | ✅ 已完成 | curl 测试两个端点均返回 200 |
| A3 | Orchestrator 扩展：run_pipeline(TriggerEvent)，每步写 EventLog | — | P0 | A2 | ✅ 已完成 | 全链路 EventLog 条目写入 DB |
| A4 | Summarizer Agent（输出 CandidatePackage） | — | P0 | A3 | ✅ 已完成 | `CandidatePackage` schema 存在；单元测试通过 |
| A5 | ReviewerGuardrail Agent（规则 + LLM，ReviewDecision） | — | P0 | A4 | ✅ 已完成 | 规则拒绝 + LLM 审核两路均可触发 |
| A6 | ActionExecutor（XHS 草稿 + OpenClaw stub） | — | P0 | A5 | ✅ 已完成 | XHS 草稿 API 调用成功；OpenClaw stub 返回 200 |
| A7 | HITL 端点：POST /api/v1/review/approve | — | P0 | A6 | ✅ 已完成 | 审批后 ReviewDecision 状态更新至 DB |
| A8 | TryOn 端点：POST /api/v1/tryon/submit + GET /api/v1/tryon/{id} | — | P0 | A6 | ✅ 已完成 | 提交返回 job_id；轮询返回 status + result_url |
| A9 | XHS 重新登录：xhs_login.py smoke test + 真实数据验证 | — | P1 | A6 | ✅ 已完成 | `tests/test_xhs_smoke.py` 通过（live 测试在桥接服务运行时自动启用；session 过期时提示重新登录） |
| A10 | Douyin CDP search() 完整实现（3h 预算） | — | P1 | A3 | ✅ 已完成 | `search()` 实现完整（XHR 拦截 + scroll-and-drain）；`tests/test_douyin_cdp.py` 覆盖解析层和 fallback |
| A11 | Instagram cookie 接入 | — | P2 | A3 | ✅ 已完成 | `developer_guide.md` 补充 instaloader session 生成步骤；`instagram_fetcher.py` 代码已有 |
| A12 | ValueEvaluator 集成进编排链 | — | P1 | A4 | ✅ 已完成 | Orchestrator Step 2 并行调用 ValueEvaluator；`review_score` 含三维评分贡献；`tests/test_summarizer.py` 验证 |

---

## Track B — Next.js 前端

| ID | 任务 | 负责人 | 优先级 | 依赖 | 状态 | 完成标志 |
|----|------|--------|--------|------|------|----------|
| B0 | Next.js scaffold + shadcn/ui + 路由组 (merchant) + (user) | — | P0 | AB0 | 🔲 待开始 | `npm run dev` 启动无报错；两个路由组可访问 |
| B1 | lib/api/client.ts + lib/api/types.ts（API 客户端 + 类型定义） | — | P0 | B0, AB0 | 🔲 待开始 | 所有后端 Schema 有对应 TS 类型；client 编译通过 |
| B2 | Zustand chat store（11 状态机） | — | P0 | B1 | 🔲 待开始 | 状态转移覆盖 idle→triggered→reviewing→done |
| B3 | /merchant — ChatUI + Trigger 提交 + EventLog 时间线 | — | P0 | B2 | 🔲 待开始 | 提交 trigger 后 UI 展示完整 EventLog 链 |
| B4 | /merchant/campaign — CandidatePackage 展示 + Reviewer UI（HITL confirm 按钮） | — | P0 | B3 | 🔲 待开始 | HITL 确认按钮调用 /api/v1/review/approve 成功 |
| B5 | /(user)/upload — react-dropzone 手部图片上传 | — | P0 | B1 | 🔲 待开始 | 拖拽上传图片；返回 upload_id |
| B6 | /(user)/tryon — TryOn 提交 + TanStack Query 轮询 + 结果展示 | — | P0 | B5 | 🔲 待开始 | 轮询至 status:done 后显示 result_url 图片 |
| B7 | /(user)/recommend — 相似风格 + 收藏（FeedbackEvent） | — | P1 | B6 | 🔲 待开始 | 收藏操作写入 FeedbackEvent；推荐列表非空 |
| B8 | 全局布局 + 导航栏 | — | P1 | B0 | 🔲 待开始 | merchant / user 两侧导航可正常跳转 |
| B9 | Streamlit 共存配置（端口隔离、反向代理） | — | P2 | B0 | 🔲 待开始 | Next.js :3000 与 Streamlit :8501 同时运行无冲突 |

---

## 共同任务

| ID | 任务 | 计划日期 | 状态 | 完成标志 |
|----|------|----------|------|----------|
| AB0 | API 合约冻结（后端 + 前端对齐所有 Schema） | 2026-05-19（周一） | 🔲 待开始 | OpenAPI spec 导出；前后端无 breaking change |
| AB1 | E2E smoke test（B 端 + C 端全流程跑通） | 2026-05-22（周四） | 🔲 待开始 | B 端流程 + C 端流程各跑通 1 次，无人工干预 |
| AB2 | MVP Demo | 2026-05-24（周六） | 🔲 待开始 | 所有验收标准通过（见下节） |

---

## MVP 验收标准

### B 端（商家运营）流程

1. `POST /api/v1/trigger` → 返回 `trigger_id`
2. EventLog 展示完整链：`TriggerEvent → TrendEvent → StrategyEvent → ReviewEvent`
3. Next.js `/merchant` 页面展示 `CandidatePackage` + `ReviewDecision`（含 HITL 确认按钮）
4. 至少 1 个平台返回真实 `TrendSignal`（非 mock 数据）
5. `ActionExecutor` XHS 草稿已发送，**或** OpenClaw stub 被调用

### C 端（消费者试戴）流程

1. `POST /api/v1/tryon/submit` → 返回 `job_id`
2. `GET /api/v1/tryon/{job_id}` → `status: done` + `result_url`（ComfyUI 渲染结果）
3. Next.js `/(user)` 展示试戴结果图片
4. 收藏操作 → `FeedbackEvent` 写入 `event_log`

---

## 风险清单

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| XHS/Douyin 登录态过期或账号风控 | A9/A10 阻塞，B 端无真实数据 | 提前准备备用账号；A9 设 smoke test 尽早发现 |
| Instagram cookie 需手动获取且频繁失效 | A11 工期不可控 | A11 列为 P2，MVP 可不包含 IG 数据 |
| ComfyUI 渲染服务不稳定 / 超时 | A8 result_url 无法返回 | 准备 mock result_url 作为 fallback，保证 C 端 UI 可演示 |
| AB0 合约冻结晚于 5-19 | B1 类型不同步，前后端 PR 冲突 | 提前在 PR 草稿中对齐关键 Schema，AB0 前不 merge Breaking 变更 |
| B 端前端工期（B0–B4）压缩至 5 天内 | Demo 时前端不完整 | B8（导航）降为 P1；优先完成 B0→B4 主链路 |
| ValueEvaluator（A12）接入可能影响 Orchestrator 稳定性 | 影响 A3/A5 已有功能 | A12 在独立分支开发，合并前跑回归测试 |
