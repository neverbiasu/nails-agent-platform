# 价值评估评分公式文档

> **文件位置**: `nails_agent/agents/workers/value_evaluator.py`  
> **最后更新**: 2026-05-13

---

## 概述

价值评估（Value Evaluator）对每个 Top 趋势信号从三个独立维度打分，再合成为上架优先级分数。

```
trend_signal
    ├── 外部热度   (external_heat_score)    0-100
    ├── 新鲜度     (trend_growth_score)     0-100
    └── 风格缺口   (style_gap_score)        0-100
              ↓
    上架优先级 (launch_priority_score)      0-100
```

---

## 维度 1：外部热度（External Heat）

### 目的
衡量信号的**绝对互动量**，反映当前市场对该风格的真实需求。

### 原始互动量
```
composite = likes + collects × 1.5 + shares × 2 + comments × 0.5
```
权重设计：
- 收藏 × 1.5：用户主动收藏代表强兴趣，高于简单点赞
- 分享 × 2：分享具有传播乘数效应，是趋势扩散的先行指标
- 评论 × 0.5：评论有水军干扰风险，降权

### 归一化（对数缩放）
```
heat = log₁₊(composite) / log₁₊(max_composite_in_batch) × 100
```
选用 log1p 而非线性缩放的原因：防止单条病毒帖（100 万点赞）将其他信号压缩到接近 0，保留中尾分布的区分度。

---

## 维度 2：新鲜度（Freshness）

> 旧版叫"新鲜度"但实际只算发帖时间衰减，分数呈严格等差数列。新版引入"批次内新秀度"作为第二子项。

### 两个子项

#### A) 发帖时间衰减（recency，权重 0.6）
```
recency = max(0, (1 − hours_since_publish / 168) × 100)
```
- 0 小时前发布 → 100 分
- 168 小时（7 天）前发布 → 0 分
- 发布时间缺失 → 取批次内其他信号年龄的中位数（而非固定 50，避免大量缺时间的信号聚集在同一分值）

#### B) 批次内新秀度（novelty，权重 0.4）
```
rank_in_batch  = 该信号按综合互动量排序后的位置（0-based）
novelty = max(0, (1 − rank_in_batch / (batch_size − 1)) × 100)
```
**为什么需要 novelty？**  
单看发帖时间无法区分"一直很热的老款"和"刚突然爆发的新款"。一个发帖 5 天、互动量排在 batch 倒数的信号和一个发帖 5 天、互动量排第一的信号，recency 得分相同，但后者代表更高价值的上升趋势。novelty 基于当前批次内的相对排名，高互动 + 低排名（即新来者）获得更高分。

#### 合并
```
freshness = 0.6 × recency + 0.4 × novelty
```

---

## 维度 3：风格缺口（Style Gap）

> 旧版：简单计算标签重叠比例，导致大多数信号得分 8.3（因为大多数风格至少有 1 个标签被库覆盖）。新版引入覆盖广度子项。

### 两个子项

#### A) 覆盖广度（coverage_ratio）
```
coverage = 库中与该趋势有 ≥1 个标签重叠的款式数量
coverage_ratio = coverage / len(library)
```
衡量**有多少款竞品**在这个风格空间里。

#### B) 最优覆盖深度（max_overlap）
```
overlap_fraction(item) = |trend_tags ∩ item.style_tags| / |trend_tags|
max_overlap = max(overlap_fraction) over all library items
```
衡量**最强竞品**覆盖了多少趋势标签。

#### 综合饱和度
```
saturation = 0.5 × coverage_ratio + 0.5 × max_overlap
gap_score = (1 − saturation) × 100
```

**极端情况**：
- `gap = 100`：库中没有任何款式与趋势有标签重叠 → 纯白板机会
- `gap = 0`：库中有大量款式且其中最好的一款完全覆盖所有趋势标签 → 红海市场
- `gap = 50`（新基线）：趋势标签未知或库为空 → 中性

---

## 上架优先级（Launch Priority）

### 权重设计
```
priority = heat × 0.45 + freshness × 0.30 + gap × 0.25
```

| 维度 | 权重 | 设计理由 |
|---|---|---|
| 外部热度 | 0.45 | 最直接的市场信号；没有需求的趋势不值得追 |
| 新鲜度 | 0.30 | 在趋势顶峰前行动才能获取最大红利 |
| 风格缺口 | 0.25 | 差异化定位很重要，但不能无视需求；纯空白市场可能只是无人问津 |

### 与旧版对比
| 维度 | 旧版公式 | 问题 | 新版公式 |
|---|---|---|---|
| 外部热度 | `composite_score`（已是 0-100）| 线性缩放，病毒帖支配全局 | log1p 缩放 |
| 新鲜度 | `recency_score(publish_time)` | 纯时间衰减，等差数列 | 0.6×recency + 0.4×novelty |
| 风格缺口 | `1 - max_overlap / len(sig_tags)` | 1 标签重叠即大幅降分，多数信号卡在 8.3 | 0.5×覆盖广度 + 0.5×最优深度 |
| 优先级权重 | 0.5 / 0.3 / 0.2 | — | 0.45 / 0.30 / 0.25 |

---

## 调参指南

调整以下常量可以改变评分行为（无需改动公式结构）：

| 常量 | 位置 | 含义 | 当前值 |
|---|---|---|---|
| `168`（小时） | `_recency()` | 新鲜度半衰周期 | 7 天 |
| `0.6 / 0.4` | `_freshness_score()` | recency vs novelty 比例 | 6:4 |
| `0.5 / 0.5` | `_style_gap_score()` | coverage vs depth 比例 | 5:5 |
| `0.45 / 0.30 / 0.25` | `_priority_score()` | heat / freshness / gap 比例 | — |
| 互动量权重 `1.0 / 1.5 / 2.0 / 0.5` | `_heat_score()` | likes/collects/shares/comments | — |
