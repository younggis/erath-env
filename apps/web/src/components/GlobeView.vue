<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { store } from '../store'
import { api, type Frame } from '../api'
import { EarthRenderer } from '../render/scene'
import { RANGES } from '../palettes'
import type { FieldData, WindData } from '../render/types'

const host = ref<HTMLDivElement | null>(null)
const hud = ref('')
const stats = ref('')
const warning = ref('')
// Central switch toast: makes layer changes unmistakable even when two
// layers look similar or the new grid takes seconds to download.
const toastVisible = ref(false)
const toastLabel = ref('')
const toastLoading = ref(false)
let toastTimer = 0
let renderer: EarthRenderer | null = null
let windFrames: Frame[] = []
let windSourceId = 'wind10'
let windFrameId = ''
let downAt: { x: number; y: number } | null = null

async function loadBasemap() {
  // Prefer a real satellite image; fall back to the offline Natural Earth
  // vector basemap if the image is unavailable.
  renderer?.setSatelliteBasemap('/earth-day.jpg', async () => {
    try {
      const res = await fetch('/land110m.json')
      renderer?.setBasemap(await res.json())
    } catch { warning.value = '底图未加载；地球仍可交互' }
  })
}

async function refreshWindFrames() {
  const active = store.state.activeLayerId
  const candidate = active.startsWith('wave_') ? 'wave_drift' : 'wind10'
  for (const id of [candidate, 'wind10']) {
    try {
      const res = await api.frames(id)
      if (res.frames.length) {
        if (windSourceId !== id) windFrameId = ''
        windSourceId = id
        windFrames = res.frames
        return
      }
    } catch { /* try the next source */ }
  }
  windSourceId = 'wind10'
  windFrames = []
}

async function loadJet() {
  if (!renderer) return
  try {
    const res = await api.frames('wind500')
    const fr = res.frames[0]
    if (!fr) { renderer.setJet(null); return }
    const m = await api.manifest(fr.frame_id)
    const a = (m.assets || []).find((x: any) => x.role === 'grid')
    if (!a) { renderer.setJet(null); return }
    const buf = await api.asset((a.href || '').split('/').pop() || '')
    const g = m.grid
    const data: WindData = {
      values: new Float32Array(buf),
      grid: { nx: g.nx, ny: g.ny, lon0: g.lon0, lat0: g.lat0, dx: g.dx, dy: g.dy, wrap_longitude: !!g.wrap_longitude },
      ncomp: (m.fields || []).length,
    }
    renderer.setJet(data)
    renderer.setJetVisible(store.state.showJet)
  } catch { renderer.setJet(null) }
}

async function updateWindForTime(time: string) {
  if (!windFrames.length) {
    renderer?.setWind(null)
    warning.value = '当前无风场数据，粒子已隐藏（不显示合成风场）'
    return
  }
  const target = windFrames.reduce((best, f) =>
    Math.abs(+new Date(f.valid_time) - +new Date(time)) < Math.abs(+new Date(best.valid_time) - +new Date(time))
      ? f : best, windFrames[0])
  if (target.frame_id === windFrameId) return
  windFrameId = target.frame_id
  try {
    const m = await api.manifest(target.frame_id)
    const a = (m.assets || []).find((x: any) => x.role === 'grid')
    if (!a) { renderer?.setWind(null); return }
    const buf = await api.asset((a.href || '').split('/').pop() || '')
    const g = m.grid
    const data: WindData = {
      values: new Float32Array(buf),
      grid: { nx: g.nx, ny: g.ny, lon0: g.lon0, lat0: g.lat0, dx: g.dx, dy: g.dy, wrap_longitude: !!g.wrap_longitude },
      ncomp: (m.fields || []).length,
    }
    renderer?.setWind(data)
    warning.value = ''
  } catch {
    renderer?.setWind(null)
    warning.value = '风场数据读取失败'
  }
}

