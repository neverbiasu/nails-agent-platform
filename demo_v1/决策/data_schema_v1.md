# Demo V1 数据结构设计

版本：V1.1 视觉特征扩展版  
日期：2026-05-12

## 1. 设计目标

Demo V1 在 V0 商家侧智能运营闭环基础上，补充用户侧 AI 试戴与会话级个性化推荐。

V1 的核心链路是：

```text
用户上传手图
-> 系统识别用户手型与肤色
-> 与美甲库中社媒图的参考手画像进行匹配
-> 生成第一轮推荐
-> 用户点击 / 试戴
-> 系统记录本次会话行为
-> 基于本次行为学习颜色偏好，并按美甲视觉特征相似度生成第二轮推荐
```

## 2. V1 边界

V1 实现：

- 用户上传完整手背图。
- 从用户手图中识别手型、肤色。
- 对美甲库图片中的参考手进行手型、肤色识别。
- 第一轮推荐只基于用户手画像与参考手画像匹配。
- 用户点击美甲款式。
- 用户选择款式后创建试戴任务；V1 初始阶段先使用原图作为试戴结果占位，后续再替换为 ComfyUI API。
- 记录本次 session 内的点击、试戴行为。
- 第二轮推荐基于本次 session 行为，结合色系、主色调、调色板、冷暖色、明暗与饱和度进行视觉相似款推荐。

V1 暂不实现：

- 多用户长期个性化推荐。
- 跨 session 用户画像保留。
- 向量库 / RAG 推荐。
- 甲型长度识别。
- 甲型轮廓识别。
- 长期趋势款动态计算。
- 复杂风格标签体系。

## 3. 枚举定义

### 3.1 HandShape

手型分类用于用户手图与社媒参考手图的匹配。

| 枚举值 | 中文名 | 说明 |
| --- | --- | --- |
| `slender_long` | 纤长型 | 手指较长，掌宽较窄 |
| `short_wide` | 短宽型 | 手掌偏宽，手指相对较短 |
| `square_palm` | 方掌型 | 掌部宽高比较接近，掌形偏方 |
| `narrow_palm` | 窄掌型 | 掌宽较窄，整体细窄 |
| `unknown` | 未识别 | 识别失败或置信度不足 |

说明：

- `HandShape` 是固定枚举，不是一张运行时数据表。
- 五种手型本身不需要 `owner_id`。
- `HandProfile` 表记录的是“某张具体图片被识别出来的手部画像实例”，其中的 `hand_shape` 字段引用这里的枚举值。
- 系统真正用于判断手型的分类依据由 `HandShapeDefinition` 配置提供。

### 3.2 SkinTone

肤色分类用于参考手画像匹配。

| 枚举值 | 中文名 | 说明 |
| --- | --- | --- |
| `cool_fair` | 冷白 | 明度高，冷调明显 |
| `warm_fair` | 暖白 | 明度高，暖调明显 |
| `natural` | 自然肤色 | 明度中等，冷暖不明显 |
| `warm_yellow` | 暖黄 | 黄调较明显 |
| `wheat` | 小麦色 | 明度较低，偏健康肤色 |
| `deep` | 深肤色 | 明度低，肤色较深 |
| `unknown` | 未识别 | 识别失败或置信度不足 |

说明：

- `SkinTone` 是固定枚举，不是一张运行时数据表。
- 系统真正用于判断肤色的分类依据由 `SkinToneDefinition` 配置提供。

### 3.3 Undertone

| 枚举值 | 中文名 |
| --- | --- |
| `warm` | 暖调 |
| `cool` | 冷调 |
| `neutral` | 中性 |
| `unknown` | 未识别 |

说明：

- `Undertone` 表示肤色冷暖倾向。
- `undertone` 的具体判定依据由 `UndertoneDefinition` 配置提供。
- `SkinToneDefinition` 主要负责肤色深浅与类别，`UndertoneDefinition` 负责冷暖倾向；最终写入同一条 `HandProfile`。

### 3.4 ColorTemperature

用于美甲款视觉特征。

| 枚举值 | 中文名 | 示例 |
| --- | --- | --- |
| `warm` | 暖色 | 红、橙、黄、金、棕、豆沙 |
| `cool` | 冷色 | 蓝、绿、紫、银灰 |
| `neutral` | 中性色 | 黑、白、灰、裸色、透明 |
| `mixed` | 混合色 | 多色且无明显主冷暖 |
| `unknown` | 未识别 | 识别失败 |

