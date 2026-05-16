---
version: alpha
name: "NailsAgent"
description: |
  美甲 AI 平台设计系统。视觉 DNA 参考 Glossier（blush pink + 暖白底 + 充分留白）。
  B端 = AI Chat 界面（参考 Claude.ai 结构，运营商使用）
  C端 = 内容发现平台（参考小红书 + 美团布局，消费者使用）
  两端共用 token，通过 layout 和 surface 色区分人格。

colors:
  # ── Brand ──────────────────────────────────────────────────────────────────
  blush:        "#F4C2C2"   # 主品牌粉 — 按钮、选中、用户消息气泡
  blushDeep:    "#D9868A"   # blush hover / active
  blushLight:   "#FDF0F0"   # 最浅粉 — tag 背景、卡片 hover tint
  blushMid:     "#EAABAA"   # 次要 accent — 分割线高亮、Agent 气泡竖线

  # ── Surface ────────────────────────────────────────────────────────────────
  white:        "#FFFFFF"
  offWhite:     "#FDF9F9"   # C端页面背景（带粉底的暖白）
  surfaceWarm:  "#F7F3F3"   # C端卡片背景
  bgMerchant:   "#F5F5F7"   # B端页面背景（偏冷中性，区分两端）
  panel:        "#FFFFFF"   # B端 panel、消息气泡、modal

  # ── Border ────────────────────────────────────────────────────────────────
  border:       "#EDE8E8"   # 通用分割线
  borderFocus:  "#D9868A"   # input focus ring

  # ── Text ──────────────────────────────────────────────────────────────────
  ink:          "#1C1C1E"   # 正文主色（暖黑）
  inkSecond:    "#6E6E73"   # 次要文字：时间戳、描述、副标题
  inkLight:     "#AEAEB2"   # 占位文字、禁用状态

  # ── Semantic ──────────────────────────────────────────────────────────────
  success:      "#30B07B"
  warning:      "#F5A623"
  error:        "#E05252"
  info:         "#4E8DDE"

  # ── Pipeline 状态（B端 EventLog 专用，勿跨场景复用）─────────────────────
  statusPending: "#F5A623"
  statusRunning: "#4E8DDE"
  statusDone:    "#30B07B"
  statusReject:  "#E05252"
  statusHuman:   "#B06ED4"   # HITL 等待人工审批 — 紫色专属

typography:
  # C端款式页大标题（hero / 模块标题）
  display:
    fontFamily: "'Plus Jakarta Sans', 'PingFang SC', 'Noto Sans SC', sans-serif"
    fontSize: "2.25rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "-0.02em"

  # 通用 h1
  h1:
    fontFamily: "'Plus Jakarta Sans', 'PingFang SC', 'Noto Sans SC', sans-serif"
    fontSize: "1.625rem"
    fontWeight: 700
    lineHeight: 1.3

  # 通用 h2 / 卡片标题
  h2:
    fontFamily: "'Plus Jakarta Sans', 'PingFang SC', 'Noto Sans SC', sans-serif"
    fontSize: "1.125rem"
    fontWeight: 600
    lineHeight: 1.4

  # 正文
  body:
    fontFamily: "'Plus Jakarta Sans', 'PingFang SC', 'Noto Sans SC', sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: 1.65

  # 辅助文字 / 时间戳 / tag 文字
  caption:
    fontFamily: "'Plus Jakarta Sans', 'PingFang SC', 'Noto Sans SC', sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.5

  # B端技术内容（EventLog、API 数据、agent 工具调用）
  mono:
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace"
    fontSize: "0.8125rem"
    fontWeight: 400
    lineHeight: 1.6

rounded:
  none:  "0"
  sm:    "6px"
  md:    "10px"
  lg:    "14px"
  xl:    "20px"
  card:  "16px"     # C端所有卡片统一圆角
  input: "10px"     # 输入框圆角
  pill:  "9999px"   # tag / badge / CTA button

spacing:
  xs:   "4px"
  sm:   "8px"
  md:   "16px"
  lg:   "24px"
  xl:   "40px"
  2xl:  "64px"
  3xl:  "96px"