async function loadTerrain() {
  if (!renderer) return
  try {
    const res = await api.frames('terrain')
    const fr = res.frames[0]
    if (!fr) { renderer.setTerrain(null); return }
    const m = await api.manifest(fr.frame_id)
    const a = (m.assets || []).find((x: any) => x.role === 'grid')
    if (!a) { renderer.setTerrain(null); return }
    const buf = await api.asset((a.href || '').split('/').pop() || '')
    const g = m.grid
    const b = m.bbox || fr.bbox
    renderer.setTerrain({
      grid: { nx: g.nx, ny: g.ny, lon0: g.lon0, lat0: g.lat0, dx: g.dx, dy: g.dy, wrap_longitude: false },
      values: new Float32Array(buf),
      exaggeration: store.state.terrainExaggeration,
    }, [b.west ?? b[0], b.south ?? b[1], b.east ?? b[2], b.north ?? b[3]])
    renderer.setTerrainVisible(store.state.showTerrain)
  } catch { renderer.setTerrain(null) }
}

/** Hide every data overlay, leaving only the basemap — used the instant a
 *  layer switch begins so a slow load is visibly "loading", not a stuck view. */
function clearRenderedLayers() {
  if (!renderer) return
  renderer.setField(null)
  renderer.setRegionField(null)
  renderer.setImagePatch(null)
  renderer.setVolume(null)
}

async function updateLayers() {
  if (!renderer) return
  const frame = store.currentFrame.value
  const layer = store.activeLayer.value
  // During a layer switch activeLayerId changes before frames[] is replaced,
  // so currentFrame can briefly still belong to the previous layer. Skip that
  // transient state — the frame_id watch will re-run once frames[] updates.
  if (frame && layer && frame.layer_id !== layer.layer_id) return
  if (!frame || !layer) {
    clearRenderedLayers()
    hud.value = '暂无可用图层'
    return
  }
  // Volumetric cloud: raymarched 3D density, not a surface texture.
  if (layer.layer_type === 'volume') {
    const vol = store.state.volumeCache.get(frame.frame_id)
    if (vol) {
      renderer.setField(null)
      renderer.setRegionField(null)
      renderer.setImagePatch(null)
      renderer.setVolume(vol)
      renderer.setVolumeVisible(store.state.showVolume)
      renderer.setVolumeDensity(store.state.volumeDensity)
      hud.value = `${layer.label} · ${frame.valid_time} · ${vol.nx}×${vol.ny}×${vol.nz} 体素 · NOAA NCEP`
    } else {
      clearRenderedLayers()
      hud.value = '正在加载图层…'
    }
    return
  }
  renderer.setVolume(null)
  const cached = store.state.gridCache.get(frame.frame_id)
  // Feed real significant wave height into the ocean shader when that layer is
  // active; other layers restore the default calm-ocean appearance.
  renderer?.setWaveField(frame.layer_id === 'wave_height' && cached
    ? cached.values : null, cached?.grid.nx || 0, cached?.grid.ny || 0)
  if (cached) {
    // Render the FULL gridded field as a continuous colour band for every
    // scalar/vector layer — including wind. This is the actual high-density
    // model data (GFS is 1441x721); particles are an additional overlay.
    const palette = layer.palette || 'default'
    let range: [number, number] = RANGES[frame.layer_id] || [0, 1]
    // API stores temperature in K but the colour scales are expressed in °C.
    if (layer.unit === 'K' && range[0] < 100) {
      range = [range[0] + 273.15, range[1] + 273.15]
    }
    const field: FieldData = {
      frameId: frame.frame_id,
      layerId: frame.layer_id,
      palette,
      range,
      grid: cached.grid,
      ncomp: cached.ncomp,
      values: cached.values,
      vector: frame.layer_id.includes('wind'),
      validTime: frame.valid_time,
    }
    // Global fields render on the sphere; regional fields (e.g. HRRR 3 km)
    // must be draped on their own bbox patch, never stretched over the globe.
    const g = cached.grid
    const isGlobal = !!g.wrap_longitude ||
      (Math.abs(g.lon0 + 180) < 1 && Math.abs((g.nx - 1) * g.dx - 360) < 1)
    if (isGlobal) {
      renderer.setRegionField(null)
      renderer.setField(field)
      renderer.setFieldVisible(store.state.showField)
      // Wind field is the primary data layer: render it more opaquely so the
      // full 1441x721 grid reads clearly; scalars stay translucent for basemap.
      renderer.setFieldOpacity(store.state.layerOpacity)
    } else {
      renderer.setField(null)
      const bbox: [number, number, number, number] = [
        g.lon0, g.lat0, g.lon0 + (g.nx - 1) * g.dx, g.lat0 + (g.ny - 1) * g.dy,
      ]
      renderer.setRegionField(field, bbox)
    }
    renderer.setImagePatch(null)
    const gridInfo = `${cached.grid.nx}×${cached.grid.ny}`
    hud.value = `${layer.label} · ${frame.valid_time} · ${gridInfo} 格点 · ${layer.attribution || layer.source_id}`
  } else if (store.state.imageCache.has(frame.frame_id)) {
    renderer.setField(null)
    renderer.setRegionField(null)
    try {
      const m = await api.manifest(frame.frame_id)
      // bbox may be [w,s,e,n] or {west,south,east,north}; never fall back to
      // the whole globe — that misplaces a regional satellite image.
      let b: number[] | null = null
      if (Array.isArray(m.bbox) && m.bbox.length === 4) b = m.bbox
      else if (m.bbox && typeof m.bbox === 'object')
        b = [m.bbox.west, m.bbox.south, m.bbox.east, m.bbox.north]
      if (!b || b.some(v => !Number.isFinite(v))) {
        hud.value = '该卫星图缺少地理范围，无法配准'
        return
      }
      renderer.setImagePatch(store.state.imageCache.get(frame.frame_id)!, b as [number, number, number, number])
      hud.value = `${layer.label} · ${frame.valid_time} · ${layer.attribution || 'JMA / NOAA'}`
    } catch { hud.value = '卫星图加载失败' }
  } else {
    // Data for the new layer is still downloading — keep overlays cleared so
    // the basemap shows through and it's obvious the view is loading.
    clearRenderedLayers()
    hud.value = '正在加载图层…'
  }
  await updateWindForTime(store.currentTime.value)
}