### 3.5 ColorFamily

用于把自动提取出的主色归一到稳定色系，避免推荐逻辑依赖过细的中文颜色名。

| 枚举值 | 中文名 | 示例 |
| --- | --- | --- |
| `red` | 红色系 | 正红、酒红、玫瑰红 |
| `pink` | 粉色系 | 裸粉、蜜桃粉、玫粉 |
| `nude` | 裸色系 | 裸透、豆沙、奶茶 |
| `white` | 白色系 | 奶白、珍珠白 |
| `black` | 黑色系 | 黑色、黑玫瑰、黑银 |
| `green` | 绿色系 | 橄榄绿、墨绿 |
| `blue` | 蓝色系 | 雾霾蓝、宝石蓝 |
| `purple` | 紫色系 | 薰衣草紫、葡萄紫 |
| `gold_silver` | 金银色系 | 香槟金、银灰、金属银 |
| `multi` | 多色系 | 渐变、撞色、多主色 |
| `unknown` | 未识别 | 识别失败 |

### 3.6 VisualLevel

用于描述明暗、饱和度、对比度等连续视觉特征的离散等级。

| 枚举值 | 中文名 | 说明 |
| --- | --- | --- |
| `light` | 浅明度 | 用于 `brightness_level` |
| `dark` | 深明度 | 用于 `brightness_level` |
| `low` | 低 | 用于低饱和或低对比 |
| `medium` | 中 | 中等明度、饱和度或对比 |
| `high` | 高 | 用于高饱和或高对比 |
| `mixed` | 混合 | 不同区域差异明显 |
| `unknown` | 未识别 | 识别失败 |

### 3.7 BehaviorType

V1 只记录本次 session 内行为。

| 枚举值 | 中文名 | 推荐权重 |
| --- | --- | ---: |
| `click` | 点击查看 | 1 |
| `try_on_start` | 发起试戴 | 3 |
| `try_on_success` | 试戴成功 | 4 |

## 4. 数据表定义

### 4.0 HandShapeDefinition

手型分类标准配置。该配置用于说明系统如何把一张手图识别出的几何特征映射到固定手型枚举。

它不是用户画像，也不是美甲款式数据，而是算法规则/分类标准。V1 初始阶段可以先写成静态 JSON 配置。

建议文件：

