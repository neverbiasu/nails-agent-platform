# Demo V1 具体流程设计

版本：V1.1 视觉特征扩展版  
日期：2026-05-12

## 1. V1 核心定位

Demo V1 的目标是补充用户侧流程，让 V0 已经上架到美甲广场的款式进一步进入「用户上传手图、个性化推荐、AI 试戴、行为反馈、二轮推荐」链路。

V1 不追求长期多用户推荐，而是实现一次上传手图后的会话级个性化：

```text
本次上传手图
-> 本次手部画像
-> 本次推荐
-> 本次点击 / 试戴行为
-> 本次二轮推荐
```

用户重新上传手图后，系统重新创建 session，之前推荐偏好不保留。

## 2. 总流程

```text
Step 0 预处理美甲库
  -> 提取每张美甲图中的参考手画像
  -> 提取每张美甲图的色系、主色、调色板、冷暖色、明暗与饱和度

Step 1 用户上传手图
  -> 创建 TryOnSession
  -> 保存 UserHandImage

Step 2 分析用户手图
  -> 生成用户 HandProfile
  -> 输出手型、肤色、置信度

Step 3 第一轮推荐
  -> 用户 HandProfile 对比美甲库 reference HandProfile
  -> 生成 RecommendationSnapshot(round_no=1)
  -> 页面展示推荐款式

Step 4 用户点击 / 选择试戴
  -> 点击款式记录 click 事件
  -> 发起试戴记录 try_on_start 事件
  -> V1 初始阶段使用原图作为试戴结果占位
  -> 试戴成功记录 try_on_success 事件

Step 5 二轮推荐
  -> 根据本次 session 行为生成 SessionPreferenceProfile
  -> 使用视觉偏好向量计算相似款
  -> 生成 RecommendationSnapshot(round_no=2)

Step 6 用户重新上传手图
  -> 关闭旧 session
  -> 创建新 session
  -> 从 Step 1 重新开始
```

## 3. 页面结构建议

V1 Streamlit 页面建议分为 5 个区域。

### 3.1 用户手图上传区

功能：

- 上传完整手背图。
- 展示上传图片。
- 展示当前 session ID。
- 支持「重新上传并重置会话」。

页面状态：

| 状态 | 展示 |
| --- | --- |
| 未上传 | 上传入口 |
| 已上传未分析 | 图片预览 + 分析按钮 |
| 已分析 | 图片预览 + 手型肤色结果 |

### 3.2 手部画像识别区

展示用户手图识别结果：

```text
手型：纤长型
手型置信度：0.86
肤色：暖白
肤色 RGB：[226, 185, 154]
肤色置信度：0.81
识别方式：mediapipe_opencv
```

如果识别失败：

```text
未能稳定识别手部，请上传自然光下完整手背图。
```

V1 Demo 允许提供兜底按钮：

```text
使用模拟手部画像
```

### 3.3 第一轮推荐区

触发条件：

- 当前 session 已有用户 HandProfile。
- 美甲库已有 reference HandProfile。

推荐逻辑：

```text
只根据用户手型、肤色与美甲库参考手手型、肤色匹配。
```

页面展示：

- 推荐款式图片。
- 推荐排名。
- 综合匹配分。
- 推荐理由。
- 点击按钮。
- 试戴按钮。

推荐理由示例：

```text
参考图中的手型与你较接近，肤色同为暖白，适合优先试戴。
```

### 3.4 AI 试戴区

触发条件：

- 用户已选择某个推荐款式。
- 当前 session 已有用户上传手图。

调用流程：

```text
用户点击试戴
-> 创建 TryOnJob(status=pending)
-> 记录 SessionBehaviorEvent(try_on_start)
-> V1 初始阶段不调用真实 ComfyUI API
-> result_image_url 直接使用原图或预置占位图
-> TryOnJob.status=success
-> 记录 SessionBehaviorEvent(try_on_success)
-> 页面展示试戴结果图
```

失败处理：

```text
TryOnJob.status=failed
error_message 写入失败原因
页面提示稍后重试
```

### 3.5 第二轮推荐区

触发方式：

- 用户点击「刷新推荐」。

触发条件：

- 当前 session 至少存在 1 条 click 或 try_on 行为。

二轮推荐核心：

```text
保留第一轮手型 / 肤色匹配结果
+ 根据用户本次点击 / 试戴过款式的视觉特征生成偏好向量
+ 在美甲库中寻找色系、调色板、冷暖、明暗、饱和度相近的款式
```

页面展示：

- 第二轮推荐列表。
- 相比第一轮的推荐变化。
- 用户偏好摘要。

偏好摘要示例：

```text
本轮你更偏好：粉色系 / 裸色系、暖色、中明度。
已为你推荐相似调色板与相近视觉氛围的款式。
```

## 4. 预处理流程

