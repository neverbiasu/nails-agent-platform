# 代码文件索引

## nails_agent/ — 核心 Python 包

### agents/ — Agent 实现层

| 文件 | 说明 |
|------|------|
| [trigger_gateway.py](../../nails_agent/agents/trigger_gateway.py) | TriggerGateway：标准化 pipeline 入口，写 TriggerEvent 到 EventLog |
| [orchestrator.py](../../nails_agent/agents/orchestrator.py) | NailsOrchestrator：B 端完整 pipeline 调度（TrendAnalyst→Summarizer→Reviewer） |
| [trend_agent.py](../../nails_agent/agents/trend_agent.py) | TrendScoutAgent：openai-agents SDK，LLM 趋势分析（Qwen3 主 / Claude 备） |
| [campaign_agent.py](../../nails_agent/agents/campaign_agent.py) | CampaignAgent：openai-agents SDK，LLM 策略生成 |
| [summarizer.py](../../nails_agent/agents/summarizer.py) | Summarizer：聚合 TrendEvent + StrategyEvent → CandidatePackage |
| [reviewer_guardrail.py](../../nails_agent/agents/reviewer_guardrail.py) | ReviewerGuardrail：规则层 + LLM 层双重审查 → ReviewDecision |
| [action_executor.py](../../nails_agent/agents/action_executor.py) | ActionExecutor：HITL 确认后执行 XHS 草稿发布 / OpenClaw webhook |
| [hermes_chat.py](../../nails_agent/agents/hermes_chat.py) | HermesChat：B 端 11 态对话状态机（ChatUI 后端） |
| [chat_runner.py](../../nails_agent/agents/chat_runner.py) | ChatRunner：异步驱动 HermesChat 状态转移 |
| [chat_events.py](../../nails_agent/agents/chat_events.py) | 对话事件类型定义（ChatEvent、UserMessage 等） |
| [nail_agents.py](../../nails_agent/agents/nail_agents.py) | 遗留 agent 定义（旧版，保留兼容） |
| [nail_tools.py](../../nails_agent/agents/nail_tools.py) | 遗留 tool 函数（旧版，保留兼容） |
| [base_tool_agent.py](../../nails_agent/agents/base_tool_agent.py) | BaseToolAgent：带 tool 调用的 Agent 基类 |
| [agent_config.py](../../nails_agent/agents/agent_config.py) | LLM provider 配置：ModelScope / OpenRouter / Anthropic |

### agents/workers/ — 规则制 Worker（无 LLM）

| 文件 | 说明 |
|------|------|
| [trend_analyst.py](../../nails_agent/agents/workers/trend_analyst.py) | TrendAnalyst：信号采集 + 规则制趋势评分，输出 TrendAnalysisResult |
| [value_evaluator.py](../../nails_agent/agents/workers/value_evaluator.py) | ValueEvaluator：三维评分（热度×新鲜度×缺口），输出 ValueEvaluationResult |
| [campaign_strategist.py](../../nails_agent/agents/workers/campaign_strategist.py) | CampaignStrategist：规则制策略生成，输出 CampaignStrategyResult |
| [asset_generator.py](../../nails_agent/agents/workers/asset_generator.py) | AssetGenerator：MVP stub，生成 AssetGenerationResult 占位 |
| [summarizer.py](../../nails_agent/agents/workers/summarizer.py) | workers/Summarizer：规则制汇总（与 agents/summarizer.py 二选一调用） |

### api/ — FastAPI 层

| 文件 | 说明 |
|------|------|
| [main.py](../../nails_agent/api/main.py) | FastAPI app 入口：CORS、lifespan、全部路由（B端+C端+tryon） |

### memory/ — Memory Fabric

| 文件 | 说明 |
|------|------|
| [store.py](../../nails_agent/memory/store.py) | MemoryStore：SQLite+FTS5，管理所有表（event_log、candidate_packages、sessions 等） |
| [event_log.py](../../nails_agent/memory/event_log.py) | EventLog：pipeline 事件链写/读接口，save/get CandidatePackage，update review 状态 |

### models/ — Pydantic 模型

| 文件 | 说明 |
|------|------|
| [schemas.py](../../nails_agent/models/schemas.py) | 全量 Pydantic 模型：TriggerEvent、TrendSignal、CandidatePackage、ReviewDecision、ActionEvent 等 |

### services/ — 业务服务层（C 端）

| 文件 | 说明 |
|------|------|
| [hand_analyzer.py](../../nails_agent/services/hand_analyzer.py) | HandAnalyzer：MediaPipe 手型识别 + 肤色分析 |
| [recommendation.py](../../nails_agent/services/recommendation.py) | RecommendationService：Round1 规则推荐 + Round2 视觉相似度重排 |
| [session_service.py](../../nails_agent/services/session_service.py) | SessionService：C 端会话生命周期管理（创建/获取/更新） |
| [style_library.py](../../nails_agent/services/style_library.py) | StyleLibrary：从 SQLite 加载款式数据，支持 FTS5 关键词检索 |
| [seed_loader.py](../../nails_agent/services/seed_loader.py) | SeedLoader：首次启动向 SQLite 写入款式 + 手型参考数据 |
| [interaction.py](../../nails_agent/services/interaction.py) | InteractionService：用户行为事件（收藏、咨询）写入 event_log |
| [labels.py](../../nails_agent/services/labels.py) | 款式标签映射与归一化工具函数 |