```text
data/hand_shape_definitions.json
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `hand_shape` | enum | 是 | 对应 `HandShape` 枚举 |
| `display_name` | string | 是 | 中文展示名 |
| `description` | string | 是 | 手型解释 |
| `feature_rules` | object | 是 | 几何特征判断规则 |
| `similar_shapes` | array | 是 | 相近手型，用于匹配分计算 |
| `recommendation_note` | string | 否 | 推荐解释用文案 |

可计算的几何特征建议：

| 特征 | 含义 | 示例 |
| --- | --- | --- |
| `finger_to_palm_ratio` | 手指长度 / 手掌长度 | 判断手指是否偏长 |
| `palm_width_ratio` | 手掌宽度 / 手掌长度 | 判断掌形宽窄 |
| `hand_aspect_ratio` | 整只手高度 / 宽度 | 判断整体修长程度 |
| `finger_length_variance` | 食指、中指、无名指、小指长度差异 | 判断关键点是否稳定，仅作辅助 |
| `landmark_visibility_score` | 手部关键点检测完整度 | 低于阈值时归为 unknown |

以上指标可以由 MediaPipe Hands 的 21 个关键点计算得到，OpenCV 负责图片读取、坐标换算和必要的距离计算。

基础关键点计算建议：

```text
palm_width = distance(index_mcp, pinky_mcp)
palm_length = distance(wrist, middle_mcp)
middle_finger_length = distance(middle_mcp, middle_pip) + distance(middle_pip, middle_dip) + distance(middle_dip, middle_tip)
avg_finger_length = mean(index_finger_length, middle_finger_length, ring_finger_length, pinky_finger_length)
finger_to_palm_ratio = avg_finger_length / palm_length
palm_width_ratio = palm_width / palm_length
hand_aspect_ratio = distance(wrist, middle_tip) / palm_width
```

分类优先级建议：

```text
1. 如果未检测到完整单手关键点，或 landmark_visibility_score < 0.70 -> unknown
2. 如果 palm_width_ratio >= 0.95 -> square_palm
3. 如果 finger_to_palm_ratio >= 1.35 且 palm_width_ratio <= 0.82 -> slender_long
4. 如果 palm_width_ratio <= 0.72 -> narrow_palm
5. 如果 finger_to_palm_ratio <= 1.05 且 palm_width_ratio >= 0.84 -> short_wide
6. 其他情况按 finger_to_palm_ratio 与 palm_width_ratio 距离最近的手型中心归类
```

手型中心值建议用于兜底归类：

| hand_shape | finger_to_palm_ratio | palm_width_ratio | hand_aspect_ratio |
| --- | ---: | ---: | ---: |
| `slender_long` | 1.42 | 0.78 | 2.55 |
| `short_wide` | 1.00 | 0.90 | 2.10 |
| `square_palm` | 1.12 | 0.98 | 2.05 |
| `narrow_palm` | 1.20 | 0.68 | 2.60 |

示例：

```json
{
  "hand_shape": "slender_long",
  "display_name": "纤长型",
  "description": "手指较长，掌宽较窄，整体比例修长。",
  "feature_rules": {
    "finger_to_palm_ratio": ">= 1.35",
    "palm_width_ratio": "<= 0.82",
    "landmark_visibility_score": ">= 0.70"
  },
  "similar_shapes": ["narrow_palm"],
  "recommendation_note": "适合展示细长线条感和留白感较强的款式。"
}
```

V1 需要实现真实用户上传图识别，不再 mock 用户手型。社媒美甲库中的参考手画像可以先由同一套识别函数批量预处理生成，必要时允许人工修正。

### 4.0.1 SkinToneDefinition

肤色分类标准配置。该配置用于说明系统如何把手部区域采样得到的颜色特征映射到固定肤色枚举。

它不是用户画像，也不是美甲款式数据，而是算法规则/分类标准。V1 初始阶段可以先写成静态 JSON 配置。

建议文件：

```text
data/skin_tone_definitions.json
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `skin_tone` | enum | 是 | 对应 `SkinTone` 枚举 |
| `display_name` | string | 是 | 中文展示名 |
| `description` | string | 是 | 肤色解释 |
| `feature_rules` | object | 是 | 颜色特征判断规则 |
| `adjacent_tones` | array | 是 | 相邻肤色，用于匹配分计算 |
| `recommendation_note` | string | 否 | 推荐解释用文案 |

可计算的颜色特征建议：

| 特征 | 含义 | 示例 |
| --- | --- | --- |
| `median_rgb` | 手部采样区域 RGB 中位数 | 页面展示和调试 |
| `lab_l` | Lab 色彩空间亮度 L | 判断明度高低 |
| `lab_a` | Lab 色彩空间红绿轴 | 辅助判断冷暖 |
| `lab_b` | Lab 色彩空间黄蓝轴 | 判断黄调 / 暖调 |
| `hsv_h` | HSV 色相 | 辅助区分偏红、偏黄 |
| `hsv_s` | HSV 饱和度 | 判断肤色是否偏灰或偏浓 |
| `ycrcb_y` | YCrCb 亮度 | 辅助判断肤色深浅 |
| `sample_stability` | 采样像素集中度 | 低于阈值时归为 unknown |

肤色采样建议：

```text
1. 使用 MediaPipe Hands 定位手部关键点。
2. 优先在手背中心或掌部区域构造采样 mask。
3. 避开指甲、背景、高光、强阴影区域。
4. 对采样像素取 median_rgb。
5. 将 RGB 转换到 Lab / HSV / YCrCb。
6. 根据 SkinToneDefinition 归类 skin_tone。
7. 根据 UndertoneDefinition 归类 undertone。
```

分类优先级建议：

```text
1. 如果没有稳定手部 mask，或 sample_stability < 0.60 -> unknown
2. 如果 lab_l >= 78 且 lab_b < 13 -> cool_fair
3. 如果 lab_l >= 76 且 lab_b >= 13 -> warm_fair
4. 如果 62 <= lab_l < 76 且 lab_b < 18 -> natural
5. 如果 62 <= lab_l < 76 且 lab_b >= 18 -> warm_yellow
6. 如果 48 <= lab_l < 62 -> wheat
7. 如果 lab_l < 48 -> deep
```

以上阈值是 V1 初版启发式规则，后续需要用真实上传图微调。

示例：