V1 推荐依赖美甲库中的两类预处理数据：

1. 社媒图参考手画像。
2. 美甲款视觉特征。

### 4.1 参考手画像预处理

输入：

```text
data/nail_styles_v1.json
```

处理：

```text
读取美甲图
-> 识别图片中的手部区域
-> 提取手型
-> 提取肤色
-> 写入 reference_hand_profiles.json
```

输出：

```text
data/reference_hand_profiles.json
```

Demo 兜底策略：

- 如果自动识别不稳定，可以先人工 mock 参考手画像。
- 字段中保留 `analysis_method=manual_mock`，便于后续替换为真实识别。

### 4.2 美甲视觉特征预处理

输入：

```text
data/nail_styles_v1.json
已完成增强 / 裁剪 / 背景处理的美甲图
```

处理：

```text
读取美甲图
-> 用 OpenCV / PIL 读取像素
-> 用 KMeans 或颜色直方图提取 2-4 个 dominant_palette
-> 将 dominant_palette 映射为 primary_color_family / primary_color_name / primary_color_rgb
-> 根据 HSV / Lab 计算 color_temperature、brightness_level、saturation_level、contrast_level
-> 拼接生成 color_vector
-> 计算 feature_confidence 与 needs_manual_review
-> 写入 nail_visual_features.json
```

输出：

```text
data/nail_visual_features.json
```

V1.1 保留：

```text
primary_color_family
primary_color_name
primary_color_rgb
dominant_palette
color_temperature
brightness_level
saturation_level
contrast_level
color_vector
extractor_version
feature_confidence
needs_manual_review
```

暂不识别：

```text
nail_length
nail_shape
style_tag
```

说明：

- 当前阶段不处理背景模糊、图片增强、主体裁剪等问题，这部分由图片增强链路保证输入质量。
- 若 `feature_confidence` 低或 `dominant_palette` 过于分散，则 `needs_manual_review=true`，页面或调试表中提示人工复核。
- 该流程可以先对 `demo_v1/images` 批处理，后续替换为爬虫图入库后的自动预处理任务。

## 5. 第一轮推荐详细规则

### 5.1 输入

```text
UserHandProfile
NailStyleV1
ReferenceHandProfile
```

### 5.2 处理

对每个美甲款计算：

```text
hand_shape_score
skin_tone_score
round1_score
```

评分公式：

```text
round1_score =
  hand_shape_score * 0.50
+ skin_tone_score * 0.50
```

排序：

```text
round1_score 从高到低
```

### 5.3 输出

```text
RecommendationSnapshot(round_no=1, strategy=reference_hand_match)
```

### 5.4 页面解释口径

第一轮推荐可以这样讲：

```text
系统会优先推荐“参考图中的手型和肤色与你更接近”的款式。
这样用户能先看到在相似手部条件下展示效果较好的美甲。
```

## 6. 用户行为记录

V1 只记录当前 session 内的轻量行为。

### 6.1 点击行为

触发：

```text
用户点击推荐卡片 / 查看详情
```

写入：

```text
SessionBehaviorEvent(event_type=click, event_weight=1)
```

用途：

- 表示弱偏好。
- 二轮推荐中轻度影响视觉偏好画像。

### 6.2 发起试戴行为

触发：

```text
用户点击试戴按钮
```

写入：

```text
SessionBehaviorEvent(event_type=try_on_start, event_weight=3)
```

用途：

- 表示较强偏好。
- 二轮推荐中比点击权重更高。

### 6.3 试戴成功行为

触发：

```text
ComfyUI 返回试戴结果图
```

写入：

```text
SessionBehaviorEvent(event_type=try_on_success, event_weight=4)
```

用途：

- 表示强偏好。
- 二轮推荐中优先学习该款式的视觉特征。

## 7. 第二轮推荐详细规则

### 7.1 输入

```text
第一轮 RecommendationSnapshot
SessionBehaviorEvent
NailVisualFeature
```

### 7.2 生成 SessionPreferenceProfile

将用户行为映射到视觉偏好。

示例：

```text
用户点击 STYLE001：
  primary_color_family=pink，primary_color_name=裸粉，color_temperature=warm，brightness_level=medium
用户试戴 STYLE003：
  primary_color_family=nude，primary_color_name=豆沙，color_temperature=warm，brightness_level=medium
```

计算：

```text
pink +1
nude +3 或 +4
warm +1 +3 或 +4
medium brightness +1 +3 或 +4
按行为权重聚合 color_vector，得到 preference_color_vector
```

输出：

```text
preferred_color_families
preferred_primary_colors
preferred_color_temperatures
preferred_brightness_levels
preferred_saturation_levels
preference_color_vector
positive_style_ids
```

### 7.3 二轮分数

```text
round2_score =
  round1_score * 0.40
+ visual_similarity_score * 0.50
+ behavior_boost_score * 0.10
```