function onPointerUp(event: PointerEvent) {
  if (!renderer || event.button !== 0 || !downAt) return
  const moved = Math.hypot(event.clientX - downAt.x, event.clientY - downAt.y)
  downAt = null
  if (moved > 4) return // a rotation, not a click
  const hit = renderer.pick(event.clientX, event.clientY)
  if (!hit) return
  if (hit.station) {
    hud.value = `站点 ${hit.station.id} · ${hit.station.lat.toFixed(2)}°, ${hit.station.lon.toFixed(2)}°`
    // Ask DetailPanel to show this exact station.
    store.state.focusedStationId = hit.station.id
    store.state.focusedEvent = null
    store.queryPoint(hit.station.lon, hit.station.lat)
  } else {
    const picked = renderer.pickEvent(event.clientX, event.clientY)
    if (picked) {
      const ev = picked.event
      hud.value = `事件 ${ev.station_id} · ${ev.lat.toFixed(2)}°, ${ev.lon.toFixed(2)}°`
      store.state.focusedStationId = ''
      store.state.focusedEvent = { source: ev.source_id as any, id: ev.station_id }
      store.queryPoint(ev.lon, ev.lat)
      return
    }
    hud.value = `${hit.lat.toFixed(2)}°, ${hit.lon.toFixed(2)}°`
    store.state.focusedStationId = ''
    store.state.focusedEvent = null
    // Pick the nearest NDBC buoy when the overlay is enabled.
    store.state.focusedBuoyId = ''
    if (store.state.showBuoys && store.state.buoys.length) {
      const near = store.state.buoys.map(b => ({
        b, d: Math.hypot(b.lon - hit.lon,
          (b.lat - hit.lat) / Math.max(0.2, Math.cos(hit.lat * Math.PI / 180))),
      })).sort((a, z) => a.d - z.d)[0]
      if (near && near.d < 2.5) {
        store.state.focusedBuoyId = near.b.station_id
        hud.value = `浮标 ${near.b.station_id} · ${near.b.lat.toFixed(2)}°, ${near.b.lon.toFixed(2)}°`
      }
    }
    // Nearest OpenAQ station when the air-quality overlay is enabled.
    store.state.focusedAirStationId = ''
    if (store.state.showAirQuality && store.state.airQuality.length) {
      const nearAQ = store.state.airQuality.map(s => ({
        s, d: Math.hypot(s.lon - hit.lon,
          (s.lat - hit.lat) / Math.max(0.2, Math.cos(hit.lat * Math.PI / 180))),
      })).sort((a, z) => a.d - z.d)[0]
      if (nearAQ && nearAQ.d < 1.5) {
        store.state.focusedAirStationId = nearAQ.s.station_id
        if (!store.state.focusedBuoyId) {
          hud.value = `空气站 ${nearAQ.s.station_id} · ${nearAQ.s.lat.toFixed(2)}°, ${nearAQ.s.lon.toFixed(2)}°`
        }
      }
    }
    // GDACS impact polygon (approximate via first ring vertex).
    store.state.focusedDisasterId = ''
    if (store.state.showDisasterPolygons && store.state.disasterPolygons.length) {
      const nearPoly = store.state.disasterPolygons.map(p => {
        const pt = p.rings?.[0]?.[0] || [0, 0]
        return { p, d: Math.hypot(pt[0] - hit.lon,
          (pt[1] - hit.lat) / Math.max(0.2, Math.cos(hit.lat * Math.PI / 180))) }
      }).sort((a, z) => a.d - z.d)[0]
      if (nearPoly && nearPoly.d < 8) {
        store.state.focusedDisasterId = nearPoly.p.event_id
        if (!store.state.focusedBuoyId && !store.state.focusedAirStationId) {
          hud.value = `${nearPoly.p.alert_level} ${nearPoly.p.event_class} · ${nearPoly.p.name}`
        }
      }
    }
    store.queryPoint(hit.lon, hit.lat)
  }
}

