# API 参考

> 前端集成和外部调用者的单一事实来源。  
> 所有端点来自 `nails_agent/api/main.py`，Schema 来自 `nails_agent/models/schemas.py`。  
> 系统设计：[Notion PRD v4](https://www.notion.so/faych/34e5f3c4a139801e806cd49a2af60591) | 完整架构：[architecture.md](architecture.md)
>
> **K1 双链路说明**：B 端 `/pipeline/*` 产出的款式优先级数据和 C 端 `/sessions/{id}/events` 记录的用户行为，均写入同一 SQLite MemoryStore，构成双链路共享 Memory 飞轮。

---

## 基础信息

| 项目 | 说明 |
|------|------|
| **本地直连** | `http://localhost:8000` |
| **通过 Caddy** | `http://localhost:8080/api`（前缀自动剥离） |
| **鉴权** | 无（CORS allow all origins） |
| **Content-Type** | `application/json`，文件上传端点使用 `multipart/form-data` |

---

## 智能运营 B 端接口

### `GET /health`

系统健康检查，返回版本和数据源可用状态。

**Response**
```json
{
  "status": "ok",
  "version": "0.2.0",
  "data_sources": {
    "xhs": true,
    "douyin_cdp": false,
    "instagram": false
  }
}
```

---

### `GET /sources`

数据源可用状态详情（同 `/health` 中的 `data_sources` 字段，独立端点）。

---

### `POST /chat`

关键词分发：检测消息中的触发词，自动启动对应流水线。

**Request**
```json
{
  "message": "帮我分析一下最新趋势",
  "session_id": "default"
}
```

触发词映射：

| 触发词 | 动作 |
|--------|------|
| `趋势` | Step 1 only（趋势分析） |
| `运营` / `完整` / `pipeline` | 完整 4 步流水线 |
| 其他 | 返回帮助提示 |

**Response**
```json
{
  "reply": "✅ 趋势分析完成！Top 3：猫眼, 法式, 夏日",
  "pipeline_id": "a1b2c3d4e5f6",
  "state": {"status": "done", "step": 4}
}
```

---

### `POST /pipeline/run`

显式触发完整 4 步流水线（同步，阻塞直到完成）。

**Response**
```json
{
  "pipeline_id": "a1b2c3d4e5f6",
  "status": "done",
  "message": "Pipeline 完成",
  "state": {"step": 4, "errors": []}
}
```

---

### `POST /pipeline/trend`

仅执行 Step 1（趋势分析），用于测试或局部更新。

**Response**
```json
{
  "pipeline_id": "a1b2c3d4e5f6",
  "status": "done",
  "message": "趋势分析完成"
}
```

---

### `GET /pipeline/{pipeline_id}`

按 ID 查询历史 pipeline 状态（从 SQLite）。

**Response**：完整 `PipelineState` JSON 或 `404`。

---

### `GET /pipeline/list?limit=20`

最近 N 次 pipeline 运行记录。

**Response**：`PipelineState[]`（简化版，含 pipeline_id, status, step, started_at）

---

### `GET /memory/search?q=&kind=&limit=10`

对 MemoryStore（FTS5）全文搜索。

| 参数 | 类型 | 说明 |
|------|------|------|
| `q` | str | 搜索词（支持中文） |
| `kind` | str? | 筛选类型：`trend / metric / style_card / pattern / anomaly / insight` |
| `limit` | int | 最多返回条数（默认 10） |

**Response**：`MemoryEntry[]`

---

### `GET /memory/insights?limit=20`

返回经 `distill()` 提炼的跨 run 长期洞察。

---

## C 端 AI 试戴接口

### `POST /hand/analyze`

分析手部图片（手型、肤色、色调）。需安装 `mediapipe` 依赖（`pip install -e ".[consumer]"`）。

**Request**：`multipart/form-data`，字段 `image`（JPEG / PNG）

**Response**
```json
{
  "ok": true,
  "hand_shape": "oval",
  "hand_shape_label": "椭圆形",
  "hand_shape_confidence": 0.82,
  "skin_tone": "light-medium",
  "skin_tone_label": "偏浅",
  "skin_confidence": 0.91,
  "undertone": "neutral",
  "undertone_label": "中性色调",
  "undertone_confidence": 0.75,
  "median_rgb": [210, 175, 148],
  "annotated_image_b64": "data:image/png;base64,..."
}
```

**503**：MediaPipe 依赖未安装

---

### `POST /sessions`

创建试戴会话（上传手部照片，自动分析 + Round 1 推荐）。

**Request**：`multipart/form-data`，字段 `image`

**Response**
```json
{
  "session": {
    "session_id": "sess_abc123",
    "status": "active",
    "created_at": "2026-05-13T10:00:00+08:00"
  },
  "user_image": { "user_hand_image_id": "...", "image_url": "..." },
  "hand_profile": {
    "hand_shape": "oval",
    "skin_tone": "light-medium",
    "undertone": "neutral"
  }
}
```

---

### `GET /sessions/{session_id}`

获取会话完整状态（session + 图片 + 手型分析）。

**Response**：`{session, user_image, hand_profile}`

---

### `POST /sessions/{session_id}/recommendations/round1`

（重新）生成 Round 1 推荐。

策略：**reference_hand_match** — 按手型 + 肤色与参考手型库（`reference_hand_profiles`）进行规则匹配，不依赖用户行为。

**Response**：`RecommendationSnapshot`（含 `items[]: {rank, style_id, total_score, hand_shape_score, skin_tone_score}`）

---

### `POST /sessions/{session_id}/recommendations/round2`

生成 Round 2 推荐（需至少 1 个 behavior event）。

策略：**session_visual_similarity_rerank** — 基于用户行为（click/try_on_start）构建偏好向量，对 Round 1 结果进行视觉相似度重排。

**400**：`"Round 2 needs at least one behavior event first."`

**Response**：`RecommendationSnapshot`

---

### `GET /sessions/{session_id}/recommendations/latest?round_no=`

获取最新推荐快照（可选按 round_no 筛选）。

**404**：该会话暂无推荐

---

### `POST /sessions/{session_id}/events`

记录用户行为事件（驱动 Round 2 偏好建模）。

**Request**
```json
{
  "style_id": "STYLE_001",
  "event_type": "click",
  "source_snapshot_id": "snap_xyz"
}
```

`event_type`：`click | try_on_start | try_on_success`

---

### `GET /sessions/{session_id}/events`

获取该会话的所有行为事件列表。

---

### `POST /sessions/{session_id}/tryon`

触发 ComfyUI 试戴（需 `COMFYUI_API_KEY`）。

**Request**
```json
{
  "style_id": "STYLE_001",
  "source_snapshot_id": "snap_xyz"
}
```

**Response**（TryOnJob）
```json
{
  "try_on_job_id": "job_abc",
  "session_id": "sess_123",
  "style_id": "STYLE_001",
  "status": "running",
  "result_image_url": null
}
```

轮询 `GET /sessions/{id}/tryon/latest` 直到 `status = "success"`。

---

### `GET /sessions/{session_id}/tryon/latest`

获取最新一次试戴任务状态。

**Response**
```json
{
  "try_on_job_id": "job_abc",
  "status": "success",
  "result_image_url": "https://storage.googleapis.com/comfy-cdn/..."
}
```

`status`：`running | success | failed`

---

## 款式库

### `GET /styles?try_on_only=false&with_visual_feature_only=false`

返回全部款式（V2，来自 SQLite `nail_styles_v2`）。

| 参数 | 类型 | 说明 |
|------|------|------|
| `try_on_only` | bool | 仅返回 `try_on_enabled=true` 的款式 |
| `with_visual_feature_only` | bool | 仅返回已提取视觉特征的款式 |

**Response**：`NailStyleV2[]`

---

### `GET /styles/{style_id}`

获取单个款式详情。**404** 如不存在。

---

### `POST /tryon`（Legacy）

B 端商户用：使用固定 hand_reference.jpg 测试 ComfyUI 试戴效果。

**Request**
```json
{
  "style_id": "STYLE_001"
}
```

**Response**
```json
{
  "success": true,
  "image_url": "https://...",
  "fallback_url": "demo/static/nail_reference.jpg",
  "duration_s": 42.3
}
```

---

## 核心 Schema 速查

### `TrendSignal`（原始采集信号）

| 字段 | 类型 | 说明 |
|------|------|------|
| `trend_id` | str | `TREND_YYYYMMDD_{PLATFORM}_{MD5[:6]}` |
| `platform` | str | `xhs / douyin / instagram` |
| `keyword` | str | 采集时使用的搜索词 |
| `caption` | str | 帖子标题/文案 |
| `likes` | int | 点赞数 |
| `collects` | int | 收藏数 |
| `shares` | int | 分享数 |
| `comments` | int | 评论数 |
| `publish_time` | str | ISO 8601 或 "" |
| `style_tags` | str[] | 款式标签（如 ["猫眼", "法式"]） |
| `composite_score` | float | `likes + collects×1.5 + shares×2 + comments×0.5` |

### `StyleTrend`（趋势聚合，Step 1 输出的核心字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `tag` | str | 款式名（如 "猫眼"） |
| `category` | str | `style / color / material / scene` |
| `post_count` | int | 携带此标签的帖子数 |
| `total_engagement` | int | 聚合互动量 |
| `aggregated_score` | float | 0-100 归一化得分 |
| `sample_caption` | str | 代表性帖子文案摘要 |

### `MetricSnapshot`（价值评估，Step 2a 输出）

| 字段 | 类型 | 说明 |
|------|------|------|
| `keyword` | str | 评估的关键词 |
| `external_heat_score` | float | 0-100，外部热度 |
| `trend_growth_score` | float | 0-100，新鲜度（发布时间衰减） |
| `style_gap_score` | float | 0-100，款式库缺口 |
| `launch_priority_score` | float | 0-100，加权综合得分 |
| `rank` | int | 排名 |

> 详细评分公式见 [`docs/scoring_formulas.md`](scoring_formulas.md)

### `StyleCard`（最终运营卡片，Step 3 输出）

| 字段 | 类型 | 说明 |
|------|------|------|
| `style_name` | str | 款式名称 |
| `platform_variants` | Dict[str, PlatformVariant] | `xhs / douyin / instagram` 各平台文案 |
| `pricing.base_price` | str | 如 "¥138" |
| `pricing.tier` | str | `基础款 / 进阶款 / 高端款` |
| `schedule.priority` | str | `P0 / P1 / P2` |
| `schedule.xiaohongshu_publish_at` | str | 排期日期（ISO 8601） |

### `HandProfile`（C 端手型分析）

| 字段 | 类型 | 说明 |
|------|------|------|
| `hand_shape` | str | `oval / square / round / almond / stiletto` |
| `skin_tone` | str | `light / light-medium / medium / medium-dark / dark` |
| `undertone` | str | `cool / neutral / warm` |
| `hand_shape_confidence` | float | 0.0-1.0 |
| `skin_confidence` | float | 0.0-1.0 |

### `RecommendationSnapshot`（推荐快照）

| 字段 | 类型 | 说明 |
|------|------|------|
| `snapshot_id` | str | 唯一 ID |
| `session_id` | str | 所属会话 |
| `round_no` | int | 1 或 2 |
| `strategy` | str | `reference_hand_match` 或 `session_visual_similarity_rerank` |
| `items` | RecommendationItem[] | 排序后的推荐列表 |

`RecommendationItem`：`{rank, style_id, total_score, hand_shape_score, skin_tone_score, visual_similarity_score, color_preference_score}`
