const SERVER_URL = getApp().globalData.serverUrl
const CAPTURE_INTERVAL_MS = 3000
const UPLOAD_TIMEOUT_MS = 25000
const RETRY_DELAYS_MS = [3000, 6000, 12000, 20000]
const FEEDING_ZONE_STORAGE_KEY = 'peekr_feeding_zone_v1'
const DEVICE_ID_STORAGE_KEY = 'peekr_capture_device_id_v1'
const MIN_ZONE_SIZE = 0.12

const DEFAULT_FEEDING_ZONE = {
  x: 0.28,
  y: 0.62,
  width: 0.44,
  height: 0.22,
  version: 1,
}

const STATE_LABELS = {
  sleep: '睡眠中',
  play: '玩耍中',
  food: '进食中',
  dream: '发呆中',
  unknown: '侦测中',
}

const QUALITY_MESSAGES = {
  too_dark: '画面过暗，请增加照明',
  too_bright: '画面过亮，请避开强光',
  low_contrast: '画面对比度较低，请调整机位',
  blurry: '画面较模糊，请固定手机并擦拭镜头',
  cat_too_small: '猫咪在画面中太小，请拉近机位',
}

const clamp = (value, min, max) => Math.min(Math.max(value, min), max)

const formatClock = (timestamp) => {
  if (!timestamp) return '暂无'
  const date = new Date(timestamp)
  const hh = date.getHours().toString().padStart(2, '0')
  const mm = date.getMinutes().toString().padStart(2, '0')
  const ss = date.getSeconds().toString().padStart(2, '0')
  return `${hh}:${mm}:${ss}`
}