// Automatic data LOD: when the view is over the HRRR domain and zoomed in,
// overlay the 3km data instead of the coarse 25km global field.
let hiresLoading = false
let hiresKey = ''
async function updateDataLOD(lon: number, lat: number, distance: number) {
  if (!renderer) return
  const inHRRR = lon >= -102 && lon <= -74 && lat >= 32 && lat <= 52
  const zoomed = distance < 4.5
  // When HRRR itself is the active layer it already renders as a regional
  // patch; only overlay it on top of the coarse global wind layer.
  const wantHi = store.state.autoHiRes && inHRRR && zoomed &&
                 store.state.activeLayerId === 'wind10'
  const key = wantHi ? 'hrrr' : 'none'
  if (key === hiresKey) return
  hiresKey = key
  if (!wantHi) {
    renderer.setHiResField(null)
    store.state.hiresInfo = { active: false, resolutionKm: 25, layer: store.state.activeLayerId }
    return
  }
  if (hiresLoading) return
  hiresLoading = true
  const info = await store.loadHiResData()
  hiresLoading = false
  if (info && hiresKey === 'hrrr') {
    const g = store.state.gridCache.get(info.frameId)
    if (g) {
      renderer.setHiResField({
        frameId: info.frameId, layerId: 'hrrr_wind10', palette: 'wind',
        range: [0, 30], grid: g.grid, ncomp: info.ncomp, values: g.values, vector: true,
      }, info.bbox)
      store.state.hiresInfo = { active: true, resolutionKm: 3, layer: 'hrrr_wind10' }
    }
  }
}

function onPointerDown(event: PointerEvent) {
  downAt = { x: event.clientX, y: event.clientY }
}