```json
{
  "skin_tone": "warm_fair",
  "display_name": "暖白",
  "description": "整体明度较高，肤色偏暖、偏黄或偏蜜桃。",
  "feature_rules": {
    "lab_l": ">= 76",
    "lab_b": ">= 13",
    "sample_stability": ">= 0.60"
  },
  "adjacent_tones": ["cool_fair", "natural", "warm_yellow"],
  "recommendation_note": "适合裸粉、豆沙、香槟金等柔和暖色系。"
}
```

### 4.0.2 UndertoneDefinition

肤色冷暖倾向分类标准配置。该配置用于说明系统如何根据手部采样颜色的 Lab / HSV / YCrCb 特征判断 undertone。

建议文件：

```text
data/undertone_definitions.json
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `undertone` | enum | 是 | 对应 `Undertone` 枚举 |
| `display_name` | string | 是 | 中文展示名 |
| `description` | string | 是 | 冷暖倾向解释 |
| `feature_rules` | object | 是 | 冷暖倾向判断规则 |
| `recommendation_note` | string | 否 | 推荐解释用文案 |

可计算的颜色特征建议：

| 特征 | 含义 | 用途 |
| --- | --- | --- |
| `lab_b` | 黄蓝轴，数值越高越偏黄 | 判断 warm |
| `lab_a` | 红绿轴，数值偏低时可能更冷或偏青 | 辅助判断 cool |
| `hsv_h` | 色相 | 辅助判断偏红、偏黄、偏青 |
| `hsv_s` | 饱和度 | 饱和度过低时更容易归为 neutral |
| `ycrcb_cr` | 红色色度 | 辅助判断暖调 |
| `ycrcb_cb` | 蓝色色度 | 辅助判断冷调 |
| `sample_stability` | 采样像素集中度 | 低于阈值时归为 unknown |

分类优先级建议：

```text
1. 如果没有稳定手部 mask，或 sample_stability < 0.60 -> unknown
2. 如果 hsv_s < 0.12，且 lab_b 在 10-18 之间 -> neutral
3. 如果 lab_b >= 18，或 ycrcb_cr - ycrcb_cb >= 12 -> warm
4. 如果 lab_b <= 10，或 ycrcb_cb - ycrcb_cr >= 8 -> cool
5. 其他情况 -> neutral
```

示例：

```json
{
  "undertone": "warm",
  "display_name": "暖调",
  "description": "肤色中黄调、蜜桃调或红调更明显。",
  "feature_rules": {
    "lab_b": ">= 18",
    "ycrcb_cr_minus_cb": ">= 12",
    "sample_stability": ">= 0.60"
  },
  "recommendation_note": "更适合暖粉、豆沙、香槟金、酒红等颜色。"
}
```

### 4.0.3 ColorFeatureRule

美甲视觉特征规则配置。该配置用于把自动提取出的 RGB / HSV / Lab 颜色结果映射到稳定枚举，避免推荐代码直接写死大量颜色阈值。

建议文件：

```text
data/color_feature_rules.json
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `rule_id` | string | 是 | 规则 ID，如 `CFR_RED_001` |
| `target_type` | string | 是 | `color_family` / `color_temperature` / `brightness_level` / `saturation_level` |
| `target_value` | enum | 是 | 对应目标枚举值 |
| `display_name` | string | 是 | 展示名 |
| `feature_rules` | object | 是 | HSV / Lab / RGB 阈值规则 |
| `priority` | number | 是 | 多规则命中时的优先级 |

示例：

```json
{
  "rule_id": "CFR_PINK_001",
  "target_type": "color_family",
  "target_value": "pink",
  "display_name": "粉色系",
  "feature_rules": {
    "hsv_h": "330-360 or 0-20",
    "hsv_s": ">= 0.18",
    "lab_l": ">= 45"
  },
  "priority": 20
}
```

### 4.1 TryOnSession

一次用户上传手图后产生一个临时会话。用户重新上传手图时，创建新 session，之前的个性化数据不继续参与推荐。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `session_id` | string | 是 | 会话 ID，如 `S001` |
| `current_user_label` | string | 否 | Demo 用模拟用户标识，如 `guest` |
| `status` | string | 是 | `active` / `closed` |
| `created_at` | datetime | 是 | 创建时间 |
| `closed_at` | datetime | 否 | 关闭时间 |
| `reset_reason` | string | 否 | 新上传手图 / 手动重置等 |

示例：

```json
{
  "session_id": "S001",
  "current_user_label": "guest",
  "status": "active",
  "created_at": "2026-05-09T14:00:00+08:00",
  "closed_at": null,
  "reset_reason": null
}
```

