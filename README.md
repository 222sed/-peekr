# Peekr 猫咪状态监测

Peekr 使用一台手机拍摄猫咪，把图片发送到电脑分析，再在另一个小程序中显示猫咪当前状态。

目前支持的状态：

- 睡眠中
- 玩耍中
- 觅食中
- 发呆中
- 未检测到猫

> 本教程面向没有编程经验的 Windows 用户。按顺序操作即可。

---

## 一、运行前需要准备

### 1. 一台 Windows 电脑

电脑运行期间不能关机，也不要关闭后面打开的两个黑色终端窗口。

### 2. 一台用作摄像头的手机

采集端必须在真机上运行，因为电脑模拟器不能正常调用手机摄像头。

### 3. 安装 Python

打开下面的网站：

https://www.python.org/downloads/windows/

推荐安装 Python 3.11。

安装时务必勾选：

```text
Add Python to PATH
```

然后点击 `Install Now`。

### 4. 安装微信开发者工具

下载地址：

https://developers.weixin.qq.com/miniprogram/dev/devtools/download.html

安装后使用微信扫码登录。

### 5. 注册 ngrok

打开：

https://dashboard.ngrok.com/signup

注册并登录。ngrok 用于让手机在不同网络下也能访问电脑上的服务。

---

## 二、下载 Peekr

打开项目页面：

https://github.com/222sed/-peekr

依次点击：

```text
Code → Download ZIP
```

下载完成后：

1. 解压 ZIP；
2. 把解压后的文件夹改名为 `peekr`；
3. 把 `peekr` 文件夹放到桌面。

最终目录应类似：

```text
C:\Users\你的用户名\Desktop\peekr
```

---

## 三、安装服务端

### 1. 打开终端

按键盘上的：

```text
Win + R
```

输入：

```text
cmd
```

点击“确定”。

### 2. 进入服务端目录

复制下面这条命令，把其中的 `你的用户名` 换成电脑用户名：

```bat
cd C:\Users\你的用户名\Desktop\peekr\server
```

按回车。

### 3. 安装依赖

输入：

```bat
python -m pip install -r requirements.txt
```

第一次安装需要几分钟。看到安装完成后再继续。

### 4. 启动服务端

输入：

```bat
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

看到下面的文字说明启动成功：

```text
Uvicorn running on http://0.0.0.0:8000
Application startup complete.
```

这个终端窗口必须保持打开。

### 5. 检查服务端

在电脑浏览器打开：

```text
http://localhost:8000/api/health
```

看到以下内容说明正常：

```json
{"ok":true}
```

> 第一次分析图片时会自动下载 YOLO 和动物姿态模型，总大小约 120MB，请保持网络连接。

---

## 四、启动 ngrok 公网连接

### 1. 下载 ngrok

打开：

https://download.ngrok.com/windows

下载 Windows 版本，解压后会得到：

```text
ngrok.exe
```

为了方便，建议创建下面的文件夹，并把 `ngrok.exe` 放进去：

```text
C:\ngrok
```

### 2. 添加账号密钥

登录 ngrok 后打开：

https://dashboard.ngrok.com/get-started/your-authtoken

网页会显示一条类似下面的命令：

```bat
ngrok config add-authtoken 你的密钥
```

按 `Win + R`，输入 `cmd`，打开第二个终端，然后输入：

```bat
C:\ngrok\ngrok.exe config add-authtoken 你的密钥
```

密钥只需要配置一次，不要把密钥发送给其他人。

### 3. 启动公网连接

继续在第二个终端输入：

```bat
C:\ngrok\ngrok.exe http 8000
```

看到类似下面的地址：

```text
Forwarding  https://xxxx.ngrok-free.app -> http://localhost:8000
```

复制其中以 `https://` 开头的地址。

第二个终端窗口也必须保持打开。

### 4. 测试公网地址

假设获得的地址是：

```text
https://xxxx.ngrok-free.app
```

在浏览器打开：

```text
https://xxxx.ngrok-free.app/api/health
```

看到以下内容说明公网连接正常：

```json
{"ok":true}
```

---

## 五、设置小程序服务器地址

两个小程序必须使用同一个 ngrok 地址。

