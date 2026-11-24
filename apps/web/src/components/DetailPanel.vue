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
const fmt = (v: any) => v === null || v === undefined ? '—' : typeof v === 'number' ? (Math.abs(v) < 0.001 && v !== 0 ? v.toExponential(2) : v.toFixed(2)) : (typeof v === 'object' ? JSON.stringify(v) : v)
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
.kv { display: flex; justify-content: space-between; gap: 10px; font-size: 11px; padding: 5px 0; color: var(--muted); }
.kv b { color: var(--text); font-weight: 500; text-align: right; }
.kv b.ok { color: #6ef0b4; } .kv b.warn { color: #ffd479; }
.legend .bar { height: 10px; border-radius: 5px; margin: 12px 0 4px; border: 1px solid rgba(255,255,255,.12); }
.bar-labels { display: flex; justify-content: space-between; font: 10px ui-monospace, monospace; color: var(--muted); margin-bottom: 10px; }
</style>