### 4.2 UserHandImage

记录用户上传的完整手背图。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `user_hand_image_id` | string | 是 | 用户手图 ID，如 `UHI001` |
| `session_id` | string | 是 | 所属会话 |
| `image_url` | string | 是 | 本地图片路径或对象存储 URL |
| `image_width` | number | 否 | 图片宽度 |
| `image_height` | number | 否 | 图片高度 |
| `uploaded_at` | datetime | 是 | 上传时间 |
| `analysis_status` | string | 是 | `pending` / `success` / `failed` |

### 4.3 HandProfile

通用手部画像表，既用于用户上传手图，也用于美甲库中社媒参考手图。

注意：

- `HandProfile` 不是五种手型的定义表。
- 它表示一次具体识别结果，例如“用户上传的这张手图被识别为纤长型、暖白肤色”。
- 固定手型分类由 `HandShape` 枚举定义，`HandProfile.hand_shape` 只保存识别后命中的枚举值。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `hand_profile_id` | string | 是 | 手部画像 ID，如 `HP001` |
| `owner_type` | string | 是 | `user_upload` / `nail_reference` |
| `owner_id` | string | 是 | 当 `owner_type=user_upload` 时为 `user_hand_image_id`；当 `owner_type=nail_reference` 时为 `style_id` |
| `hand_shape` | enum | 是 | 见 `HandShape` |
| `hand_shape_confidence` | number | 是 | 0-1 |
| `skin_tone` | enum | 是 | 见 `SkinTone` |
| `undertone` | enum | 是 | 见 `Undertone` |
| `skin_rgb` | array | 否 | 识别出的肤色 RGB，如 `[218, 174, 145]` |
| `skin_confidence` | number | 是 | 0-1 |
| `analysis_method` | string | 是 | `mediapipe_opencv` / `manual_mock` / `vision_model` |
| `created_at` | datetime | 是 | 创建时间 |

示例：

```json
{
  "hand_profile_id": "HP001",
  "owner_type": "user_upload",
  "owner_id": "UHI001",
  "hand_shape": "slender_long",
  "hand_shape_confidence": 0.86,
  "skin_tone": "warm_fair",
  "undertone": "warm",
  "skin_rgb": [226, 185, 154],
  "skin_confidence": 0.81,
  "analysis_method": "mediapipe_opencv",
  "created_at": "2026-05-09T14:00:10+08:00"
}
```

### 4.4 NailStyleV1

V1 中参与推荐和试戴的美甲款式库。可以由 V0 已上架款式、社媒趋势款或静态 mock 数据生成。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `style_id` | string | 是 | 款式 ID，如 `STYLE001` |
| `source_style_id` | string | 否 | 来源于 V0 时记录原始 ID |
| `title` | string | 是 | 款式标题 |
| `image_url` | string | 是 | 美甲图片 |
| `source_platform` | string | 否 | 小红书、抖音、站内等 |
| `reference_hand_profile_id` | string | 是 | 社媒图中参考手画像 ID |
| `visual_feature_id` | string | 是 | 视觉特征 ID |
| `is_available_for_try_on` | boolean | 是 | 是否可试戴 |
| `created_at` | datetime | 是 | 入库时间 |

### 4.5 NailVisualFeature

记录美甲款式的视觉特征。V1.1 的目标是支持真实爬虫图片进入美甲库后，由代码自动提取颜色相关字段，并服务第二轮相似款推荐。

边界说明：

