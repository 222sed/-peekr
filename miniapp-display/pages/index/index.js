const SERVER_URL = getApp().globalData.serverUrl

const STATE_CONFIG = {
  sleep:   { label: '睡眠中', color: '#9B7EC8', desc: '蜷缩入眠，呼吸绵长' },
  play:    { label: '玩耍中', color: '#4CAF7D', desc: '扑打玩具，精力充沛' },
  food:    { label: '觅食中', color: '#E8943A', desc: '低头进食，专注享用' },
  dream:   { label: '发呆中', color: '#4A90D9', desc: '凝视远方，思绪飘散' },
  unknown: { label: '侦测中', color: '#C4BDB0', desc: '正在寻找猫咪…' },
}

// Mock metric data — replaced by real data in Phase 2
const MOCK_METRICS = [
  { key: 'water', icon: '💧', label: '饮水', value: 82,  unit: '%',   colorClass: 'water' },
  { key: 'food',  icon: '🍚', label: '猫粮', value: 65,  unit: '%',   colorClass: 'food'  },
  { key: 'sleep', icon: '😴', label: '睡眠', value: 72,  unit: '%',   colorClass: 'sleep' },
  { key: 'play',  icon: '🎾', label: '活跃', value: 88,  unit: '%',   colorClass: 'play'  },
]

const MOCK_TIMELINE = [
  { type: 'sleep', pct: 28 },
  { type: 'idle',  pct: 4  },
  { type: 'food',  pct: 6  },
  { type: 'sleep', pct: 18 },
  { type: 'play',  pct: 14 },
  { type: 'food',  pct: 5  },
  { type: 'play',  pct: 25 },
]

Page({
  data: {
    state: 'unknown',
    stateLabel: '侦测中',
    stateDesc: '正在寻找猫咪…',
    stateColor: '#C4BDB0',
    connected: false,
    lastUpdated: '',
    metrics: MOCK_METRICS,
    timeline: MOCK_TIMELINE,
  },

  _pollTimer: null,
  _offlineTimer: null,
  _lastFrameTime: 0,
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
    clearTimeout(this._offlineTimer)
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
          res.statusCode === 200 &&
          res.data &&
          typeof res.data === 'object' &&
          typeof res.data.state === 'string'
        ) {
          console.log('[display] status', res.data)
          this._lastSuccessAt = Date.now()
          this._applyState(res.data)
        } else {
          console.error('[display] invalid server response', res.statusCode, res.data)
          this.setData({
            connected: false,
            state: 'unknown',
            stateLabel: '连接异常',
            stateDesc: '服务端没有返回有效状态',
          })
        }
      },
      fail: (err) => {
        console.warn('[display] request failed', err)
        const offline = Date.now() - this._lastSuccessAt > 20000
        if (offline) {
          this.setData({
            connected: false,
            stateLabel: '连接失败',
            stateDesc: '无法连接到服务端',
          })
        }
      },
      complete: () => {
        this._polling = false
      },
    })
  },

  _applyState(data) {
    const cfg = STATE_CONFIG[data.state] || STATE_CONFIG.unknown
    const now = new Date()
    const timeStr = `${now.getHours().toString().padStart(2,'0')}:${now.getMinutes().toString().padStart(2,'0')}`

    this.setData({
      state: data.state,
      stateLabel: cfg.label,
      stateDesc: cfg.desc,
      stateColor: cfg.color,
      // A successful /api/status response means the display is connected.
      // "unknown" only means that no cat is detected in the latest frame.
      connected: true,
      lastUpdated: timeStr,
    })
  },
})
