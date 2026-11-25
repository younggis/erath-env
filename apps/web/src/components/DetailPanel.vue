<script setup lang="ts">
import { computed } from 'vue'
import { store } from '../store'
import { cssColor } from '../palettes'
import { displayRangeFor } from '../earth'

const layer = computed(() => store.activeLayer.value)
// The 3D volume layer is a proxy density product without a numeric colour scale.
const isImageLayer = computed(() => layer.value?.layer_type === 'volume')
const range = computed(() => displayRangeFor(store.state.activeLayerId))
const gradient = computed(() => {
  const p = layer.value?.palette || 'default'
  return `linear-gradient(90deg, ${Array.from({ length: 12 }, (_, i) => cssColor(p, i / 11)).join(',')})`
})
const station = computed(() => {
  // A raycaster pick on a marker is authoritative.
  const id = store.state.focusedStationId
  if (id) return store.state.stations.find(s => s.station_id === id) || null
  const p = store.state.selected
  if (!p || !store.state.stations.length) return null
  const near = store.state.stations.map(st => ({
    st, d: Math.hypot(st.lon - p.lon, (st.lat - p.lat) / Math.max(0.2, Math.cos(p.lat * Math.PI / 180))),
  })).sort((a, b) => a.d - b.d)[0]
  return near && near.d < 2 ? near.st : null
})
const volcano = computed(() => store.focusedVolcano.value)
const disaster = computed(() => store.focusedDisaster.value)
const disasterArea = computed(() => {
  const p = disaster.value
  if (!p) return 0
  return (p.rings || []).reduce((sum, ring) => sum + Math.max(0, ring.length - 1), 0)
})
const airStation = computed(() => store.focusedAirStation.value)
const buoy = computed(() => store.focusedBuoy.value)
const buoyRows = computed(() => {
  const v = buoy.value?.values || {}
  return ([
    ['浪高', v.wave_height_m, 'm'],
    ['主导波周期', v.dominant_wave_period_s, 's'],
    ['平均波向', v.mean_wave_direction_deg, '°'],
    ['风速', v.wind_speed_ms, 'm/s'],
    ['阵风', v.gust_ms, 'm/s'],
    ['气压', v.pressure_hpa, 'hPa'],
    ['水温', v.water_temp_c, '°C'],
    ['气温', v.air_temp_c, '°C'],
  ] as Array<[string, number | null, string]>).filter(([, val]) => val !== null && val !== undefined)
})
const buoyAge = computed(() => {
  if (!buoy.value) return ''
  const minutes = Math.max(0, Math.round((Date.now() - new Date(buoy.value.observed_at).getTime()) / 60000))
  return minutes < 60 ? `${minutes} 分钟前` : `${Math.round(minutes / 60)} 小时前`
})

const event = computed(() => {
  const f = store.state.focusedEvent
  if (!f) return null
  return (store.state.realtimeEvents[f.source] || []).find(e => e.station_id === f.id) || null
})
const eventRows = computed(() => Object.entries(event.value?.values || {})
  .filter(([k]) => k !== 'report_url' && k !== 'geometry_url' && k !== 'link')
  .slice(0, 10))
const fmt = (v: any) => v === null || v === undefined ? '—' : typeof v === 'number' ? (Math.abs(v) < 0.001 && v !== 0 ? v.toExponential(2) : v.toFixed(2)) : (typeof v === 'object' ? JSON.stringify(v) : v)

// Forecast card: one value per available lead at the picked point.
const forecastPoints = computed(() => {
  const f = store.state.forecast
  if (!f || !f.points.length) return []
  const isWind = f.points.some(p => p.sample.values.some(v => v.id === 'wind'))
  return f.points.map(p => {
    let value: number | null = null
    let unit = ''
    if (isWind) {
      const w = p.sample.values.find(v => v.id === 'wind')
      value = typeof w?.value?.speed_ms === 'number' ? w.value.speed_ms : null
      unit = 'm/s'
    } else {
      const v = p.sample.values.find(x => x.id !== 'wind')
      value = typeof v?.display_value === 'number' ? v.display_value : null
      unit = v?.display_unit || v?.unit || ''
    }
    return { time: p.validTime, value, unit }
  })
})

