# demo_v1 整合验收方案

## 验收范围

本次整合将 `demo_v1/` 的 C 端试戴逻辑迁入 `nails_agent/services/`，通过 FastAPI 暴露，并将 `demo_v1/app.py` 改造为瘦 HTTP 客户端。验收分 4 个层次：基础环境、API 接口、消费者 UI、商家端回归。

---

## 1. 环境准备

```bash
# 安装所有依赖（含 consumer 的 MediaPipe/OpenCV 重型依赖）
pip install -e ".[demo,consumer,dev]"

# 写入种子数据到 SQLite（幂等，可重复执行）
python -m nails_agent.services.seed_loader

# 验证表已创建
sqlite3 ~/.nails_agent/memory.db ".tables"
# 期望看到: nail_styles_v2 reference_hand_profiles nail_visual_features
#           user_sessions user_hand_images user_hand_profiles
#           recommendation_snapshots behavior_events session_preference_profiles tryon_jobs

# 验证种子数量
sqlite3 ~/.nails_agent/memory.db "SELECT COUNT(*) FROM nail_styles_v2;"
# 期望: 27
sqlite3 ~/.nails_agent/memory.db "SELECT COUNT(*) FROM reference_hand_profiles;"
# 期望: 15
```

---

## 2. 服务启动

```bash
./scripts/dev.sh
# 应看到:
#   → starting FastAPI on :8000
#   → starting merchant Streamlit on :8501
#   → starting consumer V1 Streamlit on :8503
#   → starting Caddy on :8080 （若未安装则跳过）
```

日志文件：`logs/api.log`、`logs/merchant.log`、`logs/consumer.log`

---

## 3. API 接口验收（curl 脚本）

### 3.1 健康检查

```bash
curl -s http://localhost:8000/health | jq .
# 期望: {"status": "ok", ...}
```

### 3.2 手部分析

```bash
curl -s -F image=@demo_v1/images/image001.png \
  http://localhost:8000/hand/analyze | jq '{ok,hand_shape,skin_tone,undertone}'
# 期望: ok=true，三个字段非 null
```

### 3.3 风格库

```bash
curl -s http://localhost:8000/styles | jq 'length'
# 期望: 27

curl -s "http://localhost:8000/styles?try_on_only=true" | jq 'length'
# 期望: ≥1（有 is_available_for_try_on=true 的款式）

curl -s http://localhost:8000/styles/STYLE001 | jq '{style_id,title}'
# 期望: {"style_id": "STYLE001", "title": "酒红金线方格甲"}
```

### 3.4 完整会话流程

```bash
# 创建会话
SID=$(curl -s -F image=@demo_v1/images/image001.png \
  http://localhost:8000/sessions | jq -r .session.session_id)
echo "session: $SID"
# 期望: session: SESSION-001（或类似 ID）

# Round 1
curl -s -X POST http://localhost:8000/sessions/$SID/recommendations/round1 \
  | jq '{count: (.items | length), top: .items[0] | {rank,style_id,total_score,reason_tags}}'
# 期望: count=15，top.rank=1，total_score>0

# 记录行为事件
curl -s -X POST http://localhost:8000/sessions/$SID/events \
  -H 'content-type: application/json' \
  -d '{"style_id":"STYLE001","event_type":"click"}' | jq .ok
# 期望: true

# Round 2（需至少一条事件）
curl -s -X POST http://localhost:8000/sessions/$SID/recommendations/round2 \
  | jq '.items[0:3] | .[] | {rank,style_id,total_score,reason_tags}'
# 期望: 返回推荐列表，reason_tags 包含行为相关标签（如"偏好来源"）

# 试戴（无 COMFYUI_API_KEY 时期望 status=failed 而非 5xx）
curl -s -X POST http://localhost:8000/sessions/$SID/tryon \
  -H 'content-type: application/json' \
  -d '{"style_id":"STYLE001"}' | jq '{status,error_message}'
# 期望: status∈{pending,success,failed}，不报 500
```

### 3.5 有 ComfyUI Key 时的完整试戴验证

```bash
export COMFYUI_API_KEY=<your-key>
# 重启 ./scripts/dev.sh，再执行上面的 tryon 请求
# 期望: status=success，result_image_url 为 CDN 图片地址
```

---

## 4. 消费者 Streamlit UI 验收

访问 `http://localhost:8080/user/`（或 `http://localhost:8503/`）

| 步骤 | 操作 | 期望结果 |
|---|---|---|
| 1 | 上传 `demo_v1/images/image001.png` | 显示分析结果：手型、肤色、色调 |
| 2 | 查看 Round 1 推荐卡片 | 至少 6 张卡片，各有标题和匹配度 |
| 3 | 点击一张卡片上的"查看详情"或 Like 按钮 | 事件被记录（页面无报错） |
| 4 | 点击"刷新推荐（Round 2）"按钮 | 卡片重新排序，reason_tags 出现 |
| 5 | 点击"试戴"按钮 | 显示试戴结果或"生成中"状态 |
| 6 | 所有操作均无 CORS / 500 报错 | 浏览器 Console 无红色报错 |

---

## 5. 商家端回归验收

访问 `http://localhost:8080/`（或 `http://localhost:8501/`）

| 检查项 | 期望 |
|---|---|
| Trends / Campaign Tab 正常显示 | 数据加载无报错 |
| Chat Tab 能输入并得到响应 | Agent 正常对话 |
| Pipeline Tab 能触发流水线 | 状态更新正常 |
| Memory Tab 可查看记忆库条目 | 列表非空 |
| 以上功能与整合前行为一致 | 无 regression |

---

## 6. 路由验收（需安装 Caddy）

```bash
curl -sI http://localhost:8080/ | head -3
# 期望: 200 OK，X-Forwarded-Host 或 server: Caddy

curl -sI http://localhost:8080/user/ | head -3
# 期望: 200 OK

curl -s http://localhost:8080/api/health | jq .status
# 期望: "ok"
```

---

## 7. 验收通过标准

| 类别 | 通过标准 |
|---|---|
| 环境 | 27 styles + 15 profiles 入库，无报错 |
| API | 3.1–3.4 全部 curl 命令返回期望结果 |
| Consumer UI | 完整 6 步流程跑通，无 500/CORS 报错 |
| Merchant 回归 | 4 个 Tab 均正常工作 |
| 路由 | `/`、`/user/`、`/api/health` 均 200 |

---

## 8. 已知限制（不影响本次验收）

- 试戴结果图需要 `COMFYUI_API_KEY`，无 key 时返回 `status=failed` 是正常行为
- 12 款来自 V0 的款式 `reference_hand_profile_id=null`，Round 1 评分时手型匹配项得 0 分，但不影响流程
- MediaPipe 在 Apple Silicon M 系列上需要 Rosetta 或 conda 环境，若分析报 503 请检查 mediapipe 安装

---

## 附录：视频 Demo

验收期间可以同步录制 / 展示 Remotion 生成的演示视频：

```bash
cd video
npm install
npm start          # 打开 Remotion Studio 在浏览器中预览
npm run build      # 渲染 out/demo.mp4（31 秒，1920×1080）
```
