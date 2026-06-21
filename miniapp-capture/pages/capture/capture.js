const SERVER_URL = getApp().globalData.serverUrl
const CAPTURE_INTERVAL_MS = 3000

Page({
  data: {
    running: false,
    statusText: '点击开始监控',
    statusType: 'idle',
    frameCount: 0,
    battery: 100,
    lowBattery: false,
    previewSrc: '',
  },

  _timer: null,
  _cameraCtx: null,
  _retryCount: 0,

  onLoad() {
    wx.setKeepScreenOn({ keepScreenOn: true })
    this._checkBattery()
    setInterval(() => this._checkBattery(), 60000)
  },

  onUnload() {
    this._stopCapture()
  },

  onStartStop() {
    if (this.data.running) {
      this._stopCapture()
    } else {
      this._startCapture()
    }
  },

  _startCapture() {
    this._cameraCtx = wx.createCameraContext()
    this.setData({ running: true, statusText: '监控中…', statusType: 'ok', frameCount: 0 })
    this._timer = setInterval(() => this._tick(), CAPTURE_INTERVAL_MS)
    this._tick()
  },

  _stopCapture() {
    if (this._timer) {
      clearInterval(this._timer)
      this._timer = null
    }
    this.setData({ running: false, statusText: '已停止', statusType: 'idle', previewSrc: '' })
  },

  _tick() {
    if (!this._cameraCtx) return
    this.setData({ statusText: '截图中…', statusType: 'uploading' })

    this._cameraCtx.takePhoto({
      quality: 'normal',
      success: (res) => {
        wx.compressImage({
          src: res.tempImagePath,
          quality: 60,
          success: (compressed) => this._upload(compressed.tempFilePath),
          fail: () => this._upload(res.tempImagePath),
        })
      },
      fail: (err) => {
        console.error('[capture] takePhoto failed', err)
        this.setData({ statusText: '截图失败，重试中…', statusType: 'error' })
      },
    })
  },

  _upload(filePath) {
    wx.uploadFile({
      url: `${SERVER_URL}/api/frame`,
      filePath,
      name: 'file',
      header: {
        'ngrok-skip-browser-warning': 'true',
      },
      success: (res) => {
        this._retryCount = 0
        const count = this.data.frameCount + 1
        try {
          const data = JSON.parse(res.data)
          const stateLabel = data.state || ''
          this.setData({
            statusText: `${stateLabel ? stateLabel + ' · ' : ''}已上传 ${count} 帧`,
            statusType: 'ok',
            frameCount: count,
            previewSrc: data.preview || '',
          })
        } catch (e) {
          this.setData({ statusText: `已上传 ${count} 帧`, statusType: 'ok', frameCount: count })
        }
      },
      fail: (err) => {
        this._retryCount++
        console.error('[capture] upload failed', err)
        this.setData({
          statusText: `上传失败 (${this._retryCount})，检查服务端连接`,
          statusType: 'error',
        })
      },
    })
  },

  _checkBattery() {
    wx.getBatteryInfo({
      success: (res) => {
        this.setData({
          battery: res.level,
          lowBattery: res.level < 20 && !res.isCharging,
        })
      },
    })
  },
})
