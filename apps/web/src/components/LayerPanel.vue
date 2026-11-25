<script setup lang="ts">
import { computed } from 'vue'
import { store } from '../store'
import { bundleKeysFor } from '../render/layerBundles'

const groups = computed(() => {
  const map: Record<string, any[]> = {}
  for (const l of store.state.layers) (map[l.kind] ||= []).push(l)
  return Object.entries(map)
})
const label: Record<string, string> = { forecast: '全球预报' }
const activeBundle = computed(() => bundleKeysFor(store.state.activeLayerId))
</script>

<template>
  <aside class="panel layer-panel">
    <div class="panel-head">
      <div>
        <div class="eyebrow">LAYERS</div>
        <h2>数据图层</h2>
      </div>
      <span class="mode-chip">在线</span>
    </div>

    <!-- Forecast layers: a layer expands its own effect controls when active. -->
    <div v-for="[kind, layers] in groups" :key="kind" class="group">
      <div class="group-title">{{ label[kind] || kind }} <span>{{ layers.length }}</span></div>
      <div v-for="l in layers" :key="l.layer_id">
        <button class="layer-item"
                :class="{ active: store.state.activeLayerId === l.layer_id }"
                @click="store.selectLayer(l.layer_id)">
          <span class="swatch" :style="{ background: `linear-gradient(90deg, var(--accent), var(--accent2))` }"></span>
          <span class="layer-name">{{ l.label }}</span>
          <span class="layer-unit">{{ l.display_unit }}</span>
        </button>
        <div v-if="store.state.activeLayerId === l.layer_id && activeBundle.length" class="bundle">
          <template v-if="activeBundle.includes('showParticles')">
            <label class="row"><span>风粒子</span><input type="checkbox" v-model="store.state.showParticles" /></label>
            <label class="row"><span>GPU 粒子流（WebGL2）</span><input type="checkbox" v-model="store.state.useGpuWind" /></label>
            <label class="row"><span>风场拖尾光带</span><input type="checkbox" v-model="store.state.showTrails" /></label>
            <label class="row col"><span>粒子数量 <b>{{ store.state.particleCount }}</b></span>
              <input type="range" min="1000" max="30000" step="1000" v-model.number="store.state.particleCount" /></label>
          </template>
          <label v-if="activeBundle.includes('showJet')" class="row">
            <span>500 hPa 高空风丝带</span><input type="checkbox" v-model="store.state.showJet" />
          </label>
          <template v-if="activeBundle.includes('showVolume')">
            <label class="row"><span>☁ 3D 体积云显示</span><input type="checkbox" v-model="store.state.showVolume" /></label>
            <label class="row col" v-if="store.state.showVolume"><span>云密度 <b>{{ store.state.volumeDensity.toFixed(2) }}</b></span>
              <input type="range" min="0.01" max="0.3" step="0.01" v-model.number="store.state.volumeDensity" /></label>
          </template>
        </div>
      </div>
    </div>

    <div class="divider"></div>
    <div class="group-title">显示设置</div>
    <label class="row"><span>数据显示 (色带)</span><input type="checkbox" v-model="store.state.showField" /></label>
    <label class="row"><span>自动高分辨率 LOD</span><input type="checkbox" v-model="store.state.autoHiRes" /></label>
    <p class="hint">放大到美国区域（HRRR 3km 覆盖）时自动加载高分辨率数据场；其余地区用 GFS 0.25°（25km）。</p>
    <label class="row col"><span>图层不透明度 <b>{{ Math.round(store.state.layerOpacity * 100) }}%</b></span>
      <input type="range" min="0.1" max="1" step="0.05" v-model.number="store.state.layerOpacity" /></label>

    <div class="divider"></div>
    <div class="group-title">观测与事件</div>
    <p class="hint" v-if="store.state.realtimeSummary">
      Kp {{ store.state.realtimeSummary.kp ?? '—' }} · 太阳风 {{ store.state.realtimeSummary.solar_wind?.speed_kms ?? '—' }} km/s ·
      Bz {{ store.state.realtimeSummary.solar_wind?.bz_gsm ?? '—' }} nT ·
      更新 {{ store.state.realtimeUpdatedAt ? new Date(store.state.realtimeUpdatedAt).toLocaleTimeString() : '—' }}
    </p>
    <label class="row"><span>站点标记</span><input type="checkbox" v-model="store.state.showStations" /></label>
    <label class="row"><span>海洋浮标 (NDBC)</span><input type="checkbox" v-model="store.state.showBuoys" /></label>
    <label class="row"><span>空气质量站 (OpenAQ)</span><input type="checkbox" v-model="store.state.showAirQuality" /></label>
    <label class="row"><span>⚡ 实时闪电 (Blitzortung)</span><input type="checkbox" v-model="store.state.showLightning" /></label>
    <label class="row"><span>🌌 极光光幕 (OVATION)</span><input type="checkbox" v-model="store.state.showAurora" /></label>
    <label class="row"><span>💨 太阳风粒子流</span><input type="checkbox" v-model="store.state.showSolarWind" /></label>
    <label class="row"><span>🌋 实时地震冲击波</span><input type="checkbox" v-model="store.state.showQuakes" /></label>
    <label class="row"><span>✈️ 实时航班流</span><input type="checkbox" v-model="store.state.showFlights" /></label>
    <label class="row"><span>🌀 热带气旋</span><input type="checkbox" v-model="store.state.showStorms" /></label>
    <label class="row"><span>☀️ 日冕物质抛射 CME</span><input type="checkbox" v-model="store.state.showCme" /></label>
    <label class="row"><span>🌐 全球灾害预警 (GDACS/EONET)</span><input type="checkbox" v-model="store.state.showDisasters" /></label>
    <label class="row"><span>灾害影响范围 (GDACS)</span><input type="checkbox" v-model="store.state.showDisasterPolygons" /></label>
    <label class="row"><span>🔥 NASA FIRMS 全球火点</span><input type="checkbox" v-model="store.state.showFires" /></label>
    <label class="row"><span>🛰️ 全球气旋轨迹</span><input type="checkbox" v-model="store.state.showTracks" /></label>
    <label class="row"><span>卫星轨道与视锥 (CelesTrak)</span><input type="checkbox" v-model="store.state.showSatellites" /></label>
    <p class="hint">GDACS 覆盖全球气旋/洪水/火山/干旱/野火；FIRMS 需配置免费 MAP_KEY，未配置时可看 EONET 野火事件。数据每 60s 自动刷新。</p>

    <div class="divider"></div>
    <div class="group-title">静态专题图层</div>
    <label class="row"><span>海底光缆与登陆站</span><input type="checkbox" v-model="store.state.showCables" /></label>
    <label class="row"><span>🌋 板块边界与熔岩脉动</span><input type="checkbox" v-model="store.state.showTectonics" /></label>
    <label class="row"><span>🌋 3D 火山锥体</span><input type="checkbox" v-model="store.state.showVolcanoes" /></label>
    <label class="row"><span>✈ 全球航线流光网络</span><input type="checkbox" v-model="store.state.showRoutes" /></label>
    <label class="row col" v-if="store.state.showRoutes"><span>航线密度 <b>{{ Math.round(store.state.routeDensity * 100) }}%</b></span>
      <input type="range" min="0.05" max="1" step="0.05" v-model.number="store.state.routeDensity" /></label>
    <label class="row"><span>💧 全球水系荧光脉络</span><input type="checkbox" v-model="store.state.showRivers" /></label>
    <label class="row"><span>⚡ 全球电厂能量光柱</span><input type="checkbox" v-model="store.state.showPowerPlants" /></label>
    <label class="row col" v-if="store.state.showPowerPlants"><span>能源类型筛选</span>
      <select v-model="store.state.powerFuelFilter">
        <option value="all">全部 ({{ store.state.powerPlants?.plants.length ?? 0 }} 座)</option>
        <option v-for="f in (store.state.powerPlants?.fuels ?? [])" :key="f" :value="f">{{ f }}</option>
      </select></label>
    <label class="row"><span>局部地形 (DEM)</span><input type="checkbox" v-model="store.state.showTerrain" /></label>
    <label class="row col" v-if="store.state.showTerrain"><span>地形夸张 <b>×{{ store.state.terrainExaggeration }}</b></span>
      <input type="range" min="0.5" max="8" step="0.5" v-model.number="store.state.terrainExaggeration" /></label>

    <div class="divider"></div>
    <div class="group-title">✦ 视觉特效</div>
    <label class="row col"><span>夜间城市灯光 <b>{{ store.state.nightLights.toFixed(1) }}</b></span>
      <input type="range" min="0" max="3" step="0.1" v-model.number="store.state.nightLights" /></label>
    <label class="row"><span>🌊 海洋黄金航道夜光 (World Bank AIS)</span><input type="checkbox" v-model="store.state.showShippingLights" /></label>
    <label class="row col"><span>流动云层 <b>{{ Math.round(store.state.cloudStrength * 100) }}%</b></span>
      <input type="range" min="0" max="1" step="0.05" v-model.number="store.state.cloudStrength" /></label>
    <label class="row"><span>高清卫星瓦片 (Esri)</span><input type="checkbox" v-model="store.state.hdTiles" /></label>
    <p class="hint">开启后按缩放级别动态加载 Esri World Imagery 瓦片（z{{ store.state.tileInfo.zoom }}，约 {{ store.state.tileInfo.resolutionM < 10 ? store.state.tileInfo.resolutionM.toFixed(1) : Math.round(store.state.tileInfo.resolutionM) }} m/像素），可放大到区县/街道级。 imagery © Esri, Maxar。</p>
    <label class="row"><span>电影感调色（暗角/色差）</span><input type="checkbox" v-model="store.state.cinematicGrade" /></label>
    <label class="row"><span>Bloom 辉光</span><input type="checkbox" v-model="store.state.bloom" /></label>
    <label class="row col"><span>辉光强度 <b>{{ store.state.bloomStrength.toFixed(2) }}</b></span>
      <input type="range" min="0" max="2" step="0.05" v-model.number="store.state.bloomStrength" /></label>
    <label class="row"><span>昼夜跟随真实 UTC</span><input type="checkbox" :checked="!store.state.simTime" @change="store.state.simTime = ($event.target as HTMLInputElement).checked ? null : store.currentTime.value" /></label>
    <p class="hint">☀ 太阳直射点：{{ store.state.sunInfo.lat.toFixed(1) }}°, {{ store.state.sunInfo.lon.toFixed(1) }}°（{{ store.state.sunInfo.at.slice(11, 19) || '实时' }}）</p>
    <p class="hint">昼夜分界、晨昏线与城市灯光按真实太阳位置实时计算，非手绘特效。取消勾选可让昼夜跟随图层数据时刻。</p>

    <div class="divider"></div>
    <div class="group-title">实时数据源</div>
    <div v-if="store.state.dataStatus" class="live-summary" :class="store.state.dataStatus.all_live ? 'all-live' : 'partial'">
      {{ store.state.dataStatus.all_live ? '● 全部实时' : '◐ 部分实时' }}
      <span class="clock-s">{{ store.state.dataStatus.server_time.slice(11,19) }} UTC</span>
    </div>
    <div class="source-status" v-for="d in store.state.dataStatus?.datasets || []" :key="d.dataset_id">
      <span class="sid">{{ d.dataset_id }}</span>
      <span :class="d.fresh ? 'good' : 'bad'">{{ d.fresh ? `实时 ${d.age_minutes}m前` : (d.state === 'missing' ? '缺失' : '过期') }}</span>
      <span class="stime">{{ d.timestamp ? d.timestamp.slice(5,16) : '—' }}</span>
    </div>
    <p class="hint">{{ store.state.dataStatus?.note }}</p>
    <div class="sources">
      <button @click="store.refreshSource('noaa_gfs')">刷新 GFS</button>
      <button @click="store.refreshSource('awc_metar')">刷新站点</button>
      <button @click="store.refreshSource('gfs_volume')">刷新体积云</button>
    </div>
    <p class="status">{{ store.state.status }}</p>
  </aside>