onMounted(async () => {
  if (!host.value) return
  renderer = new EarthRenderer(host.value)
  ;(window as any).__earthRenderer = renderer
  ;(window as any).__store = store
  renderer.start()
  renderer.setViewChangeListener((lon, lat, dist) => updateDataLOD(lon, lat, dist))
  renderer.setPlaying(store.state.playing, (dt) => store.advance(dt))
  renderer.setWindCount(store.state.particleCount)
  renderer.setWindSpeed(store.state.speed)
  renderer.setWindVisible(store.state.showParticles)
  renderer.setGPUWindEnabled(store.state.useGpuWind)
  renderer.setWindTrailsVisible(store.state.showTrails)
  renderer.setBuoysVisible(store.state.showBuoys)
  renderer.setStationsVisible(store.state.showStations)
  renderer.setFieldOpacity(store.state.layerOpacity)
  renderer.setFieldVisible(store.state.showField)
  renderer.setImageOpacity(store.state.layerOpacity)
  renderer.setTerrainExaggeration(store.state.terrainExaggeration)
  renderer.setNightLights(store.state.nightLights)
  renderer.setCloudStrength(store.state.cloudStrength)
  renderer.setCinematicGrade(store.state.cinematicGrade)
  renderer.setBloom(store.state.bloom)
  renderer.setBloomStrength(store.state.bloomStrength)
  renderer.setTilesEnabled(store.state.hdTiles)
  renderer.setSimulationTime(store.state.simTime ? new Date(store.state.simTime) : null)
  store.state.sunInfo = { ...renderer.subSolarPoint }
  // NDBC buoy overlay is independent of the selected forecast layer.
  store.loadBuoys().then(() => {
    renderer?.setBuoys(store.state.buoys)
    renderer?.setBuoysVisible(store.state.showBuoys)
  })
  renderer.setLightningVisible(store.state.showLightning)
  renderer.setAirQualityVisible(store.state.showAirQuality)
  renderer.setDisasterPolygonsVisible(store.state.showDisasterPolygons)
  renderer.setSatellitesVisible(store.state.showSatellites)
  if (store.state.showSatellites) {
    store.loadTles().then(() => renderer?.setTles(store.state.tles))
  }
  if (store.state.showDisasterPolygons) {
    store.loadDisasterPolygons().then(() => renderer?.setDisasterPolygons(store.state.disasterPolygons))
  }
  if (store.state.showAirQuality) {
    store.loadAirQuality().then(() => renderer?.setAirQuality(store.state.airQuality))
  }
  if (store.state.showLightning) {
    store.loadLightning().then(() => renderer?.setLightning(store.state.lightning))
    const lt = window.setInterval(async () => {
      await store.loadLightning()
      renderer?.setLightning(store.state.lightning)
    }, 5000)
    ;(host.value as any).__lightningTimer = lt
  }
  host.value.addEventListener('pointerdown', onPointerDown)
  host.value.addEventListener('pointerup', onPointerUp)

  await loadBasemap()
  await loadTerrain()
  await refreshWindFrames()
  await loadJet()
  updateStations()
  await updateLayers()
  await store.loadRealtime()
  updateRealtime()
  const rt = window.setInterval(async () => {
    await store.loadRealtime()
    updateRealtime()
  }, 60000)
  ;(host.value as any).__realtimeTimer = rt
  const t = window.setInterval(() => {
    if (renderer) {
      const s = renderer.getStats()
      stats.value = `${s.fps} FPS · ${s.particles} 粒子 · ${s.drawCalls} draw`
      store.state.sunInfo = { ...renderer.subSolarPoint }
      store.state.tileInfo = { ...renderer.getTileStatus() }
    }
  }, 1000)
  ;(host.value as any).__statsTimer = t
})

function updateStations() {
  renderer?.setStations(store.state.stations.map(s => ({
    id: s.station_id, lon: s.lon, lat: s.lat,
    tempC: s.values?.temp_c, dewpointC: s.values?.dewpoint_c,
    speedMs: s.values?.wind_speed_ms,
    visibility: s.values?.visibility?.raw,
    observedAt: s.observed_at,
  })))
}