components:
  # ── C端：款式卡片 ──────────────────────────────────────────────────────────
  styleCard:
    backgroundColor: "{colors.white}"
    rounded: "{rounded.card}"
    # 图片区 aspect-ratio: 3/4（竖版），底部信息区固定高度 72px
    # hover：border 2px solid {colors.blush}，无 scale transform

  # ── C端：商家/笔记 信息卡（小红书式）──────────────────────────────────────
  noteCard:
    backgroundColor: "{colors.white}"
    rounded: "{rounded.card}"
    # 图片区 aspect-ratio: 3/4，底部：头像(24px) + 用户名 + 点赞数

  # ── C端：话题/功能 tag ────────────────────────────────────────────────────
  tag:
    backgroundColor: "{colors.blushLight}"
    textColor: "{colors.blushDeep}"
    rounded: "{rounded.pill}"
    padding: "2px 10px"
    typography: "{typography.caption}"

  # ── C端：试戴结果展示区 ───────────────────────────────────────────────────
  tryonResult:
    backgroundColor: "{colors.offWhite}"
    rounded: "{rounded.xl}"
    padding: "{spacing.xl}"
    # 图片 1:1，最大 480px；加载中用 blushLight 骨架屏 + shimmer 动画

  # ── B端：用户发出的消息气泡 ───────────────────────────────────────────────
  chatUser:
    backgroundColor: "{colors.blush}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "{spacing.sm} {spacing.md}"

  # ── B端：Agent 回复气泡 ───────────────────────────────────────────────────
  chatAgent:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    padding: "{spacing.sm} {spacing.md}"
    # 左侧 2px 竖线 = {colors.blushMid}，标识 Agent 身份

  # ── B端：Pipeline 事件条目 ───────────────────────────────────────────────
  eventBubble:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.md}"
    padding: "{spacing.sm} {spacing.md}"
    # 左侧 3px 竖线跟随 Pipeline 状态色
    # event_type 用 {typography.mono}，created_at 用 {typography.caption}

  # ── B端：HITL 审批卡 ─────────────────────────────────────────────────────
  reviewCard:
    backgroundColor: "{colors.panel}"
    rounded: "{rounded.lg}"
    padding: "{spacing.lg}"
    # Pass → success，Reject → error，Revise → warning

  # ── 通用：主 CTA 按钮 ────────────────────────────────────────────────────
  button:
    backgroundColor: "{colors.blush}"
    textColor: "{colors.ink}"
    rounded: "{rounded.pill}"
    padding: "{spacing.sm} {spacing.lg}"
    fontWeight: 600

  button-hover:
    backgroundColor: "{colors.blushDeep}"
    textColor: "#FFFFFF"

  # ── 通用：次要按钮（描边式）─────────────────────────────────────────────
  buttonOutline:
    backgroundColor: "transparent"
    textColor: "{colors.blushDeep}"
    rounded: "{rounded.pill}"
    padding: "{spacing.sm} {spacing.lg}"
    # border: 1.5px solid {colors.blush}

  # ── 通用：输入框 ─────────────────────────────────────────────────────────
  input:
    backgroundColor: "{colors.white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.input}"
    padding: "{spacing.sm} {spacing.md}"
    # border: 1.5px solid {colors.border}
    # focus: border-color → {colors.borderFocus}，box-shadow: 0 0 0 3px rgba(244,194,194,0.25)
---

## Overview

