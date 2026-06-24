const SERVER_URL = getApp().globalData.serverUrl
const CAT_PROFILE_KEY = 'peekr_display_cat_profile_v1'
const TEST_MODE_KEY = 'peekr_display_test_mode_v1'

const STATE_CONFIG = {
  sleep: { label: '睡眠中', color: '#9B7EC8', desc: '保持安静，正在休息' },
  play: { label: '活动中', color: '#4CAF7D', desc: '活动明显，精力充沛' },
  food: { label: '进食中', color: '#E8943A', desc: '停留在食盆区域，可能正在进食' },
  dream: { label: '发呆中', color: '#4A90D9', desc: '清醒但活动较少' },
  unknown: { label: '未发现猫咪', color: '#C4BDB0', desc: '采集端在线，但猫咪暂时不在画面中' },
}

const BODY_SVG = {
  body1: '/assets/cat-body-1.svg',
  body2: '/assets/cat-body-2.svg',
  body3: '/assets/cat-body-3.svg',
  body4: '/assets/cat-body-4.svg',
}

const DASHBOARD_CAT_SVG = '/assets/cat-black-white-3.svg'

const CATEGORY_LIST = [
  { key: 'bodyShape', label: '体型', icon: '🐾' },
  { key: 'coatPattern', label: '花色', icon: '🎨' },
  { key: 'bodyColor', label: '主体', icon: '🐱' },
  { key: 'bellyColor', label: '肚皮', icon: '🤍' },
  { key: 'eyeColor', label: '眼睛', icon: '👁' },
  { key: 'accessory', label: '配饰', icon: '🎀' },
]

const OPTION_MAP = {
  bodyShape: [
    { value: 'body1', label: '体型 1', desc: '原型一', previewSrc: BODY_SVG.body1 },
    { value: 'body2', label: '体型 2', desc: '原型二', previewSrc: BODY_SVG.body2 },
    { value: 'body3', label: '体型 3', desc: '原型三', previewSrc: BODY_SVG.body3 },
    { value: 'body4', label: '体型 4', desc: '原型四', previewSrc: BODY_SVG.body4 },
  ],
  coatPattern: [
    { value: 'solid', label: '纯色', desc: '无明显花纹', swatch: '#EFE4D5' },
    { value: 'orange', label: '橘猫', desc: '橘色系', swatch: '#E89A42' },
    { value: 'cow', label: '奶牛猫', desc: '黑白块面', swatch: '#2F2F35' },
    { value: 'calico', label: '三花', desc: '橘黑白', swatch: '#D9783A' },
    { value: 'tabby', label: '虎斑', desc: '条纹花色', swatch: '#9B6B46' },
    { value: 'grayWhite', label: '灰白', desc: '灰白拼色', swatch: '#9FA6AD' },
  ],
  bodyColor: [
    { value: 'white', label: '白色', swatch: '#F7F0E4' },
    { value: 'gray', label: '灰色', swatch: '#9FA6AD' },
    { value: 'orange', label: '橘色', swatch: '#E89A42' },
    { value: 'cream', label: '奶油色', swatch: '#EFD7AA' },
    { value: 'black', label: '黑色', swatch: '#2F2F35' },
    { value: 'brown', label: '棕色', swatch: '#9B6B46' },
  ],
  bellyColor: [
    { value: 'none', label: '无明显肚皮', swatch: '#FFFFFF' },
    { value: 'white', label: '白肚皮', swatch: '#FFF8EE' },
    { value: 'cream', label: '奶油肚皮', swatch: '#F4DFB8' },
    { value: 'gray', label: '浅灰肚皮', swatch: '#D8D8D8' },
  ],
  eyeColor: [
    { value: 'yellow', label: '黄色', swatch: '#EBC84A' },
    { value: 'green', label: '绿色', swatch: '#6DCB77' },
    { value: 'blue', label: '蓝色', swatch: '#72B7E8' },
    { value: 'amber', label: '琥珀色', swatch: '#D89432' },
    { value: 'grayBlue', label: '灰蓝色', swatch: '#8EAFC6' },
  ],
  accessory: [
    { value: 'none', label: '无配饰', desc: '保持原样', emoji: '—' },
    { value: 'bell', label: '铃铛', desc: '项圈铃铛', emoji: '🔔' },
    { value: 'bow', label: '领结', desc: '可爱领结', emoji: '🎀' },
    { value: 'scarf', label: '围巾', desc: '保暖围巾', emoji: '🧣' },
    { value: 'hat', label: '小帽子', desc: '装饰帽', emoji: '🎩' },
  ],
}