const chart = computed(() => {
  const pts = forecastPoints.value
  const vals = pts.map(p => p.value).filter((v): v is number => v !== null)
  if (!vals.length) return null
  let min = Math.min(...vals), max = Math.max(...vals)
  if (max - min < 1e-6) { min -= 1; max += 1 }
  const pad = (max - min) * 0.15
  min -= pad; max += pad
  const W = 300, H = 96, pl = 4, pr = 4, tp = 8, pb = 16
  const x = (i: number) => pl + (i / Math.max(1, pts.length - 1)) * (W - pl - pr)
  const y = (v: number) => tp + (1 - (v - min) / (max - min)) * (H - tp - pb)
  const segs: string[] = []
  let cur: string[] = []
  pts.forEach((p, i) => {
    if (p.value === null) { if (cur.length > 1) segs.push(cur.join(' ')); cur = [] }
    else cur.push(`${x(i).toFixed(1)},${y(p.value).toFixed(1)}`)
  })
  if (cur.length > 1) segs.push(cur.join(' '))
  const dots = pts.map((p, i) => p.value === null ? null : { x: x(i), y: y(p.value), ...p })
    .filter((d): d is NonNullable<typeof d> => d !== null)
  return { W, H, segs, dots, min, max, unit: pts[0]?.unit || '' }
})

const timeLabel = (t: string) => t.slice(5, 16).replace('T', ' ')
const valFmt = (v: number | null) => v === null ? '—' : (Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1))
</script>

