const SERVER_URL = getApp().globalData.serverUrl

const STATE_CONFIG = {
  sleep: { label: '睡眠中', color: '#9B7EC8', desc: '保持安静，正在休息' },
  play: { label: '玩耍中', color: '#4CAF7D', desc: '活动明显，精力充沛' },
  food: { label: '进食中', color: '#E8943A', desc: '停留在食盆区域进食' },
  dream: { label: '发呆中', color: '#4A90D9', desc: '清醒但活动较少' },
  unknown: { label: '未发现猫咪', color: '#C4BDB0', desc: '采集端在线，猫咪暂时不在画面中' },
}

const EMPTY_METRICS = [
  { key: 'battery', icon: '🔋', label: '设备电量', value: 0, unit: '%', barValue: 0, colorClass: 'water' },
  { key: 'food', icon: '🍚', label: '猫粮剩余', value: '--', unit: '', barValue: 0, colorClass: 'food' },
  { key: 'sleep', icon: '💤', label: '今日睡眠', value: 0, unit: '%', barValue: 0, colorClass: 'sleep' },
  { key: 'play', icon: '🎾', label: '今日活动量', value: 0, unit: '%', barValue: 0, colorClass: 'play' },
]

Page({
  data: {
    state: 'unknown',
    stateLabel: '等待采集端',
    stateDesc: '正在等待采集端上传画面',
    stateColor: '#C4BDB0',
    connected: false,
    lastUpdated: '',
    deviceInfo: '',
    metrics: EMPTY_METRICS,
    timeline: [{ type: 'idle', pct: 100 }],
  },

  _pollTimer: null,
  _polling: false,
  _lastSuccessAt: 0,

  onLoad() {
    this._poll()
    this._pollTimer = setInterval(() => this._poll(), 5000)
  },

  onShow() {
    this._poll()
  },

  onUnload() {
    clearInterval(this._pollTimer)
  },

  _poll() {
    if (this._polling) return
    this._polling = true

    wx.request({
      url: `${SERVER_URL}/api/status`,
      method: 'GET',
      timeout: 15000,
      header: {
        'ngrok-skip-browser-warning': 'true',
      },
      success: (res) => {
        if (
          res.statusCode === 200
          && res.data
          && typeof res.data === 'object'
          && typeof res.data.state === 'string'
        ) {
          this._lastSuccessAt = Date.now()
          this._applyState(res.data)
          return
        }
        this._showServerError('服务端没有返回有效状态')
      },
      fail: (err) => {
        console.warn('[display] request failed', err)
        if (Date.now() - this._lastSuccessAt > 20000) {
          this._showServerError('无法连接到服务端')
        }
      },
      complete: () => {
        this._polling = false
      },
    })
  },

  _showServerError(message) {
    this.setData({
      connected: false,
      state: 'unknown',
      stateLabel: '服务连接失败',
      stateDesc: message,
      stateColor: '#C4BDB0',
    })
  },

  _applyState(data) {
    const offline = Boolean(data.offline)
    const cfg = STATE_CONFIG[data.state] || STATE_CONFIG.unknown
    const timestamp = Number(data.captured_at || data.updated_at || 0)
    const device = data.device || {}
    const today = data.today || {}
    const summary = today.metrics || {}
    const battery = Number.isFinite(Number(summary.battery))
      ? Number(summary.battery)
      : 0
    const foodRemaining = data.food_remaining === null || data.food_remaining === undefined
      ? null
      : Math.max(0, Math.min(100, Number(data.food_remaining)))
    const sleepPct = Number(summary.sleep_pct || 0)
    const activityScore = Number(summary.activity_score || 0)

    let lastUpdated = ''
    if (timestamp > 0) {
      const date = new Date(timestamp * 1000)
      lastUpdated = `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
    }

    let deviceInfo = ''
    if (device.battery_level !== null && device.battery_level !== undefined) {
      deviceInfo = `采集端 ${device.battery_level}%${device.is_charging ? ' · 充电中' : ''}`
    }

    this.setData({
      state: offline ? 'unknown' : data.state,
      stateLabel: offline ? '采集端离线' : cfg.label,
      stateDesc: offline ? '超过 60 秒没有收到新画面' : cfg.desc,
      stateColor: offline ? '#C4BDB0' : cfg.color,
      connected: !offline,
      lastUpdated,
      deviceInfo,
      metrics: [
        { key: 'battery', icon: '🔋', label: '设备电量', value: battery, unit: '%', barValue: battery, colorClass: 'water' },
        {
          key: 'food',
          icon: '🍚',
          label: data.food_calibrated ? '猫粮剩余约' : '猫粮余量未校准',
          value: foodRemaining === null ? '--' : foodRemaining,
          unit: foodRemaining === null ? '' : '%',
          barValue: foodRemaining === null ? 0 : foodRemaining,
          colorClass: 'food',
        },
        { key: 'sleep', icon: '💤', label: '今日睡眠', value: sleepPct, unit: '%', barValue: sleepPct, colorClass: 'sleep' },
        {
          key: 'play',
          icon: '🎾',
          label: '今日活动量',
          value: activityScore,
          unit: '%',
          barValue: activityScore,
          colorClass: 'play',
        },
      ],
      timeline: Array.isArray(today.timeline) && today.timeline.length
        ? today.timeline
        : [{ type: 'idle', pct: 100 }],
    })
  },
})