</template>

<style scoped>
.panel { padding: 18px 14px; overflow-y: auto; }
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 18px; }
.eyebrow { font: 600 10px ui-monospace, monospace; letter-spacing: .18em; color: var(--accent); opacity: .7; }
h2 { margin: 4px 0 0; font-size: 17px; font-weight: 650; letter-spacing: .02em; }
.mode-chip { font-size: 10px; padding: 4px 8px; border-radius: 999px; border: 1px solid rgba(110, 240, 180, .4); color: #6ef0b4; }
.group { margin-bottom: 14px; }
.group-title { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: .1em; margin: 10px 4px 8px; display: flex; justify-content: space-between; }
.group-title span { opacity: .5; }
.layer-item {
  width: 100%; display: flex; align-items: center; gap: 9px; padding: 9px 10px; margin-bottom: 4px;
  border: 1px solid transparent; border-radius: 8px; background: rgba(255,255,255,.025);
  color: var(--text); cursor: pointer; text-align: left; transition: .16s;
}
.layer-item:hover { background: rgba(255,255,255,.06); }
.layer-item.active { background: rgba(94, 200, 255, .1); border-color: rgba(94, 200, 255, .35); }
.swatch { width: 22px; height: 4px; border-radius: 2px; flex: none; }
.layer-name { flex: 1; font-size: 12.5px; }
.layer-unit { font: 10px ui-monospace, monospace; color: var(--muted); }
.bundle { margin: 2px 0 10px 10px; padding: 6px 8px; border-left: 2px solid rgba(94,200,255,.35); background: rgba(94,200,255,.04); border-radius: 0 6px 6px 0; }
.divider { height: 1px; background: var(--line); margin: 16px 0 4px; }
.row { display: flex; align-items: center; justify-content: space-between; font-size: 12px; padding: 6px 4px; color: var(--muted); }
.row.col { flex-direction: column; align-items: stretch; gap: 6px; }
.row b { color: var(--text); font-weight: 600; }
.row input[type=range] { accent-color: var(--accent); width: 100%; }
.row select { width: 100%; padding: 4px 6px; font-size: 12px; color: var(--text); background: #0b1220; border: 1px solid rgba(255,255,255,.14); border-radius: 6px; }
.sources { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
.sources button { font-size: 11px; padding: 7px 6px; border-radius: 6px; border: 1px solid var(--line); background: rgba(255,255,255,.03); color: var(--muted); cursor: pointer; }
.sources button:hover { border-color: var(--accent); color: var(--accent); }
.live-summary { font: 600 11px ui-monospace, monospace; padding: 6px 8px; border-radius: 6px; margin-bottom: 6px; }
.live-summary.all-live { color: #6ef0b4; background: rgba(110,240,180,.10); }
.live-summary.partial { color: #ffd479; background: rgba(255,212,121,.10); }
.clock-s { float: right; color: var(--muted); font-weight: 400; }
.source-status { display: grid; grid-template-columns: 1fr auto auto; gap: 6px; font: 10px ui-monospace, monospace; padding: 4px 2px; border-bottom: 1px solid rgba(255,255,255,.04); }
.sid { color: var(--text); }
.good { color: #6ef0b4; } .bad { color: #ff8b8b; }
.stime { color: var(--muted); }
.hint { font-size: 9.5px; color: var(--muted); line-height: 1.5; margin: 6px 2px; }
.status { font-size: 10.5px; color: var(--muted); line-height: 1.5; margin: 10px 4px; word-break: break-all; }
</style>
