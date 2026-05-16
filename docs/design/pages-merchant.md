# B端页面设计 — AI Chat 运营助手

> 设计 DNA：参考 Claude.ai 的 Chat 结构 + Glossier 色盘  
> 适配优先：Desktop（1280px+），兼容 1024px  
> Token 来源：根目录 `DESIGN.md`

---

## 页面地图

```
/merchant                  ← 主 Chat 页（唯一核心页）
/merchant/history/[id]     ← 历史对话详情（从 sidebar 进入）
```

B端只有一个核心交互面：Chat。Pipeline 状态、HITL 审批、EventLog 全部**内嵌在 Chat 流里**，不另开 Dashboard 页。

---

## `/merchant` — 主 Chat 页

### 整体结构

```
┌──────────────────────────────────────────────────────────────────┐
│  [NailsAgent logo]   ←── TopBar 高 52px，bgMerchant + border-b   │
├────────────┬─────────────────────────────────────────────────────┤
│            │                                                      │
│  Sidebar   │              Chat Area                              │
│  200px     │              max-w: 680px，居中                      │
│            │                                                      │
│  折叠态    │   [消息流 ↑，overflow-y scroll]                      │
│  → 52px    │                                                      │
│            │   [InputBar sticky bottom]                           │
└────────────┴─────────────────────────────────────────────────────┘
```