watch(() => store.state.frameDataRev, updateLayers)
// On a layer switch: clear the previous layer IMMEDIATELY (before the new data
// finishes downloading) so the user can tell "loading" apart from "stale view".
watch(() => store.state.activeLayerId, (id) => {
  clearRenderedLayers()
  hud.value = '正在加载图层…'
  const l = store.state.layers.find(x => x.layer_id === id)
  toastLabel.value = l?.label || id
  toastVisible.value = true
  toastLoading.value = true
  clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => { toastVisible.value = false }, 4000)
  refreshWindFrames().then(updateLayers)
})
// Loading finished -> turn the spinner into a check mark, then fade out.
watch(() => store.state.switchingLayer, (s) => {
  toastLoading.value = !!s
  if (!s && toastVisible.value) {
    clearTimeout(toastTimer)
    toastTimer = window.setTimeout(() => { toastVisible.value = false }, 1300)
  }
})
watch(() => store.state.stations.length, updateStations)
watch(() => store.state.playing, v => renderer?.setPlaying(v, dt => store.advance(dt)))
watch(() => store.state.showParticles, v => renderer?.setWindVisible(v))
watch(() => store.state.useGpuWind, v => renderer?.setGPUWindEnabled(v))
watch(() => store.state.showTrails, v => renderer?.setWindTrailsVisible(v))
watch(() => store.state.showJet, v => renderer?.setJetVisible(v))
watch(() => store.state.showVolume, v => renderer?.setVolumeVisible(v))
watch(() => store.state.volumeDensity, v => renderer?.setVolumeDensity(v))
watch(() => store.state.showField, v => renderer?.setFieldVisible(v))
watch(() => store.state.showStations, v => renderer?.setStationsVisible(v))
watch(() => store.state.showBuoys, v => renderer?.setBuoysVisible(v))
watch(() => store.state.buoys, v => renderer?.setBuoys(v))
watch(() => store.state.particleCount, v => renderer?.setWindCount(v))
watch(() => store.state.speed, v => renderer?.setWindSpeed(v))
watch(() => store.state.layerOpacity, v => {
  renderer?.setFieldOpacity(v)
  renderer?.setImageOpacity(v)
})
watch(() => store.state.terrainExaggeration, v => renderer?.setTerrainExaggeration(v))
watch(() => store.state.showTerrain, v => renderer?.setTerrainVisible(v))
watch(() => store.state.focusRequest, r => {
  if (r) renderer?.focus(r.lon, r.lat, r.distance)
})
watch(() => store.state.nightLights, v => renderer?.setNightLights(v))
watch(() => store.state.cloudStrength, v => renderer?.setCloudStrength(v))
watch(() => store.state.cinematicGrade, v => renderer?.setCinematicGrade(v))
watch(() => store.state.bloom, v => renderer?.setBloom(v))
watch(() => store.state.bloomStrength, v => renderer?.setBloomStrength(v))
watch(() => store.state.simTime, v => renderer?.setSimulationTime(v ? new Date(v) : null))
watch(() => store.state.hdTiles, v => renderer?.setTilesEnabled(v))

