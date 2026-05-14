# 产品需求文档（PRD v4）

> 美甲 AI 运营平台  
> 设计来源：[Notion PRD v4](https://www.notion.so/faych/34e5f3c4a139801e806cd49a2af60591)  
> 最后更新：2026-05

---

## 1. 产品背景与痛点

美甲行业运营面临两类核心痛点：

**B 端（品牌/门店运营方）**
- 社媒趋势更新极快（小红书/抖音/Instagram），人工追踪效率低
- 文案需针对三平台调性分别撰写，重复人力消耗大
- 热点款式从发现到上架平均滞后 5–7 天，错失窗口期

**C 端（消费者）**
- 线下美甲选款依赖店员主观推荐，缺乏个性化依据
- AR 试戴图贴图感强，与真实效果落差大，决策转化低

---

## 2. 产品定位

| 产品模块 | 服务对象 | 核心价值主张 |
|---------|---------|------------|
| **智能运营**（B 端） | 美甲品牌/门店运营人员 | 「今天的社媒热点，今天的运营计划」—— 从信号采集到三平台文案排期，全流程 < 10 分钟 |
| **AI 试戴**（C 端） | 美甲消费者 | 「看到即所得」—— 上传手部照片，FLUX.2 扩散模型生成真实感试戴效果 |

两个模块共享款式库和行为数据，构成 **K1 双链路 Memory 飞轮**。

---

## 3. 五大创新点（K1–K5）

| # | 创新名称 | 产品价值 | 技术支撑 |
|---|---------|---------|---------|
| **K1** | 双链路共享 Memory 飞轮 | B 端运营决策 ↔ C 端推荐排序双向强化，随使用时长持续提升准确率 | 共享 SQLite MemoryStore；behavior_events 反哺 ValueEvaluator 权重 |
| **K2** | 自改进运营 Agent | Agent 记住历史运营效果，下次决策更精准，无需人工调参 | `distill()` Strategy Loop；`MemoryEntry(kind=insight)` 跨 run 积累 |
| **K3** | 扩散试戴超越 AR | 生成质量接近真实照片，消费决策转化率显著提升 | ComfyUI FLUX.2 Klein 9B；`nail_tryon_klein_9b.json` 工作流 |
| **K4** | 端到端 MAS 闭环 | 从采集到发布全自动，运营人员聚焦审核而非执行 | 九角色 MAS；Action Executor 对接 xhs-mcp（设计中） |
| **K5** | 可配置审查闸门 | 任意步骤可插入人工确认，兼顾自动化与质量管控 | Reviewer Guardrail；Chat UI 11 相状态机 + `make_checkpoint()` |

---

## 4. 用户旅程

### B 端运营旅程

```
运营人员在 Chat UI 输入意图
    │ "帮我分析今天的美甲趋势"
    ▼
[自动] Step 1：TrendScoutAgent 采集 XHS/Douyin/Instagram 信号
    │ 展示 Top 10 趋势热帖
    ▼
[Checkpoint K5] 运营人员确认趋势方向
    ▼
[自动] Step 2：价值评估（热度 × 新鲜度 × 款式缺口）+ 素材草稿生成
    │ 展示优先级排序 + 款式卡草稿
    ▼
[Checkpoint K5] 运营人员确认素材
    ▼
[自动] Step 3：CampaignAgent 生成三平台文案 + 定价排期
    │ 小红书正文 + 抖音标题 + Instagram caption，全合规检查
    ▼
[Checkpoint K5] 运营人员确认发布
    ▼
[自动/设计中] Step 4：报告生成 + Action Executor 发布
    │ Markdown 报告 + 平台发布任务
    ▼
[K2] memory.distill() 写长期洞察，下次决策更好
```

### C 端试戴旅程

```
消费者上传手部照片
    ▼
[自动] MediaPipe 分析：手型 + 肤色 + 色调
    ▼
Round 1 推荐：手型 × 肤色规则匹配款式库（B 端运营产出 ↑K1）
    ▼
消费者点击感兴趣款式（行为事件 → ↑K1 反哺 B 端）
    ▼
Round 2 推荐：视觉相似度重排（CLIP 向量 + 行为权重）
    ▼
消费者选中款式 → FLUX.2 Klein 9B 扩散生成试戴图（↑K3）
    ▼
查看真实感试戴效果 → 决策下单
```

---

## 5. 核心功能清单（MVP 范围）

### B 端功能

| 功能 | 状态 | 备注 |
|------|------|------|
| 社媒趋势采集（XHS/Douyin/Instagram） | ✅ | XHS-MCP Go server；Douyin CDP；IG Playwright |
| 趋势聚合分析（Top 10 + 款式 tag 聚合） | ✅ | TrendScoutAgent + trend_analyst worker |
| 三维价值评估（热度/新鲜度/缺口） | ✅ | value_evaluator；详见 scoring_formulas.md |
| 三平台文案生成（XHS/Douyin/Instagram） | ✅ | CampaignAgent；XHS 合规 18 禁用词检查 |
| 定价排期（P0/P1/P2 优先级） | ✅ | campaign_strategist |
| 运营报告生成（Markdown） | ✅ | summarizer |
| Chat UI 人机协作流水线 | ✅ | 11 相状态机；Reviewer Guardrail Checkpoint |
| 跨 run 长期记忆（Strategy Loop） | ✅ | distill() → insight |
| 多平台自动发布（Action Executor） | 🔲 | 设计中；对接 xhs-mcp + AiToEarn MCP |

### C 端功能

| 功能 | 状态 | 备注 |
|------|------|------|
| 手部照片分析（手型/肤色/色调） | ✅ | MediaPipe；需 consumer 依赖 |
| Round 1 推荐（规则匹配） | ✅ | reference_hand_match 策略 |
| 行为事件记录（点击/试戴） | ✅ | behavior_events 表 |
| Round 2 推荐（视觉相似度重排） | ✅ | CLIP 向量 + session_visual_similarity_rerank |
| ComfyUI 试戴生成 | ✅ | FLUX.2 Klein 9B；需 COMFYUI_API_KEY |
| 款式库浏览 | ✅ | /styles API |

---

## 6. 非功能性需求

| 维度 | 目标 | 当前状态 |
|------|------|---------|
| **延迟** | B 端完整 pipeline < 10 分钟 | ~5–8 分钟（LLM 模式） |
| **试戴生成** | < 90 秒 | ~30–60 秒（ComfyUI Cloud） |
| **无 API key 模式** | 全链路可运行（CI/demo） | ✅ rule-based fallback |
| **合规性** | 小红书 0 封号词 | ✅ 18 禁用词检查 |
| **可扩展性** | 新平台接入 < 1 天 | ✅ fetcher 接口标准化 |

---

## 7. 产品边界（Out of Scope）

- 社媒账号管理（关注/评论/私信）
- 美甲款式 3D 建模
- 门店预约系统
- 支付/交易功能
- 多租户 / SaaS 计费

---

## 8. 产品路线图（Roadmap）

| 阶段 | 目标 | 关键 Feature |
|------|------|------------|
| **当前（MVP）** | 单团队内部使用，验证核心链路 | B/C 端双产品联通；Strategy Loop 跑通 |
| **v2（下一步）** | Action Executor 上线，实现真正闭环 | xhs-mcp 自动发布；发布效果数据回流 |
| **v3** | 多租户 + 数据孤岛隔离 | Redis 分层 Memory；Qdrant 向量库迁移 |
| **v4+** | 行业化复制（服装/彩妆/护肤） | 垂直领域 LLM fine-tuning；CLIP 垂直向量 |

---

## 关键参考文件

- [手部上传流程图](hand_upload_flow.drawio) — C 端 6 步流程 drawio
- [开发架构文档](../develop/architecture.md) — 系统组件全图 + 9 角色 MAS
- [Agent 设计文档](../develop/agents.md) — 9 角色完整手册
- [API 参考](../develop/api_reference.md) — REST 端点完整列表
- [开发者指南](../develop/developer_guide.md) — 本地启动 + 扩展指南
- [评分公式](../develop/scoring_formulas.md) — K 维三维价值评估模型