背景色：`bgMerchant` (#F5F5F7)

---

### Sidebar

| 元素 | 规格 |
|---|---|
| 宽度 | 展开 200px，折叠 52px |
| 背景 | `white` |
| 右侧边框 | `1px solid {border}` |
| 顶部 | Logo 图标 32px + "NailsAgent" 文字（折叠时只留图标） |
| 内容区 | 对话历史列表，按日期分组 |
| 底部 | 用户头像 + 名字（折叠时只留头像） |

**对话历史列表 item：**
- 高度 40px，padding `0 12px`
- 文字：body，单行截断，`inkSecond`
- 选中：`blushLight` 背景 + `blushDeep` 左侧 2px 竖线
- hover：`offWhite` 背景

**新建对话按钮：**
- 位于 sidebar 顶部 logo 下方
- 样式：buttonOutline，full-width，`+ 新对话`
- 点击：创建新 trigger，清空 Chat Area

---

### Chat Area

#### 空态（未开始）

```
┌──────────────────────────────────┐
│                                  │
│         🌸（美甲 emoji 或 logo）  │
│                                  │
│    你好，我是 NailsAgent          │
│    告诉我你想推广什么款式？        │
│                                  │
│  ┌──────────────────────────┐   │
│  │  例：推广夏日显白法式美甲  │   │
│  │  例：分析本周小红书趋势   │   │
│  └──────────────────────────┘   │
└──────────────────────────────────┘
```

- 标题：h1，居中，`ink`
- 副标题：body，`inkSecond`
- 快速提示卡片：`panel` 背景，`rounded.lg`，hover → `blushLight` 背景，点击自动填入输入框

#### 消息流

每条消息之间间距 `spacing.lg`（24px）。

**用户消息气泡**

```
                    ┌─────────────────────┐
                    │  推广夏日显白法式美甲  │ ← chatUser 气泡
                    │                     │   右对齐，最大宽 70%
                    └─────────────────────┘
                              头像 32px ──▶
```

- 右对齐
- 背景：`blush`，文字：`ink`，圆角：`rounded.lg`
- 用户头像 32px 圆形，右侧

**Agent 消息气泡**

```
┌─ 2px blushMid 竖线
│  ┌───────────────────────────────────┐
   │  好的，我来分析最近美甲趋势…         │ ← chatAgent 气泡
   │                                   │   左对齐，最大宽 85%
   └───────────────────────────────────┘
```

- 左对齐，最大宽 85%
- 背景：`panel`，文字：`ink`，左侧 2px `blushMid` 竖线
- Agent 头像 32px（品牌粉底色 + 白色图标）

**Pipeline 状态内嵌气泡**

在 Agent 消息下方，折叠展示 Pipeline 进度：

```
   ┌──────────────────────────────────────┐
   │  ▶ Pipeline 运行中                   │ ← 可展开
   │  ● TriggerEvent    ✓ 已完成           │
   │  ● TrendEvent      ⟳ 分析中...       │  
   │  ○ StrategyEvent   — 等待中           │
   │  ○ ReviewEvent     — 等待中           │
   └──────────────────────────────────────┘
```

- 背景：`surfaceWarm`，`rounded.md`，左侧 `statusRunning` 竖线 3px
- event_type：`mono` 字体，`ink`
- 状态图标：✓ `success`，⟳ `statusRunning`，— `inkLight`
- 默认折叠（只显示当前步骤）；点击"展开"显示全部

**HITL 审批内嵌卡片**

当 ReviewerGuardrail 输出后，Chat 流里插入：

```
   ┌──────────────────────────────────────────┐
   │  📋 待审批：夏日法式美甲推广方案           │
   │  ─────────────────────────────────────   │
   │  趋势摘要：猫眼 / 法式 最热（评分 0.87）  │
   │  策略建议：小红书主推 + 限时折扣钩子       │
   │  风险提示：无                             │
   │  ─────────────────────────────────────   │
   │  [✓ 通过执行]  [✎ 要求修改]  [✕ 拒绝]    │
   └──────────────────────────────────────────┘
```

- 卡片：reviewCard，背景 `panel`，`rounded.lg`，`border: 1px solid {border}`
- 标题：h2，`ink`
- 内容：body，`inkSecond`
- 按钮并排：通过（`success`）/ 修改（`warning`）/ 拒绝（`error`）
- 点击任意按钮 → 二次确认 dialog → 提交 `POST /api/v1/review/approve`

**执行结果气泡**

```
   ┌──────────────────────────────────────┐
   │  ✓ 已发布至小红书草稿                 │
   │  草稿链接：xhs.com/draft/xxx          │
   └──────────────────────────────────────┘
```

- 背景：`panel`，左侧 `success` 竖线 3px

---

#### InputBar（底部固定）

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  ┌────────────────────────────────────────────┐  [发送]  │
│  │ 告诉我你想推广什么…                          │         │
│  └────────────────────────────────────────────┘         │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

- 背景：`white`，`border-top: 1px solid {border}`
- padding：`spacing.md`
- 输入框：`input` 组件，高度自适应（min 44px，max 200px），placeholder `inkLight`
- 发送按钮：`button`（blush 圆角），Enter 发送，Shift+Enter 换行
- 输入框左侧可选：附件/图片上传 icon（未来扩展）

---

### 状态变化

| 状态 | Chat Area 表现 |
|---|---|
| 空态 | 居中引导卡片 |
| 等待 Agent | 最后一条气泡下方显示 typing indicator（3个 blush 圆点闪烁） |
| Pipeline 运行 | 状态内嵌气泡实时更新（轮询 GET /api/v1/events） |
| 待 HITL 审批 | HITL 卡片插入 Chat 流，输入框禁用（灰色 + tooltip "请先完成审批"） |
| 执行完成 | 结果气泡，输入框恢复 |
| 错误 | error 色竖线 + 错误描述 + "重试"按钮 |

---

## `/merchant/history/[id]` — 历史对话

与主 Chat 页相同的布局，区别：
- 所有消息只读（无 InputBar，或 InputBar 改为"继续此对话"按钮）
- HITL 卡片已处理的显示为只读状态（通过/拒绝的结果 badge）
- 顶部 TopBar 加"← 返回"按钮

---

## 交互规范

- **轮询间隔**：Pipeline 运行时，每 2s 轮询 `GET /api/v1/events?trigger_id=xxx&limit=50`
- **滚动**：新消息出现自动滚到底部（如果用户没有向上翻看历史）
- **加载态**：首次加载历史消息时，气泡位置显示骨架屏（blushLight + shimmer）
- **错误态**：网络失败时，消息底部显示"发送失败 · 重试"（error 色文字）

---

## Tailwind 速查（关键样式）

```tsx
// 页面根容器
<div className="min-h-screen bg-[#F5F5F7] flex">

// Sidebar
<aside className="w-[200px] bg-white border-r border-[#EDE8E8] flex flex-col shrink-0">

// Chat Area
<main className="flex-1 flex flex-col items-center">
  <div className="w-full max-w-[680px] flex flex-col gap-6 px-4 py-6 overflow-y-auto">

// 用户消息气泡
<div className="self-end max-w-[70%] bg-[#F4C2C2] text-[#1C1C1E] rounded-[14px] px-4 py-2">

// Agent 消息气泡
<div className="self-start max-w-[85%] bg-white rounded-[14px] px-4 py-2
                border-l-2 border-[#EAABAA]">

// InputBar
<div className="sticky bottom-0 bg-white border-t border-[#EDE8E8] px-4 py-3">
```