function updateRealtime() {
  const e = store.state.realtimeEvents
  renderer?.setRealtimeEvents('quake', e.usgs_quake || [])
  renderer?.setRealtimeEvents('flight', e.opensky || [])
  renderer?.setRealtimeEvents('storm', e.nhc_storm || [])
  renderer?.setRealtimeEvents('cme', e.nasa_cme || [])
  const hazards = [...(e.gdacs || []), ...(e.eonet || [])]
  renderer?.setRealtimeEvents('hazard', hazards)
  renderer?.setRealtimeEvents('fire', e.nasa_firms || [])
  renderer?.setTracks(store.state.tracks)
  renderer?.setAurora(store.state.aurora)
  renderer?.setSolarWind(store.state.solarWind)
  renderer?.setAuroraVisible(store.state.showAurora)
  renderer?.setSolarWindVisible(store.state.showSolarWind)
  renderer?.setQuakesVisible(store.state.showQuakes)
  renderer?.setFlightsVisible(store.state.showFlights)
  renderer?.setStormsVisible(store.state.showStorms)
  renderer?.setCmeVisible(store.state.showCme)
  renderer?.setDisastersVisible(store.state.showDisasters)
  renderer?.setFiresVisible(store.state.showFires)
  renderer?.setTracksVisible(store.state.showTracks)
}
watch(() => store.state.realtimeUpdatedAt, updateRealtime)
watch(() => store.state.showQuakes, v => renderer?.setQuakesVisible(v))
watch(() => store.state.showFlights, v => renderer?.setFlightsVisible(v))
watch(() => store.state.showStorms, v => renderer?.setStormsVisible(v))
watch(() => store.state.showCme, v => renderer?.setCmeVisible(v))
watch(() => store.state.showDisasters, v => renderer?.setDisastersVisible(v))
watch(() => store.state.showFires, v => renderer?.setFiresVisible(v))
watch(() => store.state.showTracks, v => renderer?.setTracksVisible(v))
watch(() => store.state.showAurora, v => renderer?.setAuroraVisible(v))
watch(() => store.state.showAirQuality, (v) => {
  renderer?.setAirQualityVisible(v)
  if (v) store.loadAirQuality().then(() => renderer?.setAirQuality(store.state.airQuality))
})
watch(() => store.state.airQuality, v => renderer?.setAirQuality(v))
watch(() => store.state.showDisasterPolygons, (v) => {
  renderer?.setDisasterPolygonsVisible(v)
  if (v) store.loadDisasterPolygons().then(() => renderer?.setDisasterPolygons(store.state.disasterPolygons))
})
watch(() => store.state.disasterPolygons, v => renderer?.setDisasterPolygons(v))
watch(() => store.state.showSatellites, (v) => {
  renderer?.setSatellitesVisible(v)
  if (v) store.loadTles().then(() => renderer?.setTles(store.state.tles))
})
watch(() => store.state.showSolarWind, v => renderer?.setSolarWindVisible(v))
watch(() => store.state.showLightning, (v) => {
  renderer?.setLightningVisible(v)
  const hostEl = host.value as any
  if (!hostEl) return
  if (hostEl.__lightningTimer) { clearInterval(hostEl.__lightningTimer); hostEl.__lightningTimer = 0 }
  if (v) {
    store.loadLightning().then(() => renderer?.setLightning(store.state.lightning))
    hostEl.__lightningTimer = window.setInterval(async () => {
      await store.loadLightning()
      renderer?.setLightning(store.state.lightning)
    }, 5000)
  }
})

onBeforeUnmount(() => {
  const t = (host.value as any)?.__statsTimer
  if (t) clearInterval(t)
  const rt = (host.value as any)?.__realtimeTimer
  if (rt) clearInterval(rt)
  const lt = (host.value as any)?.__lightningTimer
  if (lt) clearInterval(lt)
  host.value?.removeEventListener('pointerdown', onPointerDown)
  host.value?.removeEventListener('pointerup', onPointerUp)
  renderer?.dispose()
  renderer = null
})
</script>

<template>
  <div class="globe-host" ref="host">
    <transition name="toast">
      <div v-if="toastVisible" class="layer-toast">
        <span v-if="toastLoading" class="toast-spinner"></span>
        <span v-else class="toast-check">✓</span>
        <span class="toast-text">{{ toastLoading ? '正在加载' : '已切换到' }} <b>{{ toastLabel }}</b></span>
      </div>
    </transition>
    <div class="globe-hud">
      <span class="dot"></span>{{ hud || '拖动旋转 · 滚轮缩放 · 点击取值' }}
    </div>
    <div v-if="warning" class="globe-warning">⚠ {{ warning }}</div>
    <div class="globe-stats">{{ stats }}</div>
    <div v-if="store.state.hiresInfo.active" class="hires-badge">◆ 高分辨率数据 {{ store.state.hiresInfo.resolutionKm }} km (HRRR 3km 区域模式)</div>
    <div v-if="store.state.hdTiles && store.state.tileInfo.zoom" class="tile-info">
      卫星瓦片 z{{ store.state.tileInfo.zoom }} · {{ store.state.tileInfo.resolutionM < 10 ? store.state.tileInfo.resolutionM.toFixed(1) : Math.round(store.state.tileInfo.resolutionM) }} m/像素 · {{ store.state.tileInfo.state }}
    </div>
    <div class="globe-compass"><span>N</span><b>↑</b></div>
  </div>
