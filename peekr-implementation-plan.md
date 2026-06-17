# Peekr 产品与落地实现文档

---

## 一、产品概念

### Peekr 核心理念

> 一眼知状态，一眼就安心。

Peekr 将复杂监控转化为轻量状态版，让用户无需打开实时画面，也能快速掌握猫咪当前情况。

产品通过像素化猫咪动态、状态标签与极简进度系统，重新设计人与宠物之间的远程连接方式。

相比传统宠物监控强调「持续查看」，Peekr 更强调：

- 快速感知
- 降低焦虑
- 轻量陪伴
- 默认隐私保护

让「查看宠物」变成一种自然、轻松的日常行为。

---

### 设计目标

**01｜降低信息密度**

传统监控产品通常需要用户长时间查看视频、主动解读行为、持续确认状态，信息复杂且容易产生焦虑。

Peekr 将复杂行为转译为：状态词 / 动态动画 / 进度条 / 轻提醒，通过更低的信息密度帮助用户快速建立安全感。

**02｜快速掌握情况**

产品将用户最关心的信息优先整合：饮水状态 / 猫粮余量 / 睡眠情况 / 活跃状态。无需进入 App，仅通过桌面小组件即可「一眼获取」，让用户像查看天气一样自然感知猫咪状态。

**03｜弱化监控感**

Peekr 不强调真实摄像头画面。系统默认不展示真实家庭环境、不展示监控视角、不制造「被观察感」，而是通过像素猫动画、插画化状态、抽象行为反馈，营造更加温和的陪伴体验。

---

### 核心状态系统

| 状态 | 描述 | 标签 |
|------|------|------|
| 睡眠中 | 蜷缩入眠，呼吸绵长 | 💤 Sleeping |
| 玩耍中 | 扑打玩具，精力充沛 | 🎾 Playing |
| 觅食中 | 低头进食，专注享用 | 🍚 Eating |
| 发呆中 | 凝视远方，思绪飘散 | ✨ Daydreaming |

---

## 二、技术方案

### 整体架构

```
手机/平板（采集端小程序）
    │  每 5 秒截图 + 上传
    ▼
服务端（FastAPI + Redis）
    │  AI 分析 → 状态数据
    ▼
用户端（展示小程序）
    │  轮询/SSE 获取状态
    ▼
桌面小组件 · 状态栏胶囊
```

### 采集方式：定时截图上传（方案 C）

不使用视频流，小程序每 5 秒截图后直接 HTTP POST 到服务端。对 Peekr「状态感知」场景，5 秒延迟完全可接受，省去推流基础设施，复杂度极低。

---

## 三、落地实现计划

### 项目概览

- **目标**：手机/平板作为摄像头 → 定时截图上传 → 服务端 AI 分析 → 小程序展示猫咪状态
- **周期**：约 6-8 周（两人小团队）

---

### 阶段一：基础链路打通（第 1-2 周）

**目标：截图能上传，状态能显示，端到端跑通。**

#### 1.1 摄像头端（小程序 A — 采集端）

功能清单：

- 打开摄像头预览（`camera` 组件）
- 每 5 秒自动截图（`wx.createCameraContext`）
- 压缩图片到 300KB 以内（`wx.compressImage`）
- POST 上传到服务端 `/api/frame`
- 保持屏幕常亮（`wx.setKeepScreenOn`）
- 显示当前上传状态 + 电量提醒

关键代码逻辑：

```js
// 采集端核心循环
setInterval(async () => {
  const frame = await captureFrame()         // 截图
  const compressed = await compress(frame)   // 压缩
  await upload('/api/frame', compressed)     // 上传
}, 5000)
```

#### 1.2 服务端（FastAPI）

接口设计：

```
POST /api/frame     ← 接收图片，丢进分析队列
GET  /api/status    ← 返回最新状态（轮询用）
GET  /api/stream    ← SSE 推状态变更（第二阶段再做）
```

第一周先用同步处理，不用队列：

```python
@app.post("/api/frame")
async def receive_frame(file: UploadFile):
    img = await file.read()
    state = analyze(img)          # 直接跑分析
    redis.set("cat:state", state) # 存 Redis
    return {"ok": True}
```

#### 1.3 展示端（小程序 B — 用户端）

功能清单：

- 首页显示猫咪当前状态（动画 + 状态词）
- 每 5 秒轮询 `/api/status`
- 四种状态切换动画（复用 Peekr 设计系统）
- 进度条展示饮水 / 猫粮 / 睡眠 / 活跃

---

### 阶段二：AI 分析核心（第 2-4 周）

**目标：分析准确率达到 85% 以上，覆盖四种状态。**

#### 2.1 检测层 — 找到猫

用 YOLOv8n（最轻量版本），COCO 权重自带 `cat` 类，零训练直接用：

```python
from ultralytics import YOLO

model = YOLO("yolov8n.pt")

def detect_cat(img):
    results = model(img, classes=[15])  # 15 = cat in COCO
    if not results[0].boxes:
        return None  # 没检测到猫
    box = results[0].boxes[0].xyxy[0]  # 取置信度最高的
    return box
```

#### 2.2 特征提取层

三个特征并行提取：

**① 运动量**（最可靠，不需要 AI）