const DEFAULT_PROFILE = {
  name: '小灰',
  bodyShape: 'body1',
  coatPattern: 'grayWhite',
  bodyColor: 'gray',
  bellyColor: 'white',
  eyeColor: 'yellow',
  accessory: 'none',
}

const EMPTY_METRICS = [
  { key: 'food', icon: '🍚', label: '猫粮余量', value: '--', unit: '', barValue: 0, colorClass: 'food' },
  { key: 'play', icon: '🧶', label: '今日活动', value: 0, unit: '%', barValue: 0, colorClass: 'play' },
  { key: 'sleep', icon: '💤', label: '今日睡眠', value: 0, unit: '%', barValue: 0, colorClass: 'sleep' },
  { key: 'meal', icon: '🍽', label: '今日进食', value: 0, unit: '次', barValue: 0, colorClass: 'meal' },
]

const DEMO_STATES = ['sleep', 'play', 'food', 'dream']

const formatClock = (timestamp) => {
  if (!timestamp) return '暂无'
  const date = new Date(Number(timestamp) * 1000)
  return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}`
}

const formatDuration = (seconds) => {
  const total = Math.max(0, Math.round(Number(seconds || 0)))
  if (total <= 0) return '暂无'
  const minutes = Math.floor(total / 60)
  const rest = total % 60
  if (minutes <= 0) return `${rest} 秒`
  if (rest <= 0) return `${minutes} 分钟`
  return `${minutes} 分 ${rest} 秒`
}

Page({
  data: {
    hasProfile: false,
    activeCategory: 'bodyShape',
    categories: CATEGORY_LIST,
    activeOptions: [],
    catProfile: { ...DEFAULT_PROFILE },
    catPreview: {},
    dashboardCatSrc: DASHBOARD_CAT_SVG,
    selectedSummary: [],
    settingsOpen: false,
    testMode: false,
    state: 'unknown',
    stateLabel: '等待采集端',
    stateDesc: '正在等待采集端上传画面',
    stateColor: '#C4BDB0',
    connected: false,
    lastUpdated: '',
    deviceInfo: '',
    deviceNote: '采集端数据实时同步',
    foodCalibrated: false,
    metrics: EMPTY_METRICS,
    feedingStats: {
      count: 0,
      latestText: '暂无',
      durationText: '暂无',
      activeText: '无',
    },
    timeline: [{ type: 'idle', pct: 100 }],
  },

  _pollTimer: null,
  _polling: false,
  _lastSuccessAt: 0,
  _demoIndex: 0,

  onLoad() {
    this._loadCatProfile()
    this._loadTestMode()
    this._poll()
    this._pollTimer = setInterval(() => this._poll(), 5000)
  },

  onShow() {
    this._poll()
  },

  onUnload() {
    clearInterval(this._pollTimer)
  },

  onNameInput(event) {
    this._updateProfile({ name: event.detail.value })
  },

  onSelectCategory(event) {
    const key = event.currentTarget.dataset.key
    if (!OPTION_MAP[key]) return
    this.setData({
      activeCategory: key,
      activeOptions: this._optionsFor(key, this.data.catProfile),
    })
  },

  onSelectOption(event) {
    const { field, value } = event.currentTarget.dataset
    if (!field || value === undefined) return
    this._updateProfile({ [field]: value })
  },

  onToolTap(event) {
    const action = event.currentTarget.dataset.action
    if (action === 'info') {
      wx.showModal({
        title: '猫咪形象',
        content: '当前版本优先保证界面稳定。体型使用你提供的 SVG 原型，花色、颜色、配饰先作为配置保存和标签展示。后续如果提供分层素材，可以做到真正精准换装。',
        showCancel: false,
      })
      return
    }
    if (action === 'camera') {
      wx.showToast({ title: '拍照生成后续开放', icon: 'none' })
      return
    }
    if (action === 'save') this.onSaveCatProfile()
  },

  onSaveCatProfile() {
    const profile = this._normalizedProfile(this.data.catProfile)
    wx.setStorageSync(CAT_PROFILE_KEY, profile)
    this._applyProfile(profile, true)
  },

  onEditCatProfile() {
    this.setData({ hasProfile: false })
  },

  onOpenSettings() {
    this.setData({ settingsOpen: !this.data.settingsOpen })
  },

  onCloseSettings() {
    this.setData({ settingsOpen: false })
  },

  onToggleTestMode() {
    const testMode = !this.data.testMode
    wx.setStorageSync(TEST_MODE_KEY, testMode)
    this.setData({ testMode, settingsOpen: false })
    this._poll()
    wx.showToast({
      title: testMode ? '测试模式已开启' : '测试模式已关闭',
      icon: 'none',
    })
  },

  _loadCatProfile() {
    const cached = wx.getStorageSync(CAT_PROFILE_KEY)
    const profile = this._normalizedProfile(cached || DEFAULT_PROFILE)
    this._applyProfile(profile, Boolean(cached))
  },

  _loadTestMode() {
    this.setData({ testMode: Boolean(wx.getStorageSync(TEST_MODE_KEY)) })
  },

  _updateProfile(partial) {
    const profile = this._normalizedProfile({ ...this.data.catProfile, ...partial })
    this._applyProfile(profile, this.data.hasProfile)
  },

  _applyProfile(profile, hasProfile) {
    this.setData({
      hasProfile,
      catProfile: profile,
      catPreview: this._buildCatPreview(profile),
      selectedSummary: this._selectedSummary(profile),
      activeOptions: this._optionsFor(this.data.activeCategory, profile),
    })
  },

  _normalizedProfile(profile) {
    const next = { ...DEFAULT_PROFILE, ...(profile || {}) }
    if (next.bodyShape === 'small') next.bodyShape = 'body1'
    if (next.bodyShape === 'standard') next.bodyShape = 'body2'
    if (next.bodyShape === 'round') next.bodyShape = 'body3'
    if (next.bodyShape === 'fluffy') next.bodyShape = 'body4'
    next.name = String(next.name || '').trim().slice(0, 8) || DEFAULT_PROFILE.name
    Object.keys(DEFAULT_PROFILE).forEach((key) => {
      if (key !== 'name' && !OPTION_MAP[key].some((item) => item.value === next[key])) {
        next[key] = DEFAULT_PROFILE[key]
      }
    })
    return next
  },

  _buildCatPreview(profile) {
    return {
      bodySrc: BODY_SVG[profile.bodyShape] || BODY_SVG.body1,
    }
  },

  _optionsFor(key, profile) {
    return (OPTION_MAP[key] || []).map((item) => ({
      ...item,
      selected: profile[key] === item.value,
    }))
  },

  _labelOf(key, value) {
    const item = (OPTION_MAP[key] || []).find((option) => option.value === value)
    return item ? item.label : ''
  },

  _selectedSummary(profile) {
    return [
      { key: 'bodyShape', label: '体型', value: this._labelOf('bodyShape', profile.bodyShape) },
      { key: 'coatPattern', label: '花色', value: this._labelOf('coatPattern', profile.coatPattern) },
      { key: 'bodyColor', label: '主体', value: this._labelOf('bodyColor', profile.bodyColor) },
      { key: 'bellyColor', label: '肚皮', value: this._labelOf('bellyColor', profile.bellyColor) },
      { key: 'eyeColor', label: '眼睛', value: this._labelOf('eyeColor', profile.eyeColor) },
      { key: 'accessory', label: '配饰', value: this._labelOf('accessory', profile.accessory) },
    ]
  },

  _poll() {
    if (this.data.testMode) {
      this._applyDemoState()
      return
    }

    if (this._polling) return
    this._polling = true

    wx.request({
      url: `${SERVER_URL}/api/status`,
      method: 'GET',
      timeout: 15000,
      header: { 'ngrok-skip-browser-warning': 'true' },
      success: (res) => {
        if (res.statusCode === 200 && res.data && typeof res.data === 'object' && typeof res.data.state === 'string') {
          this._lastSuccessAt = Date.now()
          this._applyState(res.data)
          return
        }
        this._showServerError('服务端没有返回有效状态')
      },
      fail: (err) => {
        console.warn('[display] request failed', err)
        if (Date.now() - this._lastSuccessAt > 20000) this._showServerError('无法连接到服务端')
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

  _applyDemoState() {
    const demoState = DEMO_STATES[this._demoIndex % DEMO_STATES.length]
    const now = Math.floor(Date.now() / 1000)
    this._demoIndex += 1

    this._applyState({
      state: demoState,
      updated_at: now,
      captured_at: now,
      offline: false,
      food_calibrated: true,
      food_remaining: demoState === 'food' ? 62 : 68,
      device: {
        battery_level: 86,
        is_charging: false,
      },
      today: {
        metrics: {
          activity_score: demoState === 'play' ? 92 : 48,
          sleep_pct: demoState === 'sleep' ? 76 : 42,
          food_count: 3,
        },
        feeding: {
          count: 3,
          latest: {
            started_at: now - 1800,
            duration_seconds: 260,
          },
          active: demoState === 'food' ? {
            started_at: now - 80,
            duration_seconds: 80,
          } : null,
        },
        timeline: [
          { type: 'sleep', pct: 34 },
          { type: 'dream', pct: 18 },
          { type: 'food', pct: 9 },
          { type: 'play', pct: 28 },
          { type: 'idle', pct: 11 },
        ],
      },
    })
  },

  _applyState(data) {
    const offline = Boolean(data.offline)
    const cfg = STATE_CONFIG[data.state] || STATE_CONFIG.unknown
    const timestamp = Number(data.captured_at || data.updated_at || 0)
    const device = data.device || {}
    const today = data.today || {}
    const summary = today.metrics || {}
    const feeding = today.feeding || {}
    const latestFeeding = feeding.latest || null
    const activeFeeding = feeding.active || null
    const foodRemaining = data.food_remaining === null || data.food_remaining === undefined
      ? null
      : Math.max(0, Math.min(100, Number(data.food_remaining)))
    const sleepPct = Number(summary.sleep_pct || 0)
    const activityScore = Number(summary.activity_score || 0)
    const feedingCount = Number(feeding.count || summary.food_count || 0)

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
      deviceNote: deviceInfo || '采集端数据实时同步',
      foodCalibrated: Boolean(data.food_calibrated),
      feedingStats: {
        count: feedingCount,
        latestText: latestFeeding ? formatClock(latestFeeding.started_at) : '暂无',
        durationText: latestFeeding ? formatDuration(latestFeeding.duration_seconds) : '暂无',
        activeText: activeFeeding ? '正在进食' : '无',
      },
      metrics: [
        {
          key: 'food',
          icon: '🍚',
          label: data.food_calibrated ? '猫粮余量' : '猫粮未校准',
          value: foodRemaining === null ? '--' : foodRemaining,
          unit: foodRemaining === null ? '' : '%',
          barValue: foodRemaining === null ? 0 : foodRemaining,
          colorClass: 'food',
        },
        { key: 'play', icon: '🧶', label: '今日活动', value: activityScore, unit: '%', barValue: activityScore, colorClass: 'play' },
        { key: 'sleep', icon: '💤', label: '今日睡眠', value: sleepPct, unit: '%', barValue: sleepPct, colorClass: 'sleep' },
        {
          key: 'meal',
          icon: '🍽',
          label: activeFeeding ? '正在进食' : '今日进食',
          value: feedingCount,
          unit: '次',
          barValue: Math.min(100, feedingCount * 25),
          colorClass: 'meal',
        },
      ],
      timeline: Array.isArray(today.timeline) && today.timeline.length ? today.timeline : [{ type: 'idle', pct: 100 }],
    })
  },
})