### 1. 修改采集端

用记事本打开：

```text
peekr\miniapp-capture\app.js
```

把 `serverUrl` 改成自己的 ngrok 地址，例如：

```javascript
App({
  globalData: {
    serverUrl: 'https://xxxx.ngrok-free.app',
  },
})
```

保存文件。

### 2. 修改展示端

用记事本打开：

```text
peekr\miniapp-display\app.js
```

填入完全相同的地址：

```javascript
App({
  globalData: {
    serverUrl: 'https://xxxx.ngrok-free.app',
  },
})
```

保存文件。

> 地址末尾不要加 `/`，也不要填写 `/api/health`。

---

## 六、导入采集端小程序

1. 打开微信开发者工具；
2. 点击“导入项目”；
3. 选择：

```text
peekr\miniapp-capture
```

4. 填写自己的 AppID，没有 AppID 时可选择测试号；
5. 进入项目后，打开“详情 → 本地设置”；
6. 勾选“不校验合法域名、web-view、TLS 版本以及 HTTPS 证书”；
7. 点击顶部“真机调试”；
8. 用作为摄像头的手机扫码；
9. 允许摄像头权限；
10. 点击“开始监控”。

手机上出现：

```text
已上传 1 帧
```

说明采集端正常。

电脑服务端终端也会不断出现：

```text
POST /api/frame 200 OK
```

---

## 七、导入展示端小程序

展示端可以直接在电脑模拟器中运行，不需要第二台手机。

1. 再打开一个微信开发者工具窗口；
2. 点击“导入项目”；
3. 选择：

```text
peekr\miniapp-display
```

4. 可使用与采集端相同的 AppID；
5. 打开“详情 → 本地设置”；
6. 勾选“不校验合法域名”；
7. 点击“编译”。

等待约 5 秒，页面应该显示：

```text
睡眠中 / 玩耍中 / 觅食中 / 发呆中
```

采集端和展示端不需要登录同一个微信。它们通过同一个服务器地址共享数据。

---

## 八、以后每次测试怎么启动

以后不需要重新安装依赖，只需要打开两个终端。

### 第一个终端：启动服务端

```bat
cd C:\Users\你的用户名\Desktop\peekr\server
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 第二个终端：启动 ngrok

```bat
C:\ngrok\ngrok.exe http 8000
```

然后：

1. 检查 ngrok 地址是否变化；
2. 如果地址变化，修改两个 `app.js`；
3. 在微信开发者工具中重新点击“编译”或“真机调试”。

---

## 九、常见问题

### 手机显示“上传失败”

依次检查：

1. 服务端终端是否保持打开；
2. ngrok 终端是否保持打开；
3. `ngrok地址/api/health` 能否访问；
4. `miniapp-capture/app.js` 地址是否正确；
5. 是否勾选“不校验合法域名”；
6. 修改代码后是否重新生成真机调试二维码。

### 展示端不更新

检查：

1. `miniapp-display/app.js` 是否与采集端使用相同地址；
2. 展示端是否勾选“不校验合法域名”；
3. 点击“编译”后等待 5 秒；
4. 浏览器访问：

```text
你的ngrok地址/api/status
```

如果能看到 `state`，说明服务器有状态数据。

### 一直显示“未检测到猫”

- 确保猫完整出现在画面中；
- 保持光线充足；
- 摄像头不要离猫太远；
- 避免镜头抖动或严重模糊；
- 第一次识别需要等待模型下载完成。

### 提示端口 8000 被占用

说明服务端可能已经启动，不要重复启动。

可以先在浏览器打开：

```text
http://localhost:8000/api/health
```

如果能看到 `{"ok":true}`，直接使用现有服务即可。

### ngrok 提示 endpoint 已经在线

说明 ngrok 已经在另一个终端运行，不需要再次启动。

---

## 十、重要说明

- 电脑关机后，采集端和展示端都会失去连接；
- 免费 ngrok 地址可能在重新启动后发生变化；
- 这个项目目前适合开发测试；
- 正式发布微信小程序需要自己的备案 HTTPS 域名和服务器；
- 请勿把 ngrok 密钥、微信 AppSecret 或其他账号密码提交到 GitHub。
