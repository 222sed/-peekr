# Peekr Design System

## Direction

Peekr 的展示端采用 Modern Editorial Pet Companion：猫咪承担陪伴感，数据承担可信度。界面应像克制的生活方式产品，而不是儿童宠物玩具、监控后台或通用数据仪表盘。

## Homepage Composition

首页首屏固定为四层：身份与设备状态、当前状态与观察时间、圆弧今日概况中的中央动态猫咪、进食/休息/活动三项记录条。圆弧是品牌化的“状态轨迹”，不是健康分；没有参考区间时，记录条必须明确写出“暂无参考”或“记录不足”。

次级内容（时间轴、异常说明、自定义入口、设置）位于首屏主结构之后，不与中央猫咪争夺视觉权重。

## Tokens

- Background: `#F7F5F0`
- Surface: `#FFFFFF`
- Primary text: `#222220`
- Secondary text: `#686963`
- Divider: `#E4E1DA`
- Brand / attention: `#F05F65`
- Rest: `#9B97B0`
- Activity: `#5DB8A8`
- Feeding: `#E8A85A`
- Low activity: `#7C9CA2`

Use the system Chinese sans-serif stack. Use 4px/8px spacing logic (8rpx base at the 375px reference width). Touchable controls are at least 88rpx high or wide. Ordinary content relies on whitespace and dividers; reserve white panels for information that needs to read as one unit.

## Character and Motion

Reuse the existing flat layered SVG cat. Sleep is slow, activity is quicker, feeding uses a small head dip, and uncertain states use a restrained idle pose. Offline, stale, server-error and waiting states stop the live animation and reduce emphasis. Respect reduced-motion settings.

Do not add paper-doll joints, clay or plush materials, 3D rendering, inner shadows, large gradients, glass effects, decorative geometry or generic icon tiles.

## Data Language

- Sleep is “推测休息”, never confirmed physiological sleep.
- Sleep/activity percentages are “已记录时段占比”, not all-day duration.
- Feeding is a recorded event count. Until a validated reference exists, do not draw a progress fill or label it low/normal/high.
- Observation freshness uses the capture timestamp. Records older than 30 minutes are not presented as live.
- Offline, server failure, not-found and demo data remain distinct in both copy and styling.

## Responsive and Accessibility

Design from a 375px mobile width, compress vertical rhythm on short screens, avoid fixed page heights, and preserve the WeChat navigation and bottom safe area. State is always expressed with text as well as color. Auxiliary copy remains at least 24rpx with sufficient contrast. Interactive controls need visible pressed feedback and descriptive accessibility labels.