</template>

<style scoped>
.globe-host { position: relative; width: 100%; height: 100%; overflow: hidden; background: #050a12; }
.globe-hud {
  position: absolute; left: 14px; top: 12px; z-index: 2; display: flex; align-items: center; gap: 8px;
  padding: 7px 12px; border-radius: 8px; background: rgba(8, 16, 28, .78); backdrop-filter: blur(8px);
  border: 1px solid rgba(120, 180, 220, .2); color: #d2e6f6; font-size: 12px; max-width: 70%;
  overflow: hidden; white-space: nowrap; text-overflow: ellipsis;
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: #4fe1a5; box-shadow: 0 0 10px #4fe1a5; flex: none; }
.globe-warning {
  position: absolute; left: 14px; top: 48px; z-index: 2; padding: 5px 10px; border-radius: 6px;
  background: rgba(120, 70, 20, .7); border: 1px solid rgba(255, 200, 100, .3);
  color: #ffd479; font-size: 11px;
}
.globe-stats { position: absolute; right: 14px; bottom: 12px; font: 10px ui-monospace, monospace; color: rgba(150,190,220,.5); }
.tile-info { position: absolute; left: 14px; bottom: 12px; padding: 4px 9px; border-radius: 6px; background: rgba(8,16,28,.75); border: 1px solid rgba(120,180,220,.2); font: 10px ui-monospace, monospace; color: #7dfbd0; }
.hires-badge { position: absolute; right: 14px; top: 44px; padding: 5px 10px; border-radius: 6px; background: rgba(124,60,180,.75); border: 1px solid rgba(200,150,255,.4); font: 11px ui-monospace, monospace; color: #e8d0ff; }
.globe-compass {
  position: absolute; right: 16px; top: 12px; display: flex; flex-direction: column; align-items: center;
  color: rgba(190, 220, 240, .55); font: 600 11px ui-monospace, monospace; letter-spacing: .1em;
}
.globe-compass b { font-size: 18px; line-height: 1; color: var(--accent); }
/* Central switch confirmation — deliberately large & centred so a layer
   change is never ambiguous, even between visually similar layers. */
.layer-toast {
  position: absolute; left: 50%; top: 16%; transform: translateX(-50%);
  z-index: 6; display: flex; align-items: center; gap: 10px;
  padding: 11px 20px; border-radius: 12px; white-space: nowrap;
  background: rgba(8, 18, 32, .9); backdrop-filter: blur(10px);
  border: 1px solid rgba(120, 200, 240, .45);
  box-shadow: 0 8px 32px rgba(0, 0, 0, .5), 0 0 24px rgba(80, 180, 230, .18);
  color: #d6ecfa; font-size: 14px;
}
.toast-text b { color: #7dfbd0; font-weight: 600; }
.toast-spinner {
  width: 16px; height: 16px; flex: none; border-radius: 50%;
  border: 2px solid rgba(125, 251, 208, .25); border-top-color: #7dfbd0;
  animation: toast-spin .8s linear infinite;
}
@keyframes toast-spin { to { transform: rotate(360deg); } }
.toast-check {
  width: 18px; height: 18px; flex: none; border-radius: 50%;
  background: rgba(79, 225, 165, .18); color: #4fe1a5;
  display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 700;
}
.toast-enter-active, .toast-leave-active { transition: opacity .25s ease, transform .25s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateX(-50%) translateY(-8px); }
</style>