Page({
  data: {
    running: false,
    cameraVisible: false,
    statusText: '点击开始监控',
    statusType: 'idle',
    frameCount: 0,
    battery: 100,
    isCharging: false,
    lowBattery: false,
    previewSrc: '',
    qualityWarning: '',
    reconnectText: '',
    serverUrl: SERVER_URL,
    uploadState: 'idle',
    uploadStateLabel: '未连接',
    lastUploadText: '暂无',
    lastErrorText: '暂无',
    failCount: 0,
    nextRetryText: '',
    uploadingNow: false,
    lastHttpStatus: '',
    feedingFeedbackText: '等待进食区域反馈',
    feedingFeedbackType: 'idle',

    hasFeedingZone: false,
    feedingZone: { ...DEFAULT_FEEDING_ZONE },
    feedingZoneStyle: '',
    liveFeedingZoneStyle: '',
    foodLevelZoneStyle: '',
    showFeedingZone: true,
    settingsOpen: false,
    showSetupPrompt: false,
    calibrationStep: '',
    calibrationImage: '',
    calibrationStageStyle: '',
    foodCalibrationTitle: '',
    foodCalibrationDesc: '',
    foodCalibrationUploading: false,
  },

  _timer: null,
  _batteryTimer: null,
  _cameraCtx: null,
  _retryCount: 0,
  _frameBusy: false,
  _nextAttemptAt: 0,
  _uploadTask: null,
  _uploadTimeout: null,
  _stopping: false,
  _calibrationRect: null,
  _zoneGesture: null,
  _deviceId: '',

  onLoad() {
    wx.setKeepScreenOn({ keepScreenOn: true })
    this._deviceId = this._loadDeviceId()
    this._loadFeedingZone()
    this._checkBattery()
    this._batteryTimer = setInterval(() => this._checkBattery(), 60000)
  },

  _loadDeviceId() {
    try {
      const saved = wx.getStorageSync(DEVICE_ID_STORAGE_KEY)
      if (saved) return String(saved)
      const info = wx.getSystemInfoSync()
      const model = String(info.model || 'wechat-device')
        .replace(/[^a-zA-Z0-9_-]/g, '-')
        .slice(0, 24)
      const id = `${model}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
      wx.setStorageSync(DEVICE_ID_STORAGE_KEY, id)
      return id
    } catch (err) {
      console.warn('[device] id storage failed', err)
      return `wechat-${Date.now().toString(36)}`
    }
  },

  onUnload() {
    this._stopCapture()
    clearInterval(this._batteryTimer)
  },

  _loadFeedingZone() {
    try {
      const saved = wx.getStorageSync(FEEDING_ZONE_STORAGE_KEY)
      if (saved && this._isValidZone(saved)) {
        this.setData({
          hasFeedingZone: true,
          feedingZone: saved,
          feedingZoneStyle: this._zoneStyle(saved),
          liveFeedingZoneStyle: this._liveZoneStyle(saved),
          foodLevelZoneStyle: this._liveZoneStyle(this._foodLevelZone(saved)),
        })
        return
      }
    } catch (err) {
      console.warn('[feeding-zone] load failed', err)
    }
    this.setData({
      hasFeedingZone: false,
      showSetupPrompt: true,
      feedingZoneStyle: this._zoneStyle(DEFAULT_FEEDING_ZONE),
      liveFeedingZoneStyle: this._liveZoneStyle(DEFAULT_FEEDING_ZONE),
      foodLevelZoneStyle: this._liveZoneStyle(this._foodLevelZone(DEFAULT_FEEDING_ZONE)),
    })
  },

  _isValidZone(zone) {
    if (!zone) return false
    const { x, y, width, height } = zone
    return [x, y, width, height].every(Number.isFinite)
      && x >= 0
      && y >= 0
      && width >= MIN_ZONE_SIZE
      && height >= MIN_ZONE_SIZE
      && x + width <= 1
      && y + height <= 1
  },

  _zoneStyle(zone) {
    return [
      `left:${zone.x * 100}%`,
      `top:${zone.y * 100}%`,
      `width:${zone.width * 100}%`,
      `height:${zone.height * 100}%`,
    ].join(';')
  },

  _liveZoneStyle(zone) {
    if (!zone.imageWidth || !zone.imageHeight) {
      return this._zoneStyle(zone)
    }

    const windowInfo = wx.getWindowInfo
      ? wx.getWindowInfo()
      : wx.getSystemInfoSync()
    const viewWidth = windowInfo.windowWidth
    const viewHeight = windowInfo.windowHeight
    const scale = Math.max(
      viewWidth / zone.imageWidth,
      viewHeight / zone.imageHeight,
    )
    const renderedWidth = zone.imageWidth * scale
    const renderedHeight = zone.imageHeight * scale
    const offsetX = (viewWidth - renderedWidth) / 2
    const offsetY = (viewHeight - renderedHeight) / 2

    return [
      `left:${offsetX + zone.x * renderedWidth}px`,
      `top:${offsetY + zone.y * renderedHeight}px`,
      `width:${zone.width * renderedWidth}px`,
      `height:${zone.height * renderedHeight}px`,
    ].join(';')
  },

  _foodLevelZone(zone) {
    return {
      ...zone,
      x: zone.x + zone.width * 0.08,
      y: zone.y + zone.height * 0.45,
      width: zone.width * 0.84,
      height: zone.height * 0.5,
    }
  },

  onSkipSetup() {
    this.setData({ showSetupPrompt: false })
  },

  onToggleSettings() {
    this.setData({ settingsOpen: !this.data.settingsOpen })
  },

  onTestConnection() {
    this.setData({ settingsOpen: false })
    this._setUploadStatus({
      state: 'uploading',
      label: '测试连接中',
      uploadingNow: true,
      error: '',
      nextRetry: '',
      httpStatus: '',
    })
    wx.request({
      url: `${SERVER_URL}/api/health`,
      method: 'GET',
      timeout: 8000,
      header: {
        'ngrok-skip-browser-warning': 'true',
      },
      success: (res) => {
        if (res.statusCode === 200 && res.data && res.data.ok) {
          this._setUploadStatus({
            state: 'ok',
            label: '服务端已连接',
            lastUploadAt: Date.now(),
            failCount: 0,
            error: '',
            nextRetry: '',
            uploadingNow: false,
            httpStatus: '200',
          })
          wx.showToast({ title: '服务端正常', icon: 'success' })
          return
        }
        this._setUploadStatus({
          state: 'error',
          label: '服务端异常',
          error: `健康检查返回 ${res.statusCode}`,
          nextRetry: '',
          uploadingNow: false,
          httpStatus: String(res.statusCode || ''),
        })
      },
      fail: (err) => {
        this._setUploadStatus({
          state: 'error',
          label: '连接失败',
          error: this._shortError(err),
          nextRetry: '',
          uploadingNow: false,
          httpStatus: '',
        })
      },
    })
  },

  onCloseSettings() {
    this.setData({ settingsOpen: false })
  },

  onToggleFeedingZone() {
    this.setData({
      showFeedingZone: !this.data.showFeedingZone,
      settingsOpen: false,
    })
  },

  onOpenFeedingSetup() {
    if (this.data.running) this._stopCapture()
    this.setData({
      settingsOpen: false,
      showSetupPrompt: false,
      calibrationStep: 'camera',
      calibrationImage: '',
      previewSrc: '',
      cameraVisible: true,
      statusText: '请固定机位并拍摄校准照片',
      statusType: 'idle',
    }, () => {
      this._cameraCtx = wx.createCameraContext()
    })
  },

  onOpenFoodCalibration() {
    if (!this.data.hasFeedingZone) {
      wx.showToast({ title: '请先设置食盆区域', icon: 'none' })
      return
    }
    if (this.data.running) this._stopCapture()
    this.setData({ settingsOpen: false })
    wx.showModal({
      title: '校准猫粮余量',
      content: '第一步请清空食盆，并保持手机和食盆位置不变。',
      confirmText: '拍摄空碗',
      success: (res) => {
        if (!res.confirm) return
        this._startFoodCalibrationStep('empty')
      },
    })
  },

  _startFoodCalibrationStep(level) {
    const isEmpty = level === 'empty'
    this.setData({
      calibrationStep: `food-${level}`,
      cameraVisible: true,
      previewSrc: '',
      foodCalibrationTitle: isEmpty ? '拍摄空食盆' : '拍摄装满的食盆',
      foodCalibrationDesc: isEmpty
        ? '食盆需要完全清空，机位和光照保持日常状态'
        : '将猫粮加到日常最满位置，然后拍摄',
      foodCalibrationUploading: false,
      statusText: isEmpty ? '准备拍摄空碗' : '准备拍摄满碗',
      statusType: 'idle',
    }, () => {
      this._cameraCtx = wx.createCameraContext()
    })
  },

  onTakeFoodCalibrationPhoto() {
    if (this.data.foodCalibrationUploading) return
    const level = this.data.calibrationStep === 'food-empty' ? 'empty' : 'full'
    if (!this._cameraCtx) this._cameraCtx = wx.createCameraContext()
    this.setData({ foodCalibrationUploading: true })
    this._cameraCtx.takePhoto({
      quality: 'high',
      success: (res) => this._uploadFoodCalibration(res.tempImagePath, level),
      fail: (err) => {
        console.error('[food-calibration] take photo failed', err)
        this.setData({ foodCalibrationUploading: false })
        wx.showToast({ title: '拍摄失败，请重试', icon: 'none' })
      },
    })
  },

  _uploadFoodCalibration(filePath, level) {
    wx.uploadFile({
      url: `${SERVER_URL}/api/food-calibration`,
      filePath,
      name: 'file',
      formData: {
        device_id: this._deviceId,
        level,
        feeding_zone: JSON.stringify(this.data.feedingZone),
      },
      header: {
        'ngrok-skip-browser-warning': 'true',
      },
      success: (res) => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          console.error('[food-calibration] server error', res.statusCode, res.data)
          wx.showToast({ title: '校准上传失败', icon: 'none' })
          return
        }
        if (level === 'empty') {
          wx.showModal({
            title: '空碗记录完成',
            content: '现在将猫粮装到日常最满位置，保持手机和食盆不动。',
            confirmText: '拍摄满碗',
            showCancel: false,
            success: () => this._startFoodCalibrationStep('full'),
          })
          return
        }
        this.setData({
          calibrationStep: '',
          cameraVisible: false,
          foodCalibrationUploading: false,
          statusText: '猫粮余量校准完成',
          statusType: 'ok',
        })
        wx.showToast({ title: '余量校准完成', icon: 'success' })
      },
      fail: (err) => {
        console.error('[food-calibration] upload failed', err)
        wx.showToast({ title: '连接服务端失败', icon: 'none' })
      },
      complete: () => {
        if (level === 'full' || this.data.calibrationStep === `food-${level}`) {
          this.setData({ foodCalibrationUploading: false })
        }
      },
    })
  },

  onCancelCalibration() {
    this._zoneGesture = null
    this._calibrationRect = null
    this.setData({
      calibrationStep: '',
      calibrationImage: '',
      cameraVisible: false,
      statusText: this.data.hasFeedingZone ? '已取消重新设置' : '点击开始监控',
      statusType: 'idle',
    })
  },

  onTakeCalibrationPhoto() {
    if (!this._cameraCtx) this._cameraCtx = wx.createCameraContext()
    this.setData({ statusText: '正在拍摄校准照片…', statusType: 'uploading' })
    this._cameraCtx.takePhoto({
      quality: 'high',
      success: (res) => {
        this._openCalibrationEditor(res.tempImagePath)
      },
      fail: (err) => {
        console.error('[feeding-zone] take photo failed', err)
        this.setData({ statusText: '拍摄失败，请重试', statusType: 'error' })
      },
    })
  },

  _openCalibrationEditor(imagePath) {
    wx.getImageInfo({
      src: imagePath,
      success: (info) => {
        const original = this.data.hasFeedingZone
          ? this.data.feedingZone
          : DEFAULT_FEEDING_ZONE
        const zone = {
          ...original,
          imageWidth: info.width,
          imageHeight: info.height,
        }
        this._showCalibrationEditor(imagePath, zone)
      },
      fail: () => {
        const zone = this.data.hasFeedingZone
          ? { ...this.data.feedingZone }
          : { ...DEFAULT_FEEDING_ZONE }
        this._showCalibrationEditor(imagePath, zone)
      },
    })
  },

  _showCalibrationEditor(imagePath, zone) {
    this.setData({
      cameraVisible: false,
      calibrationStep: 'edit',
      calibrationImage: imagePath,
      calibrationStageStyle: this._calibrationStageStyle(zone),
      feedingZone: zone,
      feedingZoneStyle: this._zoneStyle(zone),
      statusText: '拖动方框框住食盆及其上方空间',
      statusType: 'idle',
    })
  },

  _calibrationStageStyle(zone) {
    if (!zone.imageWidth || !zone.imageHeight) {
      return 'width:100%;height:55vh'
    }

    const windowInfo = wx.getWindowInfo
      ? wx.getWindowInfo()
      : wx.getSystemInfoSync()
    const maxWidth = windowInfo.windowWidth
    const maxHeight = Math.max(windowInfo.windowHeight - 210, 240)
    const scale = Math.min(
      maxWidth / zone.imageWidth,
      maxHeight / zone.imageHeight,
    )

    return [
      `width:${Math.round(zone.imageWidth * scale)}px`,
      `height:${Math.round(zone.imageHeight * scale)}px`,
    ].join(';')
  },

  onCalibrationImageLoad() {
    wx.createSelectorQuery()
      .select('.calibration-photo')
      .boundingClientRect((rect) => {
        this._calibrationRect = rect
      })
      .exec()
  },

  onZoneTouchStart(event) {
    this._startZoneGesture('move', event)
  },

  onResizeTouchStart(event) {
    this._startZoneGesture('resize', event)
  },

  _startZoneGesture(mode, event) {
    const touch = event.touches && event.touches[0]
    if (!touch || !this._calibrationRect) return
    this._zoneGesture = {
      mode,
      startX: touch.clientX,
      startY: touch.clientY,
      zone: { ...this.data.feedingZone },
    }
  },

  onZoneTouchMove(event) {
    const touch = event.touches && event.touches[0]
    const gesture = this._zoneGesture
    const rect = this._calibrationRect
    if (!touch || !gesture || !rect || !rect.width || !rect.height) return

    const dx = (touch.clientX - gesture.startX) / rect.width
    const dy = (touch.clientY - gesture.startY) / rect.height
    const original = gesture.zone
    let next

    if (gesture.mode === 'resize') {
      next = {
        ...original,
        width: clamp(original.width + dx, MIN_ZONE_SIZE, 1 - original.x),
        height: clamp(original.height + dy, MIN_ZONE_SIZE, 1 - original.y),
      }
    } else {
      next = {
        ...original,
        x: clamp(original.x + dx, 0, 1 - original.width),
        y: clamp(original.y + dy, 0, 1 - original.height),
      }
    }

    this.setData({
      feedingZone: next,
      feedingZoneStyle: this._zoneStyle(next),
    })
  },

  onZoneTouchEnd() {
    this._zoneGesture = null
  },

  onResetZone() {
    const zone = { ...DEFAULT_FEEDING_ZONE }
    if (this.data.feedingZone.imageWidth && this.data.feedingZone.imageHeight) {
      zone.imageWidth = this.data.feedingZone.imageWidth
      zone.imageHeight = this.data.feedingZone.imageHeight
    }
    this.setData({
      feedingZone: zone,
      feedingZoneStyle: this._zoneStyle(zone),
    })
  },

  onRetakeCalibration() {
    this._calibrationRect = null
    this.setData({
      calibrationStep: 'camera',
      calibrationImage: '',
      cameraVisible: true,
      statusText: '请重新拍摄校准照片',
      statusType: 'idle',
    }, () => {
      this._cameraCtx = wx.createCameraContext()
    })
  },

  onSaveFeedingZone() {
    const zone = {
      ...this.data.feedingZone,
      version: 1,
    }
    if (!this._isValidZone(zone)) {
      wx.showToast({ title: '区域过小或超出画面', icon: 'none' })
      return
    }

    try {
      wx.setStorageSync(FEEDING_ZONE_STORAGE_KEY, zone)
      this.setData({
        hasFeedingZone: true,
        feedingZone: zone,
        feedingZoneStyle: this._zoneStyle(zone),
        liveFeedingZoneStyle: this._liveZoneStyle(zone),
        foodLevelZoneStyle: this._liveZoneStyle(this._foodLevelZone(zone)),
        calibrationStep: '',
        calibrationImage: '',
        cameraVisible: false,
        statusText: '进食区域设置完成',
        statusType: 'ok',
      })
      wx.showToast({ title: '设置已保存', icon: 'success' })
    } catch (err) {
      console.error('[feeding-zone] save failed', err)
      wx.showToast({ title: '保存失败，请重试', icon: 'none' })
    }
  },

  onClearFeedingZone() {
    wx.showModal({
      title: '清除进食区域',
      content: '清除后将暂停进食识别，其他状态不受影响。',
      confirmText: '清除',
      confirmColor: '#E85A5A',
      success: (res) => {
        if (!res.confirm) return
        wx.removeStorageSync(FEEDING_ZONE_STORAGE_KEY)
        this.setData({
          hasFeedingZone: false,
          feedingZone: { ...DEFAULT_FEEDING_ZONE },
          feedingZoneStyle: this._zoneStyle(DEFAULT_FEEDING_ZONE),
          liveFeedingZoneStyle: this._liveZoneStyle(DEFAULT_FEEDING_ZONE),
          foodLevelZoneStyle: this._liveZoneStyle(this._foodLevelZone(DEFAULT_FEEDING_ZONE)),
          settingsOpen: false,
          showSetupPrompt: true,
          statusText: '进食区域已清除',
          statusType: 'idle',
        })
      },
    })
  },

  onStartStop() {
    if (this.data.running) {
      this._stopCapture()
    } else {
      this._startCapture()
    }
  },

  _startCapture() {
    this._stopping = false
    this._retryCount = 0
    this._nextAttemptAt = 0
    this._cameraCtx = wx.createCameraContext()
    this.setData({
      running: true,
      cameraVisible: true,
      settingsOpen: false,
      statusText: this.data.hasFeedingZone ? '监控中…' : '监控中 · 进食识别未设置',
      statusType: 'ok',
      frameCount: 0,
      qualityWarning: '',
      reconnectText: '',
      uploadState: 'uploading',
      uploadStateLabel: '准备上传',
      lastUploadText: '暂无',
      lastErrorText: '暂无',
      failCount: 0,
      nextRetryText: '',
      uploadingNow: false,
      lastHttpStatus: '',
      feedingFeedbackText: this.data.hasFeedingZone ? '等待猫咪进入食盆区域' : '未设置食盆区域',
      feedingFeedbackType: this.data.hasFeedingZone ? 'waiting' : 'missing',
    })
    this._timer = setInterval(() => this._tick(), CAPTURE_INTERVAL_MS)
    this._tick()
  },

  _stopCapture() {
    this._stopping = true
    if (this._timer) {
      clearInterval(this._timer)
      this._timer = null
    }
    if (this._uploadTimeout) {
      clearTimeout(this._uploadTimeout)
      this._uploadTimeout = null
    }
    if (this._uploadTask) {
      this._uploadTask.abort()
      this._uploadTask = null
    }
    this._frameBusy = false
    this._nextAttemptAt = 0
    this.setData({
      running: false,
      cameraVisible: false,
      settingsOpen: false,
      statusText: '已停止',
      statusType: 'idle',
      previewSrc: '',
      qualityWarning: '',
      reconnectText: '',
      uploadState: 'idle',
      uploadStateLabel: '已停止',
      uploadingNow: false,
      nextRetryText: '',
      feedingFeedbackText: '监控已停止',
      feedingFeedbackType: 'idle',
    })
  },

  _tick() {
    if (!this._cameraCtx || !this.data.running || this._frameBusy) return
    if (Date.now() < this._nextAttemptAt) return
    this._frameBusy = true
    this.setData({ statusText: '截图中…', statusType: 'uploading' })
    this._setUploadStatus({
      state: 'uploading',
      label: '截图中',
      uploadingNow: true,
      nextRetry: '',
    })

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
        this._finishFrame()
        this._scheduleRetry('截图失败')
      },
    })
  },

  _upload(filePath) {
    this._setUploadStatus({
      state: 'uploading',
      label: '上传中',
      uploadingNow: true,
      nextRetry: '',
      httpStatus: '',
    })

    const formData = {
      device_id: this._deviceId,
      captured_at: String(Date.now() / 1000),
      battery_level: String(this.data.battery),
      is_charging: this.data.isCharging ? 'true' : 'false',
    }
    if (this.data.hasFeedingZone) {
      formData.feeding_zone = JSON.stringify(this.data.feedingZone)
    }

    this._uploadTask = wx.uploadFile({
      url: `${SERVER_URL}/api/frame`,
      filePath,
      name: 'file',
      formData,
      header: {
        'ngrok-skip-browser-warning': 'true',
      },
      success: (res) => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          console.error('[capture] server error', res.statusCode, res.data)
          this._setUploadStatus({
            state: 'error',
            label: '服务端异常',
            error: `服务端返回 ${res.statusCode}`,
            httpStatus: String(res.statusCode || ''),
            uploadingNow: false,
          })
          this._scheduleRetry(`服务端返回 ${res.statusCode}`)
          return
        }

        this._retryCount = 0
        this._nextAttemptAt = 0
        const count = this.data.frameCount + 1
        this._setUploadStatus({
          state: 'ok',
          label: '上传正常',
          lastUploadAt: Date.now(),
          failCount: 0,
          error: '',
          nextRetry: '',
          uploadingNow: false,
          httpStatus: String(res.statusCode || 200),
        })
        try {
          const data = JSON.parse(res.data)
          const stateLabel = STATE_LABELS[data.state] || data.state || ''
          const warnings = data.quality && Array.isArray(data.quality.warnings)
            ? data.quality.warnings
            : []
          const qualityWarning = warnings.length
            ? (QUALITY_MESSAGES[warnings[0]] || '当前画面质量可能影响识别')
            : ''
          const feedingFeedback = this._formatFeedingFeedback(data.feeding)
          this.setData({
            statusText: `${stateLabel ? `${stateLabel} · ` : ''}已上传 ${count} 帧`,
            statusType: 'ok',
            frameCount: count,
            previewSrc: data.preview || '',
            qualityWarning,
            reconnectText: '',
            feedingFeedbackText: feedingFeedback.text,
            feedingFeedbackType: feedingFeedback.type,
          })
        } catch (err) {
          console.warn('[capture] invalid response', err)
          this.setData({
            statusText: `已上传 ${count} 帧`,
            statusType: 'ok',
            frameCount: count,
            reconnectText: '',
          })
        }
      },
      fail: (err) => {
        if (!this.data.running || this._stopping) return
        console.error('[capture] upload failed', err)
        const message = err && err.errMsg && err.errMsg.includes('timeout')
          ? '上传超时'
          : this._shortError(err)
        this._setUploadStatus({
          state: 'error',
          label: '上传失败',
          error: message,
          uploadingNow: false,
          httpStatus: '',
        })
        this._scheduleRetry(
          err && err.errMsg && err.errMsg.includes('timeout')
            ? '上传超时'
            : '网络连接异常',
        )
      },
      complete: () => {
        if (this._uploadTimeout) {
          clearTimeout(this._uploadTimeout)
          this._uploadTimeout = null
        }
        this._uploadTask = null
        this._finishFrame()
      },
    })

    this._uploadTimeout = setTimeout(() => {
      if (!this._uploadTask) return
      console.warn('[capture] upload timeout, aborting current frame')
      this._uploadTask.abort()
    }, UPLOAD_TIMEOUT_MS)
  },

  _finishFrame() {
    this._frameBusy = false
  },

  _setUploadStatus(update = {}) {
    const next = {}
    if (update.state !== undefined) next.uploadState = update.state
    if (update.label !== undefined) next.uploadStateLabel = update.label
    if (update.lastUploadAt !== undefined) next.lastUploadText = formatClock(update.lastUploadAt)
    if (update.error !== undefined) next.lastErrorText = update.error || '暂无'
    if (update.failCount !== undefined) next.failCount = update.failCount
    if (update.nextRetry !== undefined) next.nextRetryText = update.nextRetry || ''
    if (update.uploadingNow !== undefined) next.uploadingNow = Boolean(update.uploadingNow)
    if (update.httpStatus !== undefined) next.lastHttpStatus = update.httpStatus || ''
    this.setData(next)
  },

  _shortError(err) {
    const message = err && err.errMsg ? String(err.errMsg) : '网络连接异常'
    if (message.includes('timeout')) return '请求超时'
    if (message.includes('fail')) return message.replace(/^.*fail[: ]?/i, '').slice(0, 42) || '网络连接异常'
    return message.slice(0, 42)
  },

  _formatFeedingFeedback(feeding) {
    if (!feeding || !feeding.zone_set) {
      return { type: 'missing', text: '未设置食盆区域' }
    }
    if (!feeding.cat_detected) {
      return { type: 'idle', text: '未识别到猫咪' }
    }
    if (feeding.confirmed || feeding.active) {
      const seconds = Math.round(feeding.active_seconds || feeding.candidate_seconds || 0)
      return { type: 'confirmed', text: `本次进食已记录${seconds ? ` · ${seconds} 秒` : ''}` }
    }
    if (feeding.in_zone) {
      const candidate = Math.round(feeding.candidate_seconds || 0)
      const total = Math.round(feeding.confirm_seconds || 15)
      const remain = Math.max(0, Math.round(feeding.remaining_seconds || 0))
      return {
        type: 'candidate',
        text: `疑似进食中 ${candidate}/${total} 秒${remain ? ` · 还需 ${remain} 秒` : ''}`,
      }
    }
    return { type: 'outside', text: '猫咪不在食盆区域' }
  },

  _scheduleRetry(message) {
    this._retryCount += 1
    const delayIndex = Math.min(this._retryCount - 1, RETRY_DELAYS_MS.length - 1)
    const delay = RETRY_DELAYS_MS[delayIndex]
    this._nextAttemptAt = Date.now() + delay
    const seconds = Math.round(delay / 1000)
    this.setData({
      statusText: `连接异常 (${this._retryCount}) · ${message}`,
      statusType: 'error',
      reconnectText: `${seconds} 秒后自动重试`,
      uploadState: 'error',
      uploadStateLabel: '等待重试',
      failCount: this._retryCount,
      lastErrorText: message,
      nextRetryText: `${seconds} 秒后自动重试`,
      uploadingNow: false,
    })
  },

  _checkBattery() {
    wx.getBatteryInfo({
      success: (res) => {
        this.setData({
          battery: res.level,
          isCharging: Boolean(res.isCharging),
          lowBattery: res.level < 20 && !res.isCharging,
        })
      },
    })
  },
})
