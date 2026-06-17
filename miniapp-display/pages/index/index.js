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

  onLoad() {
    this._poll()
    this._pollTimer = setInterval(() => this._poll(), 5000)
  },

  onUnload() {
    clearInterval(this._pollTimer)
    clearTimeout(this._offlineTimer)
  },

  _poll() {
    wx.request({
      url: `${SERVER_URL}/api/status`,
      method: 'GET',
      success: (res) => {
        if (res.statusCode === 200) {
          this._applyState(res.data)
        }
      },
      fail: () => {
        this.setData({ connected: false, stateLabel: '连接失败', stateDesc: '无法连接到服务端' })
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
      connected: data.state !== 'unknown',
      lastUpdated: timeStr,
    })
  },
})