```python
def motion_score(curr_box, prev_box):
    cx1, cy1 = center(prev_box)
    cx2, cy2 = center(curr_box)
    return ((cx2-cx1)**2 + (cy2-cy1)**2) ** 0.5
```

**② 姿态紧缩度**（判断蜷缩 vs 站立）

```python
def compactness(box):
    # BoundingBox 宽高比接近 1:1 → 蜷缩
    # 宽高比差异大 → 站立/伸展
    w = box[2] - box[0]
    h = box[3] - box[1]
    return min(w,h) / max(w,h)
```

**③ 头部位置**（判断低头觅食）

```python
def head_position(pose_keypoints):
    head_y = pose_keypoints['head'][1]
    body_y = pose_keypoints['body'][1]
    return head_y > body_y + threshold
```

#### 2.3 状态分类规则

```python
def classify_state(motion, compactness, head_down, consecutive_still):

    # 睡眠：长时间不动 + 蜷缩
    if motion < 5 and consecutive_still > 12 and compactness > 0.7:
        return "sleep"

    # 觅食：头部低垂
    if head_down and motion < 20:
        return "food"

    # 玩耍：快速移动
    if motion > 30:
        return "play"

    # 发呆：轻微移动 + 坐姿
    if motion < 15 and compactness < 0.6:
        return "dream"

    # 兜底：沿用上一个状态
    return last_state
```

#### 2.4 状态平滑（防跳变）

状态不直接切换，用滑动窗口投票：

```python
from collections import deque, Counter

state_buffer = deque(maxlen=6)  # 保留最近 6 次（约 30 秒）

def smooth_state(new_state):
    state_buffer.append(new_state)
    counts = Counter(state_buffer)
    return counts.most_common(1)[0][0]  # 超过半数才切换
```

---

### 阶段三：推送与体验优化（第 4-6 周）

#### 3.1 轮询 → SSE 升级

服务端添加 SSE 端点：

```python
@app.get("/api/stream")
async def state_stream():
    async def generator():
        last = None
        while True:
            state = redis.get("cat:state")
            if state != last:
                yield f"data: {state}\n\n"  # 只推变更
                last = state
            await asyncio.sleep(1)
    return EventSourceResponse(generator())
```

小程序用 `RequestTask` + `enableChunked` 接收：

```js
const task = wx.request({
  url: 'https://yourserver/api/stream',
  enableChunked: true,
  success() {},
})
task.onChunkReceived(({ data }) => {
  const state = parseSSE(data)
  updateUI(state)
})
```

#### 3.2 离线兜底

- 超过 60 秒没收到新帧 → 显示「连接中断」状态
- 超过 10 分钟 → 推送通知「摄像头可能断线了」

#### 3.3 夜间模式

- 采集端检测环境亮度（分析图片平均像素值）
- 亮度低于阈值 → 提示「环境太暗，识别准确率下降」
- 可选：切换黑白模式，提升低光对比度

---

### 阶段四：数据积累 + 模型提升（第 6-8 周）

当规则分类积累了足够数据后，升级为轻量模型：

- **数据收集**：服务端记录每帧特征 + 用户反馈的正确状态
- **标注工具**：简单后台页面，显示截图让用户点选正确状态
- **训练**：MobileNetV3 fine-tune，约 500 张/类就够
- **部署**：替换 `classify_state` 函数，其余不变

---

## 四、技术栈汇总

| 层 | 技术 | 说明 |
|----|------|------|
| 采集端 | 微信小程序 | camera + setInterval |
| 展示端 | 微信小程序 | 复用 Peekr 设计系统 |
| 服务端 | FastAPI + Python 3.11 | 推理性能好 |
| AI 推理 | YOLOv8n + 规则分类 | 无需 GPU，CPU 可跑 |
| 状态存储 | Redis | TTL 自动过期 |
| 推送 | SSE（阶段三升级） | 轮询过渡 |
| 部署 | Docker + 单台 2核4G云服务器 | 月费约 50-80 元 |

---

## 五、里程碑

| 周次 | 目标 |
|------|------|
| Week 1 | 截图上传链路打通，服务端收到图片 |
| Week 2 | YOLOv8 检测猫，返回 BoundingBox |
| Week 3 | 四种状态规则分类跑通，小程序能看到状态 |
| Week 4 | 状态平滑 + 准确率测试，准确率 > 80% |
| Week 5 | SSE 推送替换轮询，展示端体验优化 |
| Week 6 | 夜间/断线兜底，稳定性测试 |
| Week 7-8 | 数据收集 + 模型微调（可选） |

---

## 六、最小可验证版本（第 2 周末）

只做这三件事，能端到端跑通就算成功：

1. 手机小程序拍照 → 上传到服务器
2. 服务器用 YOLOv8 判断「有没有猫」+ 简单运动量算一个状态
3. 展示端小程序每 5 秒拉接口，显示当前状态词

代码量约 500 行，一个人一周能完成。

---

## 七、主要风险点

| 风险 | 应对 |
|------|------|
| 训练数据少 | 前期多用规则 + 运动向量，减少对姿态模型依赖 |
| 夜间检测率低 | 增加「不确定」兜底状态，提示用户补光 |
| 手机续航 | 插电 + 常亮 + 低亮度模式，小程序内提示 |
| 状态跳变 | 滑动窗口投票，半数以上才切换 |

---

*Peekr · 2026 · 陪伴，而非监控*