其中：

```text
visual_similarity_score:
候选款式的 color family / palette vector / color temperature / brightness / saturation 与本次偏好越接近，分数越高。

behavior_boost_score:
用户已点击或试戴过的款式默认只获得少量加权；若希望突出相似新款，也可以对 positive_style_ids 设置轻微降权。
```

推荐策略建议：

- 点击 / 试戴行为用于学习偏好，不直接等于“该款置顶”。
- 若候选款与用户偏好色系相同、调色板接近、冷暖与明暗接近，则优先上升。
- 若希望推荐更多相似新款，对已点击 / 已试戴款设置轻微降权。

V1 Demo 建议：

```text
已试戴款不隐藏，但不置顶。
相似色系 / 相似调色板 / 同冷暖色的未试戴款优先上升。
```

### 7.4 输出

```text
RecommendationSnapshot(round_no=2, strategy=session_visual_similarity_rerank)
SessionPreferenceProfile
```

## 8. ComfyUI API 对接流程

V1 初始阶段先不调用真实 ComfyUI API，试戴结果直接使用原图或预置占位图；后续 ComfyUI 工作流完成后，再替换试戴服务实现。ComfyUI 不纳入推荐算法。

### 8.1 请求输入

```text
用户手图 image_url
美甲款式图 nail_image_url
style_id
session_id
```

### 8.2 请求输出

```text
result_image_url
status
error_message
```

### 8.3 V1 初始状态流转

```text
pending
-> success
```

初始阶段处理方式：

```text
生成 TryOnJob
-> result_image_url 使用原图或预置占位图
-> status=success
```

### 8.4 后续 ComfyUI 接入后的状态流转

```text
pending
-> running
-> success
```

失败：

```text
pending / running
-> failed
```

这样可以保证推荐链路和行为回流不被图像生成接口阻塞。

## 9. 与 V0 的关系

V0 负责：

```text
趋势款识别
-> 机会判断
-> 营销内容生成
-> 上架到美甲广场
-> 行为趋势报告
```

V1 负责：

```text
用户上传手图
-> 用户侧个性化推荐
-> AI 试戴
-> 本次行为反馈
-> 二轮推荐
```

连接方式：

```text
V0 launched_nail_styles
-> V1 nail_styles_v1
```

V1 可以复用 V0 已上架款式作为美甲库来源，同时补充：

```text
reference_hand_profile_id
visual_feature_id
is_available_for_try_on
```

## 10. V1 开发顺序建议

### Phase 0：美甲视觉特征预处理

目标：

- 扩展 `nail_visual_features.json` 字段。
- 编写美甲视觉特征提取函数。
- 从美甲图片生成色系、主色、调色板、冷暖色、明暗、饱和度和颜色向量。
- 对低置信度结果保留人工修正入口。

### Phase 1：数据与页面骨架

目标：

- 建立 V1 JSON 数据文件。
- 页面支持上传手图。
- 页面展示美甲库。
- 页面可展示款式视觉特征调试信息。
- 页面展示 mock 用户手画像。

### Phase 2：第一轮推荐

目标：

- 美甲库补齐参考手画像。
- 根据手型、肤色生成第一轮推荐。
- 页面展示推荐理由。

### Phase 3：行为记录

目标：

- 点击推荐卡片写入 `SessionBehaviorEvent(click)`。
- 点击试戴按钮写入 `SessionBehaviorEvent(try_on_start)`。

### Phase 4：Mock 试戴接入

目标：

- 创建 `TryOnJob`。
- 先使用原图或预置占位图作为 `result_image_url`。
- 展示 Mock 试戴结果。
- 成功后写入 `try_on_success` 行为。

后续 ComfyUI API 完成后，再将 Mock 试戴服务替换为真实接口调用。

### Phase 5：第二轮推荐

目标：

- 根据 session 行为生成 `SessionPreferenceProfile`。
- 根据视觉偏好向量计算相似款推荐。
- 页面展示偏好摘要与第二轮推荐结果。

## 11. 当前最小可跑 Demo 流程

如果需要快速做出 V1 最小闭环，可以先这样实现：

```text
1. 准备 10-15 个 NailStyleV1
2. 人工 mock 每个款式的 reference HandProfile
3. 用代码提取或人工修正每个款式的 NailVisualFeature
4. 用户上传手图
5. 用户手型肤色先允许 mock 选择
6. 生成第一轮推荐
7. 用户点击 / 试戴
8. 试戴结果先用占位图
9. 根据点击 / 试戴行为生成视觉偏好画像与第二轮相似款推荐
```

这条最小闭环跑通后，再逐步替换：

```text
mock 用户手画像 -> 真实手图识别
mock 参考手画像 -> 社媒图自动识别
人工视觉特征 -> OpenCV 自动特征提取
mock 试戴结果 -> ComfyUI API
```
