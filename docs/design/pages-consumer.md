# C端页面设计 — AI 美甲试戴平台

> 设计 DNA：参考小红书（内容发现）+ 美团（商家信息）+ Glossier（粉色调性）  
> 适配优先：Mobile-first（375px 基准），兼容 Tablet / Desktop  
> Token 来源：根目录 `DESIGN.md`

---

## 页面地图

```
/(user)                      ← 首页：款式 + 笔记发现（瀑布流）
/(user)/shop/[id]            ← 商家主页（款式 + 笔记 + 联系）
/(user)/note/[id]            ← 笔记/内容详情
/(user)/upload               ← 手型上传（Step 1）
/(user)/recommend            ← AI 推荐结果（Step 2）
/(user)/tryon                ← 试戴结果（Step 3）
```

---

## 全局布局（Mobile）

```
┌─────────────────────┐
│  TopBar（44px）      │  ← Logo 居中，左边返回/菜单，右边搜索图标
├─────────────────────┤
│                     │
│   Page Content      │  ← overflow-y: auto
│                     │
├─────────────────────┤
│  BottomTabBar（56px）│  ← 首页 / 发现 / 试戴(CTA) / 我的
└─────────────────────┘
```

TopBar：背景 `white`，`box-shadow: 0 1px 0 {border}`，sticky top  
BottomTabBar：背景 `white`，`box-shadow: 0 -1px 0 {border}`，sticky bottom

**BottomTabBar Tab 项：**

| Tab | 图标 | 激活色 |
|---|---|---|
| 首页 | house | `blushDeep` |
| 发现 | compass | `blushDeep` |
| **试戴**（CTA） | camera（圆形凸起按钮） | `blush` 背景 + `white` 图标 |
| 我的 | person | `blushDeep` |

试戴 tab 用凸起圆形按钮（高 56px，`blush` 背景，`rounded.pill`），视觉强调 AI 核心功能。

---

## `/(user)` — 首页（发现）

### 结构

```
TopBar
│
├─ 搜索栏（可选，style：input 组件，placeholder="搜索款式、颜色…"）
│
├─ 话题 tag 横向滚动行
│   [全部] [法式] [猫眼] [渐变] [夏日] [显白] …
│
└─ 双列瀑布流（StyleCard / NoteCard 混排）
    ↓ 无限滚动加载
```

