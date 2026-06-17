# Peekr — 阶段一启动指南

## 项目结构

```
peekr/
├── server/              # FastAPI 服务端
├── miniapp-capture/     # 采集端小程序（手机摄像头）
└── miniapp-display/     # 展示端小程序（状态展示）
```

---

## 1. 启动服务端

### 环境要求
- Python 3.11+
- pip

### 安装依赖

```bash
cd server
pip install -r requirements.txt
```

首次运行会自动下载 YOLOv8n 权重（约 6MB），需要网络连接。

### 启动

```bash
uvicorn main:app --reload
```

服务运行在 `http://localhost:8000`

验证是否正常：
```bash
curl http://localhost:8000/api/health
# 返回 {"ok": true}
```

---

## 2. 启动采集端小程序

1. 打开微信开发者工具，导入 `miniapp-capture/` 目录
2. 填入你的 AppID（或使用测试号）
3. 在 `app.js` 中确认 `serverUrl` 为 `http://localhost:8000`
4. 开发者工具中勾选：**不校验合法域名**（设置 → 项目设置）
5. 点击「真机调试」扫码，在手机上测试（模拟器无法调用摄像头）
6. 点击「开始监控」

---

## 3. 启动展示端小程序

1. 打开微信开发者工具，导入 `miniapp-display/` 目录
2. 填入你的 AppID
3. 在 `app.js` 中确认 `serverUrl` 为 `http://localhost:8000`
4. 开发者工具中勾选：**不校验合法域名**
5. 模拟器即可查看状态展示

---

## 4. 验证链路

```
手机采集端 → POST /api/frame → 服务端分析 → GET /api/status → 展示端刷新
```

服务端终端会打印每帧的分析结果：
```
[frame] state=sleep  motion=2.1  compact=0.812
[frame] state=play   motion=45.3  compact=0.541
```

展示端每 5 秒自动刷新状态。

---

## 5. API 说明

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/frame` | POST | 上传图片帧，返回分析结果 |
| `/api/status` | GET | 获取当前猫咪状态 |
| `/api/health` | GET | 健康检查 |

`/api/status` 返回格式：
```json
{
  "state": "sleep",
  "confidence": 0.95,
  "updated_at": 1717459200.0
}
```

状态值：`sleep` / `play` / `food` / `dream` / `unknown`

---

## 6. 常见问题

**Q：小程序上传失败，提示域名不合法**
A：开发者工具 → 设置 → 项目设置 → 勾选「不校验合法域名、web-view、TLS版本及HTTPS证书」

**Q：服务端报 `No module named 'ultralytics'`**
A：确认在 `server/` 目录下执行了 `pip install -r requirements.txt`

**Q：摄像头没有权限**
A：小程序需要在真机上授权摄像头权限，模拟器不支持

**Q：检测结果一直是 unknown**
A：YOLOv8 在光线不足时容易漏检，确保摄像头画面中猫咪清晰可见
