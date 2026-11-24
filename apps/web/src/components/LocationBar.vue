<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { store } from '../store'

const query = ref('')
const msg = ref('')
const KEY = 'earthsim.savedRegions'

onMounted(() => {
  try { store.state.savedRegions = JSON.parse(localStorage.getItem(KEY) || '[]') } catch { /* ignore */ }
})

function parse(): { lon: number; lat: number } | null {
  const parts = query.value.split(/[\s,，]+/).filter(Boolean).map(Number)
  if (parts.length < 2 || parts.some(x => !Number.isFinite(x))) return null
  const lon = parts[0], lat = parts[1]
  if (lon < -180 || lon > 180 || lat < -90 || lat > 90) return null
  return { lon, lat }
}

function locate() {
  const p = parse()
  if (!p) { msg.value = '请输入经度,纬度（如 139.7, 35.5）'; return }
  store.state.focusRequest = { ...p, distance: 3.4 }
  store.state.focusedStationId = ''
  msg.value = `定位到 ${p.lat.toFixed(2)}°, ${p.lon.toFixed(2)}°`
}

function save() {
  const p = parse()
  if (!p) { msg.value = '请先输入有效坐标'; return }
  const name = query.value.trim()
  const list = store.state.savedRegions
  if (!list.some(r => Math.abs(r.lon - p.lon) < 0.01 && Math.abs(r.lat - p.lat) < 0.01)) {
    list.push({ name, lon: p.lon, lat: p.lat, distance: 3.4 })
    localStorage.setItem(KEY, JSON.stringify(list))
  }
  msg.value = '已保存为常用区域'
}

function goto(r: { lon: number; lat: number; distance?: number }) {
  store.state.focusRequest = { ...r }
  msg.value = ''
}
function remove(index: number) {
  store.state.savedRegions.splice(index, 1)
  localStorage.setItem(KEY, JSON.stringify(store.state.savedRegions))
}
</script>

<template>
  <div class="location-bar">
    <span class="label">定位</span>
    <input v-model="query" placeholder="经度, 纬度  例：139.7, 35.5" @keyup.enter="locate" />
    <button class="primary" @click="locate">前往</button>
    <button @click="save" title="保存当前坐标">☆ 保存</button>
    <div v-if="store.state.savedRegions.length" class="favorites">
      <span v-for="(r, i) in store.state.savedRegions" :key="i" class="fav">
        <a @click="goto(r)">{{ r.name }}</a>
        <small @click="remove(i)">×</small>
      </span>
    </div>
    <span v-if="msg" class="msg">{{ msg }}</span>
  </div>
</template>

<style scoped>
.location-bar { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; padding: 6px 12px; border-bottom: 1px solid var(--line); background: rgba(10, 18, 30, .75); }
.label { font: 600 10px ui-monospace, monospace; letter-spacing: .12em; color: var(--accent); }
input { width: 200px; background: rgba(255,255,255,.05); border: 1px solid var(--line); border-radius: 6px; padding: 6px 8px; color: var(--text); font-size: 11px; }
button { padding: 6px 9px; font-size: 11px; border-radius: 6px; border: 1px solid var(--line); background: rgba(255,255,255,.04); color: var(--muted); cursor: pointer; }
button.primary { background: var(--accent); color: #04121d; border-color: transparent; font-weight: 700; }
.msg { font-size: 10px; color: #6ef0b4; }
.favorites { display: flex; gap: 6px; align-items: center; }
.fav { display: inline-flex; align-items: center; gap: 2px; padding: 3px 6px; border-radius: 5px; background: rgba(94,200,255,.08); font-size: 10px; }
.fav a { color: var(--accent); cursor: pointer; max-width: 120px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fav small { color: var(--muted); cursor: pointer; margin-left: 2px; }
</style>