### tools/ — 外部集成工具

| 文件 | 说明 |
|------|------|
| [comfyui_client.py](../../nails_agent/tools/comfyui_client.py) | ComfyUIClient：提交 FLUX.2 Klein 9B 试戴渲染任务，轮询结果 |

### tools/fetchers/ — 数据采集层

| 文件 | 说明 |
|------|------|
| [signal_collector.py](../../nails_agent/tools/fetchers/signal_collector.py) | SignalCollector：多平台聚合入口，fallback 到 mock 数据 |
| [xhs_mcp_fetcher.py](../../nails_agent/tools/fetchers/xhs_mcp_fetcher.py) | XHS MCP Fetcher：通过 xhs-mcp 本地服务（:18060）采集小红书信号 |
| [xhs_cdp_fetcher.py](../../nails_agent/tools/fetchers/xhs_cdp_fetcher.py) | XHS CDP Fetcher：Playwright CDP 备用采集路径 |
| [xhs_skills_fetcher.py](../../nails_agent/tools/fetchers/xhs_skills_fetcher.py) | XHS Skills Fetcher：基于 Claude MCP skills 的 XHS 采集封装 |
| [douyin_cdp.py](../../nails_agent/tools/fetchers/douyin_cdp.py) | DouyinCDPFetcher：抖音 CDP 采集（search() 主体待完成） |
| [instagram_fetcher.py](../../nails_agent/tools/fetchers/instagram_fetcher.py) | InstagramFetcher：instaloader + Playwright 双路径，需 ~/.ig_session.json |
| [tikhub_fetcher.py](../../nails_agent/tools/fetchers/tikhub_fetcher.py) | TikHubFetcher：TikHub API 采集（需 TIKHUB_API_KEY） |

---

## web/ — B 端 Streamlit UI（过渡期）

| 文件 | 说明 |
|------|------|
| [chat_app.py](../../web/chat_app.py) | 11 态 Chat UI 主入口（Streamlit :8501），对接 HermesChat |
| [app.py](../../web/app.py) | Pipeline 管控 tab 页（趋势/策略/数据链路可视化） |
| [chat_state.py](../../web/chat_state.py) | Streamlit session state 管理（Chat 状态持久化） |
| [chat_render.py](../../web/chat_render.py) | Chat UI 消息渲染组件 |
| [comfyui_tryon.py](../../web/comfyui_tryon.py) | B 端 ComfyUI 试戴调用封装 |
| [data_loader.py](../../web/data_loader.py) | 加载 web/data/ 下 JSON 文件到 Streamlit |
| [tabs/tab_overview.py](../../web/tabs/tab_overview.py) | 总览 tab：平台状态、最新 pipeline 摘要 |
| [tabs/tab_trends.py](../../web/tabs/tab_trends.py) | 趋势 tab：TrendSignal 列表、热力图 |
| [tabs/tab_operations.py](../../web/tabs/tab_operations.py) | 运营 tab：CandidatePackage 展示、HITL 审查按钮 |
| [tabs/tab_datachain.py](../../web/tabs/tab_datachain.py) | 数据链路 tab：EventLog 时间轴可视化 |
| [tabs/tab_tryon.py](../../web/tabs/tab_tryon.py) | 试戴 tab：手图上传 + ComfyUI 结果展示 |

### web/data/ — Pipeline 静态数据（开发期 mock + 输出缓存）

| 文件 | 说明 |
|------|------|
| [trend_signals.json](../../web/data/trend_signals.json) | ~40 条 mock 趋势信号（SignalCollector fallback 数据源） |
| [trend_signals_with_score.json](../../web/data/trend_signals_with_score.json) | 带评分的趋势信号（ValueEvaluator 输出缓存） |
| [style_cards.json](../../web/data/style_cards.json) | 款式运营卡片列表（CampaignStrategist 输出缓存） |
| [style_library.json](../../web/data/style_library.json) | 款式库主数据（种子数据，已写入 SQLite） |
| [event_log.json](../../web/data/event_log.json) | EventLog 导出快照（调试用） |
| [module_outputs.json](../../web/data/module_outputs.json) | 各 Agent 模块输出快照 |
| [metric_snapshots.json](../../web/data/metric_snapshots.json) | 指标快照（平台运营数据） |
| [action_executions.json](../../web/data/action_executions.json) | ActionExecutor 执行记录快照 |
| [user_profile.json](../../web/data/user_profile.json) | 示例用户画像（C 端测试用） |

---

## consumer/ — C 端 Streamlit UI（过渡期）

| 文件 | 说明 |
|------|------|
| [app.py](../../consumer/app.py) | C 端 AI 试戴主入口（Streamlit :8503） |
| [app_hand_check.py](../../consumer/app_hand_check.py) | 手型检测独立调试页面 |