- 默认输入图片已经经过图片增强 / 裁剪 / 背景处理，能代表该美甲款式本身。
- 当前阶段先做颜色与整体视觉特征，不做甲型长度、甲型轮廓识别。
- `primary_color_name` 用于页面展示，`primary_color_family` 和 `dominant_palette` 用于推荐计算。
- `color_vector` 是机器计算字段，用于后续按颜色距离做相似度，不要求人工理解。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `visual_feature_id` | string | 是 | 视觉特征 ID，如 `NVF001` |
| `style_id` | string | 是 | 款式 ID |
| `primary_color_family` | enum | 是 | 主色系，见 `ColorFamily` |
| `primary_color_name` | string | 是 | 页面展示用主色名称，如 `裸粉`、`玫红`、`黑色` |
| `primary_color_rgb` | array | 否 | 主色 RGB，如 `[196, 68, 112]` |
| `dominant_palette` | array | 是 | 主要调色板，保存 2-4 个颜色及占比 |
| `color_temperature` | enum | 是 | 见 `ColorTemperature` |
| `brightness_level` | enum | 是 | 整体明暗，见 `VisualLevel` |
| `saturation_level` | enum | 是 | 整体饱和度，见 `VisualLevel` |
| `contrast_level` | enum | 否 | 颜色对比度，见 `VisualLevel` |
| `color_vector` | array | 是 | 推荐计算用颜色向量，可由主色 RGB、HSV/Lab、调色板比例拼接生成 |
| `extractor_version` | string | 是 | 特征提取器版本，如 `opencv_kmeans_v1` |
| `feature_confidence` | number | 是 | 0-1，表示自动提取稳定性 |
| `needs_manual_review` | boolean | 是 | 是否建议人工复核 |
| `feature_source` | string | 是 | `auto_color_extract` / `manual_seed` / `manual_corrected` |
| `created_at` | datetime | 是 | 创建时间 |
| `updated_at` | datetime | 否 | 最近修正时间 |

`dominant_palette` 子结构：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `color_family` | enum | 是 | 该颜色所属色系 |
| `color_name` | string | 是 | 展示用颜色名 |
| `rgb` | array | 是 | RGB |
| `ratio` | number | 是 | 在款式图中的占比，0-1 |

示例：

```json
{
  "visual_feature_id": "NVF001",
  "style_id": "STYLE001",
  "primary_color_family": "pink",
  "primary_color_name": "裸粉",
  "primary_color_rgb": [220, 164, 175],
  "dominant_palette": [
    {
      "color_family": "pink",
      "color_name": "裸粉",
      "rgb": [220, 164, 175],
      "ratio": 0.58
    },
    {
      "color_family": "white",
      "color_name": "奶白",
      "rgb": [238, 229, 220],
      "ratio": 0.24
    }
  ],
  "color_temperature": "warm",
  "brightness_level": "medium",
  "saturation_level": "medium",
  "contrast_level": "low",
  "color_vector": [220, 164, 175, 0.58, 238, 229, 220, 0.24],
  "extractor_version": "opencv_kmeans_v1",
  "feature_confidence": 0.78,
  "needs_manual_review": false,
  "feature_source": "auto_color_extract",
  "created_at": "2026-05-09T14:01:00+08:00",
  "updated_at": null
}
```

### 4.6 RecommendationSnapshot

一次推荐结果快照。第一轮和第二轮都写入该表，便于页面展示与调试。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `snapshot_id` | string | 是 | 推荐快照 ID，如 `RS001` |
| `session_id` | string | 是 | 所属会话 |
| `round_no` | number | 是 | `1` 第一轮，`2` 第二轮 |
| `strategy` | string | 是 | `reference_hand_match` / `session_visual_similarity_rerank` |
| `items` | array | 是 | 推荐条目列表 |
| `created_at` | datetime | 是 | 创建时间 |

### 4.7 RecommendationItem

`RecommendationSnapshot.items` 中的嵌套结构。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `rank` | number | 是 | 推荐排序 |
| `style_id` | string | 是 | 款式 ID |
| `total_score` | number | 是 | 综合推荐分，0-100 |
| `hand_shape_score` | number | 是 | 手型匹配分 |
| `skin_tone_score` | number | 是 | 肤色匹配分 |
| `visual_similarity_score` | number | 否 | 第二轮使用，候选款与本次视觉偏好的相似度 |
| `color_preference_score` | number | 否 | 第二轮调试字段，可由色系、主色和调色板相似度组成 |
| `behavior_boost_score` | number | 否 | 第二轮调试字段，默认只做弱加权或不参与最终分 |
| `primary_color_family` | enum | 否 | 推荐展示和调试用 |
| `primary_color_name` | string | 否 | 推荐展示和调试用 |
| `color_temperature` | enum | 否 | 推荐展示和调试用 |
| `reason_tags` | array | 是 | 推荐理由标签 |
| `reason_text` | string | 是 | 页面展示推荐理由 |

示例：

```json
{
  "rank": 1,
  "style_id": "STYLE001",
  "total_score": 92.5,
  "hand_shape_score": 95,
  "skin_tone_score": 90,
  "visual_similarity_score": 0,
  "color_preference_score": 0,
  "behavior_boost_score": 0,
  "primary_color_family": "pink",
  "primary_color_name": "裸粉",
  "color_temperature": "warm",
  "reason_tags": ["手型接近", "肤色接近"],
  "reason_text": "这款参考图中的手型与肤色都与你较接近，优先推荐试戴。"
}
```