视觉 DNA 参考 [Glossier](https://www.glossier.com)：blush pink 品牌色、暖白底色、充分留白、圆润友好的字体。

**两端人格分离：**

| | B端（运营商） | C端（消费者） |
|---|---|---|
| 页面背景 | `bgMerchant` #F5F5F7（冷中性） | `offWhite` #FDF9F9（暖白） |
| 主要交互 | AI Chat + Pipeline 状态 | 内容浏览 + 试戴 |
| 字体风格 | h1/h2，克制 | display + h1，有美感 |
| 布局参考 | Claude.ai | 小红书 + 美团 |
| 适配优先 | Desktop | Mobile-first |

---

## Colors

**规则（AI 必须遵守）：**

- `blush` 是唯一强调色，只用于 CTA button、选中状态、用户消息气泡、hover 描边
- 正文、icon、普通边框 **不用 blush 系颜色**，用 `ink / border / inkSecond`
- `blushLight` 只用于 tag 背景和轻 hover tint，不做大面积填充
- Pipeline 状态色（`statusPending` ~ `statusHuman`）仅限 B端 EventLog，不跨场景复用
- 不要出现裸写 hex，所有颜色必须引用 token

---

## Typography

字体栈：中文用 PingFang SC（macOS/iOS 系统字体，质感最好），跨平台回退 Noto Sans SC；英文/数字用 Plus Jakarta Sans（圆润友好，比 Inter 更有温度）。

**分工：**
- C端款式页大标题 → `display`（Glossier 风格，有美感）
- B端所有标题 → `h1/h2`（专业克制，不用 display）
- 正文统一 → `body`，行高 1.65 不覆盖
- EventLog、API 数据、工具调用状态 → `mono`，固定不替换
- 中文内容最小字号 14px（0.875rem）

---

## Layout

**B端 Chat（Desktop 优先）：**
```
┌─────────────────────────────────────────────┐
│  sidebar 200px  │  chat area max-w 680px    │
│  （折叠 52px）   │  （居中，上方消息流）      │
│                 │                           │
│  对话历史列表    │  消息气泡流               │
│                 │  ↑ Pipeline 状态内嵌其中   │
│                 │                           │
│                 │  [输入框 sticky bottom]    │
└─────────────────────────────────────────────┘
```

**C端 内容（Mobile-first）：**
```
375px:  2列 grid（卡片宽 ~164px）
768px:  3列 grid
1280px: 4列 grid

图片比例：3:4（竖版，贴近小红书内容习惯）
商家 banner：高 140px，头像 64px overlap 底部 -32px
底部 tab 导航：首页 / 发现 / 试戴 / 我的
```

---

## Elevation & Depth

扁平优先，border 做层次而非 shadow：

| 层级 | 用法 | 样式 |
|---|---|---|
| 默认卡片 | styleCard, noteCard | `border: 1px solid {colors.border}` |
| Hover 卡片 | 鼠标悬停 | `border-color → {colors.blush}` |
| 浮层 | modal, bottom sheet | `box-shadow: 0 12px 32px rgba(0,0,0,0.08)` |
| 顶导栏 | sticky header | `box-shadow: 0 1px 0 {colors.border}` |

不使用超过 1 层 shadow 叠加。

---

## Components

**StyleCard / NoteCard（C端）**
- 图片 aspect-ratio 3:4，`object-fit: cover`，`border-radius` 上两角 = `rounded.card`
- 底部信息区：款式名（h2）+ tag（最多 2 个）+ 收藏图标（blush 心形）
- hover：border 粉色描边，收藏图标加深，无 scale

**ChatAgent 气泡（B端）**
- 左边 2px blushMid 竖线标识 Agent 身份
- 工具调用 / Pipeline 步骤折叠展示在气泡下方（默认收起）
- 点击展开显示 EventLog 详情，用 mono 字体，浅灰背景 `surfaceWarm`

**EventBubble（B端）**
- 左侧 3px 彩色竖线 = Pipeline 状态色
- event_type 加粗 mono，created_at caption 右对齐
- payload 默认折叠，点击展开 JSON

**TryonResult（C端）**
- 图片加载中：blushLight 骨架屏 + shimmer 动画（右向渐变）
- 加载完成：`opacity: 0 → 1`，transition 0.3s ease
- 无 spinner，无进度条，只有骨架屏

**ReviewCard（B端 HITL）**
- CandidatePackage 摘要在上方（卡片形式）
- 三个并排按钮：通过（success 绿）/ 修改（warning 橙）/ 拒绝（error 红）
- 确认 dialog 二次确认，防误操作

---

## Do's and Don'ts

**✅ 必须做：**
- 所有颜色引用 token，不裸写 hex
- 中文字号最小 14px
- 所有可点击元素有明确 hover 状态
- 图片容器固定宽高比，不允许变形
- 加载态必须有骨架屏或 spinner，不留空白

**❌ 禁止：**
- 正文不用纯黑 #000000，用 `{colors.ink}` #1C1C1E
- B端不用 display 字体（太柔，不专业）
- C端不放密集表格或数据 dashboard
- 自定义 breakpoint，只用 Tailwind 默认（sm/md/lg/xl/2xl）
- 在 B端 Chat 区域嵌入 C端的内容 grid