<template>
  <section class="detail">
    <div class="block">
      <div class="eyebrow">SELECTION</div>
      <h2>{{ layer?.label || '选择一个图层' }}</h2>
      <div class="sub" v-if="store.state.selected">
        {{ store.state.selected.lat.toFixed(3) }}°N · {{ store.state.selected.lon.toFixed(3) }}°E
        <span class="pill">{{ store.state.selected.valid_time }}</span>
      </div>
      <div class="sub" v-else>在地球上点击任意位置查看数值</div>
    </div>

    <div class="block values" v-if="store.state.selected">
      <div v-for="v in store.state.selected.values.filter(x => x.id !== 'wind')" :key="v.id" class="value-row">
        <span class="vname">{{ v.id }}</span>
        <span class="vval">{{ fmt(v.display_value) }} <em>{{ v.display_unit || v.unit }}</em></span>
      </div>
      <div v-for="v in store.state.selected.values.filter(x => x.id === 'wind')" :key="'wind'" class="wind-card">
        <div class="wind-title">10 m 风</div>
        <div class="wind-grid">
          <div><span>风速</span><b>{{ fmt(v.value?.speed_ms) }} m/s</b></div>
          <div><span>来向</span><b>{{ v.value?.direction_from_deg === null ? '静风' : fmt(v.value?.direction_from_deg) + '° ' + v.value?.compass }}</b></div>
        </div>
        <p>{{ store.state.selected.note }}</p>
      </div>
    </div>

    <div class="block" v-if="chart">
      <div class="eyebrow">FORECAST AT THIS POINT · {{ forecastPoints.length }} 时效</div>
      <svg class="chart" :viewBox="`0 0 ${chart.W} ${chart.H}`" preserveAspectRatio="none">
        <line :x1="4" :y1="chart.H - 16" :x2="chart.W - 4" :y2="chart.H - 16" stroke="rgba(255,255,255,.12)" />
        <polyline v-for="(s, i) in chart.segs" :key="i" :points="s" fill="none" stroke="var(--accent)" stroke-width="1.8" stroke-linejoin="round" />
        <circle v-for="(d, i) in chart.dots" :key="i" :cx="d.x" :cy="d.y" r="2.6" fill="#fff">
          <title>{{ timeLabel(d.time) }} · {{ valFmt(d.value) }} {{ chart.unit }}</title>
        </circle>
      </svg>
      <div class="chart-legend">
        <span>{{ timeLabel(forecastPoints[0].time) }}</span>
        <span>{{ chart.min.toFixed(1) }}–{{ chart.max.toFixed(1) }} {{ chart.unit }}</span>
        <span>{{ timeLabel(forecastPoints[forecastPoints.length - 1].time) }}</span>
      </div>
      <div class="fc-list">
        <div v-for="(p, i) in forecastPoints" :key="i"><span>{{ timeLabel(p.time) }}</span><b>{{ valFmt(p.value) }} {{ p.unit }}</b></div>
      </div>
    </div>

    <div class="block" v-if="volcano">
      <div class="eyebrow">GLOBAL VOLCANO</div>
      <h3>{{ volcano.name }}</h3>
      <div class="kv"><span>海拔</span><b>{{ fmt(volcano.elev) }} m</b></div>
      <div class="kv"><span>类型</span><b>{{ volcano.type || '—' }}</b></div>
      <div class="kv"><span>活动年代</span><b>{{ volcano.status || '—' }}</b></div>
      <div class="kv"><span>最近喷发（年代代码）</span><b>{{ volcano.last_code || '未知' }}</b></div>
      <div class="kv"><span>位置</span><b>{{ volcano.lat.toFixed(3) }}°, {{ volcano.lon.toFixed(3) }}°</b></div>
      <div class="sub">{{ volcano.country }} · {{ volcano.region }} · 熔岩脉动频率按最近喷发年代近似映射</div>
    </div>

    <div class="block" v-if="disaster">
      <div class="eyebrow">GDACS DISASTER ALERT</div>
      <h3>{{ disaster.name || disaster.event_class }}</h3>
      <div class="kv"><span>告警等级</span><b :style="{ color: disaster.alert_color }">{{ disaster.alert_level }}</b></div>
      <div class="kv"><span>灾种</span><b>{{ disaster.event_class }} ({{ disaster.event_type }})</b></div>
      <div class="kv"><span>影响范围</span><b>{{ (disaster.rings || []).length }} 个多边形 · {{ disasterArea }} 段边界</b></div>
      <p class="sub" v-if="disaster.description">{{ disaster.description }}</p>
      <div class="kv" v-if="disaster.report_url">
        <a :href="disaster.report_url" target="_blank" rel="noopener">官方报告 ↗</a>
      </div>
    </div>

    <div class="block" v-if="airStation">
      <div class="eyebrow">OPENAQ AIR QUALITY</div>
      <h3>{{ airStation.values?.station_name || airStation.station_id }}</h3>
      <div class="kv"><span>PM2.5</span><b>{{ fmt(airStation.values?.pm25_ugm3) }} µg/m³</b></div>
      <div class="kv"><span>PM2.5 AQI</span><b>{{ fmt(airStation.values?.aqi_pm25) }}</b></div>
      <div class="kv"><span>NO₂</span><b>{{ fmt(airStation.values?.no2_ugm3) }} µg/m³</b></div>
      <div class="kv"><span>O₃</span><b>{{ fmt(airStation.values?.o3_ugm3) }} µg/m³</b></div>
      <div class="kv"><span>传感器时间 (UTC)</span><b>{{ airStation.values?.sensor_time || '—' }}</b></div>
      <div class="sub">来源：OpenAQ v3 地面监测站 · 气体已归一化为 µg/m³</div>
    </div>

    <div class="block" v-if="buoy">
      <div class="eyebrow">NOAA NDBC BUOY</div>
      <h3>{{ buoy.station_id }}</h3>
      <div class="kv"><span>观测时刻 (UTC)</span><b>{{ buoy.observed_at }}</b></div>
      <div class="kv"><span>数据新鲜度</span><b class="ok">{{ buoyAge }}</b></div>
      <div class="kv" v-for="[name, val, unit] in buoyRows" :key="name">
        <span>{{ name }}</span><b>{{ fmt(val) }} {{ unit }}</b>
      </div>
      <div class="sub">来源：NOAA NDBC 实时浮标观测 · SI 单位 · 缺测项为 null</div>
    </div>

    <div class="block" v-if="event">
      <div class="eyebrow">REAL-TIME EVENT</div>
      <h3>{{ event.values?.name || event.values?.title || event.station_id }}</h3>
      <div class="kv"><span>来源</span><b>{{ event.source_id }}</b></div>
      <div class="kv"><span>观测时刻</span><b>{{ event.observed_at }}</b></div>
      <div class="kv"><span>位置</span><b>{{ event.lat.toFixed(2) }}°, {{ event.lon.toFixed(2) }}°</b></div>
      <template v-if="event.source_id === 'nasa_firms'">
        <div class="fire-card">
          <div><span>FRP 辐射功率</span><b>{{ fmt(event.values?.frp_mw) }} MW</b></div>
          <div><span>置信度</span><b>{{ event.values?.confidence || '—' }}</b></div>
          <div><span>卫星 / 昼夜</span><b>{{ event.values?.satellite || '—' }} · {{ event.values?.day_night || '—' }}</b></div>
        </div>
      </template>
      <div class="kv" v-for="[k, v] in eventRows.filter(([key]) => !['frp_mw','confidence','satellite','daynight'].includes(key))" :key="k"><span>{{ k }}</span><b>{{ fmt(v) }}</b></div>
      <div class="kv" v-if="event.values?.report_url || event.values?.link">
        <span>原文</span>
        <a :href="event.values?.report_url || event.values?.link" target="_blank" rel="noopener">打开 ↗</a>
      </div>
    </div>

    <div class="block" v-if="station">
      <div class="eyebrow">NEAREST STATION</div>
      <h3>{{ station.station_id }}</h3>
      <div class="kv"><span>观测时刻</span><b>{{ station.observed_at }}</b></div>
      <div class="kv"><span>气温 / 露点</span><b>{{ fmt(station.values?.temp_c) }} / {{ fmt(station.values?.dewpoint_c) }} °C</b></div>
      <div class="kv"><span>风</span><b>{{ fmt(station.values?.wind_speed_ms) }} m/s</b></div>
      <div class="kv"><span>能见度</span><b>{{ fmt(station.values?.visibility?.meters) }} m ({{ station.values?.visibility?.raw }})</b></div>
      <div class="kv" v-if="station.values?.weather_phenomena"><span>天气现象</span><b>{{ station.values.weather_phenomena }}</b></div>
    </div>

    <div class="block legend">
      <div class="eyebrow">LEGEND</div>
      <template v-if="!isImageLayer">
        <div class="bar" :style="{ background: gradient }"></div>
        <div class="bar-labels"><span>{{ range[0] }}</span><span>{{ layer?.display_unit || '' }}</span><span>{{ range[1] }}</span></div>
      </template>
      <div v-else class="sub">3D 体积云基于多层相对湿度的云密度代理（非真实云水含量），无数值色标；可用左侧密度滑块调节浓淡。</div>
      <div class="kv"><span>数据来源</span><b>{{ layer?.source_id || '—' }}</b></div>
      <div class="kv"><span>采样方式</span><b>{{ store.state.selected?.sampling_method || '—' }}</b></div>
      <div class="kv"><span>数据状态</span><b :class="layer?.source_kind === 'fixture' ? 'warn' : 'ok'">{{ layer?.source_kind === 'fixture' ? '演示样本' : '已发布' }}</b></div>
    </div>
  </section>