### 4.8 SessionBehaviorEvent

记录本次 session 内用户对推荐款式的行为。该表只服务于当前 session 的二轮推荐，不用于长期用户画像。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `event_id` | string | 是 | 行为事件 ID，如 `SBE001` |
| `session_id` | string | 是 | 所属会话 |
| `style_id` | string | 是 | 款式 ID |
| `event_type` | enum | 是 | 见 `BehaviorType` |
| `source_snapshot_id` | string | 否 | 行为发生在哪次推荐快照中 |
| `event_weight` | number | 是 | 点击 1，发起试戴 3，试戴成功 4 |
| `created_at` | datetime | 是 | 行为时间 |

### 4.9 SessionPreferenceProfile

由本次 session 行为临时计算出来的偏好画像。重新上传手图后失效。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `preference_id` | string | 是 | 偏好画像 ID，如 `SPP001` |
| `session_id` | string | 是 | 所属会话 |
| `preferred_color_families` | array | 是 | 偏好的稳定色系及权重 |
| `preferred_primary_colors` | array | 是 | 偏好的主色名称及权重 |
| `preferred_color_temperatures` | array | 是 | 偏好的冷暖色及权重 |
| `preferred_brightness_levels` | array | 否 | 偏好的明暗等级及权重 |
| `preferred_saturation_levels` | array | 否 | 偏好的饱和度等级及权重 |
| `preference_color_vector` | array | 是 | 按行为权重聚合出的颜色偏好向量 |
| `positive_style_ids` | array | 是 | 产生正反馈的款式 |
| `source_event_ids` | array | 是 | 参与计算的行为事件 |
| `created_at` | datetime | 是 | 创建时间 |

示例：

```json
{
  "preference_id": "SPP001",
  "session_id": "S001",
  "preferred_color_families": [
    {"color_family": "pink", "weight": 4},
    {"color_family": "nude", "weight": 1}
  ],
  "preferred_primary_colors": [
    {"primary_color_name": "裸粉", "weight": 4},
    {"primary_color_name": "豆沙", "weight": 1}
  ],
  "preferred_color_temperatures": [
    {"color_temperature": "warm", "weight": 5}
  ],
  "preferred_brightness_levels": [
    {"brightness_level": "medium", "weight": 5}
  ],
  "preferred_saturation_levels": [
    {"saturation_level": "medium", "weight": 5}
  ],
  "preference_color_vector": [218, 160, 172, 0.64, 236, 224, 216, 0.21],
  "positive_style_ids": ["STYLE001", "STYLE003"],
  "source_event_ids": ["SBE001", "SBE002"],
  "created_at": "2026-05-09T14:05:00+08:00"
}
```

### 4.10 TryOnJob

记录试戴任务。V1 初始阶段先不调用真实 ComfyUI API，直接使用原图或占位图作为 `result_image_url`；后续接入 ComfyUI 后复用同一张表。

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `try_on_job_id` | string | 是 | 试戴任务 ID，如 `TOJ001` |
| `session_id` | string | 是 | 所属会话 |
| `style_id` | string | 是 | 被试戴款式 |
| `user_hand_image_id` | string | 是 | 用户上传手图 |
| `nail_image_url` | string | 是 | 美甲款式图 |
| `status` | string | 是 | `pending` / `running` / `success` / `failed` |
| `comfyui_prompt_id` | string | 否 | ComfyUI 返回的任务 ID |
| `request_payload` | object | 否 | 发给 ComfyUI 的请求摘要 |
| `result_image_url` | string | 否 | 试戴结果图 |
| `error_message` | string | 否 | 失败原因 |
| `created_at` | datetime | 是 | 创建时间 |
| `completed_at` | datetime | 否 | 完成时间 |

## 5. 推荐评分规则

### 5.1 第一轮推荐：参考手画像匹配

第一轮推荐只使用用户手画像与美甲库参考手画像。`confidence` 字段仅用于展示和调试，不参与 V1 初始推荐排序。

```text
round1_score =
  hand_shape_score * 0.50
+ skin_tone_score * 0.50
```

分数范围为 0-100。

### 5.2 手型匹配分

| 匹配关系 | 分数 |
| --- | ---: |
| 完全相同 | 100 |
| 相近类型 | 70 |
| 差异明显 | 35 |
| 任一方 unknown | 50 |