**背景：** `offWhite` (#FDF9F9)

**话题 tag 行：**
- 横向 scroll（隐藏滚动条），padding `spacing.md`
- 选中 tag：`blush` 背景 + `white` 文字（反色）
- 未选中：tag 组件默认（`blushLight` 背景 + `blushDeep` 文字）

**双列 Grid：**
```tsx
// Mobile
<div className="columns-2 gap-3 px-3">

// Tablet ≥768px
<div className="columns-3 gap-4 px-4">

// Desktop ≥1280px
<div className="columns-4 gap-4 px-6">
```

使用 CSS `columns`（瀑布流），不用固定高度的 grid（让内容自然撑高）。

---

### StyleCard（款式卡片）

```
┌──────────────────┐
│                  │  ← 图片 3:4，object-fit cover
│     美甲图片      │     圆角：card（16px）上两角
│                  │
│                  │
├──────────────────┤  ← 分割线（无实线，纯视觉留白）
│ 夏日法式美甲      │  ← h2，ink，单行截断
│ [法式] [白色]     │  ← tag × 2，blushLight
│ 🤍 128           │  ← 收藏数，caption，inkSecond；收藏 icon 右侧
└──────────────────┘
```

- 整体：`white` 背景，`rounded.card`，`border: 1px solid {border}`
- hover（Desktop）：`border-color → blush`
- 点击：进入 `/note/[id]` 详情
- 收藏图标：默认 `inkLight` 轮廓心形；已收藏 → `blush` 实心

---

### NoteCard（笔记卡片，商家发布）

```
┌──────────────────┐
│                  │  ← 图片 3:4
│     笔记封面      │
│  [商家认证角标]   │  ← 右上角：蓝 V 或粉 V badge，8px，圆形
│                  │
├──────────────────┤
│ 春日裸色美甲教程  │  ← h2，单行截断
│ 👤 美甲师小芳    │  ← 头像 20px + 用户名，caption，inkSecond
│              48  │  ← 点赞数右对齐，caption
└──────────────────┘
```

商家认证角标：右上角绝对定位，`blushDeep` 背景 + `white` ✓ 图标，圆形 20px

---

### 空态 / 加载态

**加载态：** 骨架屏占位，高度与真实卡片比例一致，`blushLight` 底色 + shimmer 动画（`background: linear-gradient(90deg, #FDF0F0 0%, #FAE0E0 50%, #FDF0F0 100%)`，2s 无限循环）

**空态（无结果）：** 居中插画（美甲相关）+ "暂无相关款式" + "查看全部" 按钮

---

## `/(user)/shop/[id]` — 商家主页

### 结构

```
Banner 图（140px 高，object-fit cover）
│
├─ 头像区（头像 64px，overlap banner -32px，居左 spacing.lg）
│   头像旁：商家名称（h1）+ 认证 badge + 地址 caption
│
├─ 操作行：[预约] [收藏] [分享] 三个按钮并排
│
├─ 简介文字（body，inkSecond，展开/收起）
│
├─ Tab 切换：[款式] [笔记] [评价]
│
└─ Tab 内容区
    款式 tab → 双列 StyleCard grid
    笔记 tab → 双列 NoteCard grid
    评价 tab → 列表（头像 + 评分 + 文字）
```

**Banner：**
- 默认图片；无图时用 `blushLight` 渐变占位（`linear-gradient(135deg, #FDF0F0, #F4C2C2)`）

**头像：**
- 64px 圆形，`border: 3px solid white`（与 banner 形成浮起感）
- 商家认证：头像右下角 20px badge

**操作按钮：**
- `预约`：`button` 组件（blush 实心），`flex-1`
- `收藏`：`buttonOutline`，图标 + 文字
- `分享`：`buttonOutline`，图标 + 文字

**Tab 切换：**
- 下划线式，选中 tab：`blushDeep` 下划线 2px；文字 `ink`
- 未选中：`inkSecond`
- Tab 切换无跳转（客户端状态），URL 不变

---

## `/(user)/note/[id]` — 笔记详情

### 结构

```
← 返回（TopBar 左侧）
│
├─ 图片轮播（全宽，3:4 比例，支持左右滑动）
│   底部分页点（blush 实心 / border 空心）
│
├─ 内容区（padding spacing.lg）
│   商家信息行：头像 36px + 名字（body 加粗）+ 关注按钮
│   标题：h1
│   正文：body，inkSecond，展开/收起（超过 4 行）
│   tag 行：多个 tag 组件横排
│
├─ 互动行：❤️ 点赞数  🔖 收藏数  💬 评论数  ↗ 分享
│
├─ AI 推荐入口（醒目卡片）
│   ┌──────────────────────────────────┐
│   │  ✨ 想试试这款美甲效果？           │
│   │  上传手型，AI 帮你虚拟试戴         │
│   │  [立即试戴 →]                    │
│   └──────────────────────────────────┘
│   背景：blushLight，rounded.xl，padding spacing.lg
│   按钮：button 组件（blush 实心）
│   → 点击进入 /upload，携带 style_id
│
└─ 评论区
    输入框 + 评论列表（头像 32px + 名字 + 内容 + 时间 caption）
```

**AI 推荐入口卡片**是核心转化入口，视觉权重要仅次于图片。

---

## `/(user)/upload` — 手型上传（Step 1/3）

### 结构

```
TopBar：← 返回，标题"AI 试戴"，Step 指示 "1/3"
│
├─ 进度条（3 步，当前高亮 blush）
│
├─ 上传区域
│   ┌──────────────────────────────────┐
│   │                                  │
│   │   📷（相机图标，blush 色）        │
│   │                                  │
│   │   上传你的手型照片               │
│   │   正面拍摄，光线充足              │
│   │                                  │
│   │   [选择照片] 或拖拽到这里         │
│   └──────────────────────────────────┘
│   边框：`border: 2px dashed {border}`，`rounded.xl`，高 240px
│   hover / drag-over：`border-color → blush`，`backgroundColor → blushLight`
│
├─ 示例图片（3张小图横排）
│   "参考这样拍 ↓"，caption，inkSecond
│
└─ 拍摄小贴士（折叠区）
    • 将手放在白色或浅色背景上
    • 确保 5 根手指都完整入镜
    • 避免戴戒指或手链遮挡
```

**图片已选中状态：**
- 上传区替换为预览图（全填充，`object-fit: cover`）
- 右上角 ✕ 重选按钮（`inkSecond` 圆形背景）
- 底部出现「[下一步：查看推荐 →]」button

**上传中状态：**
- 覆盖蒙层（半透明 white）+ blush 色 spinner 居中

---

## `/(user)/recommend` — AI 推荐（Step 2/3）

### 结构

```
TopBar：← 返回，标题"为你推荐"，Step "2/3"
│
├─ 手型分析结果（顶部信息卡）
│   ┌────────────────────────────────────┐
│   │  你的手型：修长形                   │
│   │  肤色：冷白皮 / 中性调              │
│   │  推荐色系：粉色系、裸色、浅紫       │
│   └────────────────────────────────────┘
│   背景：`blushLight`，`rounded.lg`，padding `spacing.md`
│   文字：h2 + caption，左侧粉色图标
│
├─ "为你推荐的款式"（h1）
│
├─ 双列 StyleCard grid（推荐结果）
│   每张卡片右下角加"试戴这款"按钮（小 button，pill 形）
│   → 点击 → 提交 /api/v1/tryon/submit → 进入 /tryon
│
└─ 底部："没找到心仪款式？浏览全部 →"（链接，blushDeep 色）
```

**加载态：**
- 手型分析结果区：骨架屏（3行文字高度）
- 推荐列表：4个 StyleCard 骨架屏占位

---

## `/(user)/tryon` — 试戴结果（Step 3/3）

### 结构

```
TopBar：← 返回，标题"试戴效果"，Step "3/3"
│
├─ 结果展示区（tryonResult 组件）
│   ┌────────────────────────────────────┐
│   │                                    │ ← 图片 1:1，最大 480px
│   │     试戴渲染结果图                  │
│   │     （或骨架屏 + 进度文字）          │
│   └────────────────────────────────────┘
│
├─ 渲染进度（仅在 status=pending/running 时显示）
│   ⏳ AI 正在为你渲染，预计 20–30 秒…
│   （blushLight 骨架屏 + shimmer 动画，无 spinner）
│
├─ 款式信息（渲染完成后显示）
│   款式名（h2）+ tag × 3 + 商家名
│
├─ 操作区（渲染完成后显示）
│   [💾 保存图片]   [🔁 换一款]   [📅 预约体验]
│   三个按钮：保存=button，换一款=buttonOutline，预约=button（最重要）
│
├─ 相似款推荐（横向滚动，3张 StyleCard）
│   "你可能还喜欢"，h2
│
└─ 用户反馈（轻量）
    [❤️ 喜欢这款]  [👎 不太适合]
    → 点击写入 FeedbackEvent（POST /api/v1/sessions/feedback）
```

**轮询逻辑（前端）：**
- 每 3s 轮询 `GET /api/v1/tryon/{job_id}`
- `status: pending` → 骨架屏 + "排队中"
- `status: running` → 骨架屏 + "渲染中（进度动画）"
- `status: done` → `result_url` 替换骨架屏，fade-in 0.3s
- `status: failed` → 替换为错误态（下方说明）

**错误态：**
```
┌────────────────────────────────────┐
│         😢 渲染未能完成             │
│  可能是网络波动，请重试              │
│  [重新试戴]                        │
└────────────────────────────────────┘
```
- 图片区替换为错误卡片，`border: 1px solid {error}`，`rounded.xl`

---

## 跨页面交互状态

| 场景 | 处理方式 |
|---|---|
| 未登录访问 /upload | 引导登录 bottom sheet（不跳转，保留当前页） |
| 上传失败 | Toast 提示（顶部，`error` 背景，3s 消失） |
| 网络断开 | 页面顶部 banner："当前网络不稳定" + 重试 |
| 图片审核未通过 | 友好文案 + 重新上传按钮（不暴露技术错误） |

---

## Toast 规范

- 位置：顶部居中，safe-area 下方 8px
- 宽度：max-w 340px，自适应文字
- 成功：`success` 背景，白色文字，✓ 图标
- 错误：`error` 背景，白色文字，✕ 图标
- 提示：`blushLight` 背景，`ink` 文字，ℹ 图标
- 持续：3s 自动消失，可手动关闭（右侧 ✕）
- 动画：top slide-in 0.2s，0.2s slide-out

---

## Tailwind 速查（关键样式）

```tsx
// 页面根容器（C端）
<div className="min-h-screen bg-[#FDF9F9] pb-14">

// BottomTabBar
<nav className="fixed bottom-0 left-0 right-0 h-14 bg-white
                border-t border-[#EDE8E8] flex items-center justify-around z-50">

// 试戴 CTA tab 按钮
<button className="w-14 h-14 -mt-4 rounded-full bg-[#F4C2C2]
                   flex items-center justify-center shadow-md">

// 瀑布流容器
<div className="columns-2 md:columns-3 xl:columns-4 gap-3 px-3">

// StyleCard
<div className="break-inside-avoid mb-3 bg-white rounded-2xl
                border border-[#EDE8E8] hover:border-[#F4C2C2] transition-colors">

// 图片容器 3:4
<div className="relative aspect-[3/4] overflow-hidden rounded-t-2xl">
  <img className="absolute inset-0 w-full h-full object-cover" />
</div>

// 上传区 drop zone
<div className="border-2 border-dashed border-[#EDE8E8] rounded-2xl h-60
                flex flex-col items-center justify-center
                hover:border-[#F4C2C2] hover:bg-[#FDF0F0] transition-all">

// AI 推荐入口卡片
<div className="bg-[#FDF0F0] rounded-2xl p-6 mx-4 my-3">

// 试戴结果图容器
<div className="aspect-square max-w-[480px] mx-auto rounded-2xl
                overflow-hidden bg-[#FDF9F9]">
```