### consumer/data/ — C 端参考数据

| 文件 | 说明 |
|------|------|
| [nail_styles_v1.json](../../consumer/data/nail_styles_v1.json) | 款式库 v1（早期版本） |
| [nail_visual_features.json](../../consumer/data/nail_visual_features.json) | 款式视觉特征向量（Round2 相似度计算输入） |
| [hand_shape_definitions.json](../../consumer/data/hand_shape_definitions.json) | 手型分类定义（方形/椭圆/修长等） |
| [skin_tone_definitions.json](../../consumer/data/skin_tone_definitions.json) | 肤色分类定义（Fitzpatrick 量表映射） |
| [undertone_definitions.json](../../consumer/data/undertone_definitions.json) | 肤色冷暖调定义 |
| [color_feature_rules.json](../../consumer/data/color_feature_rules.json) | 色彩推荐规则（肤色×色调→适配色系） |
| [reference_hand_profiles.json](../../consumer/data/reference_hand_profiles.json) | 手型参考画像（Round1 匹配基准） |

---

## video/ — Remotion 动效

| 文件 | 说明 |
|------|------|
| [src/NailsTryOnDemo.tsx](../../video/src/NailsTryOnDemo.tsx) | 试戴 Demo 主合成（8 个场景串联） |
| [src/scenes/](../../video/src/scenes/) | 8 个分场景：Intro/Upload/Analysis/Round1/Round2/TryOn/Interaction/Outro |
| [src/theme.ts](../../video/src/theme.ts) | 动效主题色、字体、动画时长常量 |
| [src/constants.ts](../../video/src/constants.ts) | 视频尺寸、帧率、总时长配置 |

---

## workflows/ — ComfyUI 工作流

| 文件 | 说明 |
|------|------|
| [nail_tryon_klein_9b.json](../../workflows/nail_tryon_klein_9b.json) | FLUX.2 Klein 9B 试戴渲染主工作流 |
| [product_showcase_firered_image_edit1_1.json](../../workflows/product_showcase_firered_image_edit1_1.json) | FireRed 商品展示图生成工作流 |
| [social_media_firered_image_edit1_1.json](../../workflows/social_media_firered_image_edit1_1.json) | FireRed 社媒配图生成工作流 |

---

## tests/ — 测试套件

| 文件 | 说明 |
|------|------|
| [test_api.py](../../tests/test_api.py) | FastAPI 端点集成测试（TestClient）：trigger、events、pipeline、tryon |
| [test_event_log.py](../../tests/test_event_log.py) | EventLog 单元测试：写入、读取、CandidatePackage 持久化、review 状态更新 |
| [test_reviewer_guardrail.py](../../tests/test_reviewer_guardrail.py) | ReviewerGuardrail 单元测试：规则层 pass/revise/reject、LLM 层 mock |
| [test_signal_collector.py](../../tests/test_signal_collector.py) | SignalCollector 测试：mock 数据回退、返回 TrendSignal 列表 |
| [test_trend_analyst.py](../../tests/test_trend_analyst.py) | TrendAnalyst 单元测试：评分计算、top_10 输出 |
| [test_value_evaluator.py](../../tests/test_value_evaluator.py) | ValueEvaluator 单元测试：三维评分公式验证 |

---

## scripts/ — 运维脚本

| 文件 | 说明 |
|------|------|
| [dev.sh](../../scripts/dev.sh) | 一键启动：XHS bridge（:18060）+ FastAPI（:8000）+ ChatUI（:8501）+ C 端（:8503）+ Caddy（:8080） |
| [xhs_rest_bridge.mjs](../../scripts/xhs_rest_bridge.mjs) | Node.js REST bridge：把 xhs-mcp 内部 API 封装为 REST（/api/v1/feeds/search 等），供 Python 调用 |
| [xhs_login.py](../../scripts/xhs_login.py) | XHS MCP 账号登录：触发 QR 码扫码，持久化 cookie |
| [hooks/pre-push](../../scripts/hooks/pre-push) | git pre-push 门禁：ruff check + ruff format + pytest 全部通过才允许 push |

---

## 配置文件

| 文件 | 说明 |
|------|------|
| [pyproject.toml](../../pyproject.toml) | 包配置：依赖、extras（consumer/demo/dev）、ruff 规则、pytest 设置 |
| [Caddyfile](../../Caddyfile) | Caddy 反向代理：/ → :8501，/user/ → :8503，/api/ → :8000 |
| [config/signals.yaml](../../config/signals.yaml) | 信号采集配置：平台列表、关键词、采集频率 |
| [.env.example](../../.env.example) | 环境变量模板：LLM keys、ComfyUI、XHS、OpenClaw |
| [.github/workflows/ci.yml](../../.github/workflows/ci.yml) | CI：pytest + ruff，push/PR 触发 |
| [.github/workflows/ruff.yml](../../.github/workflows/ruff.yml) | Ruff lint 专项 CI |