相近类型可先用静态规则定义，例如：

```text
slender_long <-> narrow_palm
short_wide <-> square_palm
```

### 5.3 肤色匹配分

| 匹配关系 | 分数 |
| --- | ---: |
| 完全相同 | 100 |
| undertone 相同且肤色相邻 | 75 |
| undertone 不同但明度相近 | 55 |
| 差异明显 | 30 |
| 任一方 unknown | 50 |

### 5.4 第二轮推荐：本次行为驱动的视觉相似款推荐

第二轮推荐在第一轮基础上加入本次 session 的视觉偏好。行为不直接决定某个已点击款置顶，而是用于学习用户喜欢的视觉特征，再去美甲库中寻找相似款。

```text
round2_score =
  round1_score * 0.40
+ visual_similarity_score * 0.50
+ behavior_boost_score * 0.10
```

其中 `behavior_boost_score` 默认只做弱加权或调试展示。若希望第二轮更多展示相似新款，可以对 `positive_style_ids` 中已点击 / 已试戴款设置轻微降权，而不是加权。

行为权重：

| 行为 | 权重 |
| --- | ---: |
| click | 1 |
| try_on_start | 3 |
| try_on_success | 4 |

`visual_similarity_score` 来自候选款与 `SessionPreferenceProfile` 的视觉相似度，建议由以下部分组成：

```text
visual_similarity_score =
  color_family_score * 0.30
+ palette_vector_score * 0.35
+ color_temperature_score * 0.15
+ brightness_score * 0.10
+ saturation_score * 0.10
```

字段解释：

| 分项 | 含义 |
| --- | --- |
| `color_family_score` | 候选款主色系是否命中用户偏好色系 |
| `palette_vector_score` | 候选款 `color_vector` 与偏好向量的距离相似度 |
| `color_temperature_score` | 冷暖色是否接近 |
| `brightness_score` | 明暗等级是否接近 |
| `saturation_score` | 饱和度等级是否接近 |

示例：

```text
用户点击 STYLE001：粉色系 / 裸粉 / 暖色 / 中明度 / 中饱和
用户成功试戴 STYLE003：裸色系 / 豆沙 / 暖色 / 中明度 / 低饱和
=> pink、nude、warm、中明度 获得较高权重
=> 第二轮推荐优先上升“相似色系 + 相似调色板”的未试戴款
```

## 6. 推荐文件结构

建议 V1 初始阶段使用 JSON 存储，延续 V0 Demo 的轻量实现方式。

```text
demo_v1/
  data/
    hand_shape_definitions.json
    skin_tone_definitions.json
    undertone_definitions.json
    color_feature_rules.json
    nail_styles_v1.json
    reference_hand_profiles.json
    nail_visual_features.json
  uploads/
    .gitkeep
  outputs/
    try_on_sessions.json
    user_hand_images.json
    user_hand_profiles.json
    recommendation_snapshots.json
    session_behavior_events.json
    session_preference_profiles.json
    try_on_jobs.json
```

其中：

- `data/` 存放美甲库基础数据、预处理好的参考手画像，以及可配置识别规则。
- `uploads/` 存放用户上传手图。
- `outputs/` 存放每次 Demo 运行产生的 session、推荐、行为、试戴结果。

## 7. 实现说明

手型与肤色识别建议：

```text
MediaPipe Hands
+ OpenCV / PIL
+ 规则映射
```

美甲视觉特征识别建议：

```text
PIL / OpenCV 读取图片
-> KMeans 或颜色直方图提取 2-4 个 dominant_palette
-> RGB 转 HSV / Lab
-> 根据 Hue / 明度 / 饱和度映射 primary_color_family、color_temperature、brightness_level、saturation_level
-> 生成 color_vector
-> 写入 NailVisualFeature
```

V1 Demo 可接受以下过渡方式：

- 用户手图画像优先尝试代码识别，失败时允许 mock 结果。
- 美甲库参考手画像可以先预处理生成，也可以先人工 mock。
- 美甲视觉特征优先代码自动提取，必要时人工修正。
- `hand_shape_definitions.json`、`skin_tone_definitions.json`、`undertone_definitions.json` 用于维护手型、肤色、冷暖调识别规则，避免阈值散落在识别代码中。
- `color_feature_rules.json` 用于维护色系、冷暖色、明暗和饱和度的映射规则，避免规则散落在推荐代码中。