</template>

<style scoped>
.detail { padding: 18px 16px; overflow-y: auto; }
.eyebrow { font: 600 10px ui-monospace, monospace; letter-spacing: .16em; color: var(--accent); opacity: .75; }
h2 { margin: 6px 0; font-size: 17px; }
h3 { margin: 6px 0 12px; font-size: 14px; color: #8fe8c0; }
.sub { font-size: 11px; color: var(--muted); line-height: 1.8; }
.pill { display: inline-block; margin-left: 6px; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,.06); font-family: ui-monospace, monospace; }
.block { padding: 14px 0; border-bottom: 1px solid var(--line); }
.block:last-child { border: 0; }
.value-row { display: flex; justify-content: space-between; align-items: baseline; padding: 6px 0; }
.vname { font: 11px ui-monospace, monospace; color: var(--muted); text-transform: uppercase; }
.vval { font: 600 14px ui-monospace, monospace; color: var(--text); }
.vval em { font-style: normal; font-size: 10px; color: var(--muted); }
.wind-card { margin-top: 10px; padding: 10px; border-radius: 8px; background: rgba(94,200,255,.06); border: 1px solid rgba(94,200,255,.18); }
.wind-title { font-size: 11px; color: var(--accent); margin-bottom: 8px; }
.wind-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.wind-grid div { display: flex; flex-direction: column; gap: 3px; }
.wind-grid span { font-size: 10px; color: var(--muted); }
.wind-grid b { font: 600 12px ui-monospace, monospace; }
.wind-card p { font-size: 9.5px; color: var(--muted); margin: 8px 0 0; line-height: 1.5; }
.fire-card { margin: 10px 0; padding: 10px; border-radius: 8px; background: rgba(255,120,60,.07); border: 1px solid rgba(255,130,60,.22); display: grid; gap: 6px; }
.fire-card div { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--muted); }
.fire-card b { color: #ffb072; font: 600 12px ui-monospace, monospace; }
.kv { display: flex; justify-content: space-between; gap: 10px; font-size: 11px; padding: 5px 0; color: var(--muted); }
.kv b { color: var(--text); font-weight: 500; text-align: right; }
.kv a { color: var(--accent); font-size: 11px; text-decoration: none; }
.kv a:hover { text-decoration: underline; }
.kv b.ok { color: #6ef0b4; } .kv b.warn { color: #ffd479; }
.legend .bar { height: 10px; border-radius: 5px; margin: 12px 0 4px; border: 1px solid rgba(255,255,255,.12); }
.bar-labels { display: flex; justify-content: space-between; font: 10px ui-monospace, monospace; color: var(--muted); margin-bottom: 10px; }
.chart { width: 100%; height: 96px; display: block; margin-top: 10px; overflow: visible; }
.chart-legend { display: flex; justify-content: space-between; font: 10px ui-monospace, monospace; color: var(--muted); margin-bottom: 8px; }
.fc-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 10px; }
.fc-list div { display: flex; justify-content: space-between; gap: 6px; font: 10px ui-monospace, monospace; color: var(--muted); }
.fc-list b { color: var(--text); font-weight: 600; }
</style>
