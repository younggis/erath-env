/** Central reactive store. Vue state stays separate from the Three.js loop. */
import { reactive, computed } from 'vue'
import { api, type Layer, type Frame, type Sample, type Station, type Buoy, type LightningStrike, type AirStation, type DisasterPolygon, type TleRecord } from './api'
import { sortLayers } from './layerOrder'
import type { GridInfo } from './earth'
import type { VolumeData } from './render/types'
import type { EventType, RealtimeEvent, TrackData } from './realtime'

export interface GridData { values: Float32Array; grid: GridInfo; ncomp: number }

const state = reactive({
  ready: false,
  mode: 'fixture',
  apiError: '' as string,
  layers: [] as Layer[],
  sources: [] as any[],
  dataStatus: null as Awaited<ReturnType<typeof api.dataStatus>> | null,
  // real-time events / space weather
  realtimeEvents: {} as Partial<Record<EventType, RealtimeEvent[]>>,
  tracks: null as TrackData | null,
  aurora: null as any,
  solarWind: null as any,
  realtimeSummary: null as any,
  realtimeUpdatedAt: '' as string,
  showQuakes: false,
  showFlights: false,
  showStorms: false,
  showCme: false,
  showDisasters: false,
  showFires: false,
  showTracks: false,
  showAurora: true,
  showSolarWind: false,
  showJet: false,
  showVolume: true,
  volumeDensity: 0.08,
  volumeSteps: 48,
  activeLayerId: '' as string,
  /** Layer currently being loaded (drives the switch toast/spinner). */
  switchingLayer: '' as string,
  frames: [] as Frame[],
  missingTimes: [] as string[],
  frameIndex: 0,
  /** Float play cursor. frameIndex stays an integer; advance() uses this. */
  playhead: 0,
  gridCache: new Map<string, GridData>(),
  imageCache: new Map<string, string>(),
  volumeCache: new Map<string, VolumeData>(),
  /** Bumped whenever frame data is ready; size-based watches miss same-count evictions. */
  frameDataRev: 0,
  stations: [] as Station[],
  selected: null as Sample | null,
  /** Per-lead sample series for the last picked point (forecast card). */
  forecast: null as { lon: number; lat: number; points: Array<{ validTime: string; sample: Sample }> } | null,
  /** Set by a direct raycaster pick on a station marker. */
  focusedStationId: '' as string,
  focusedEvent: null as { source: EventType; id: string } | null,
  /** NOAA NDBC ocean buoy observations. */
  buoys: [] as Buoy[],
  showBuoys: false,
  focusedBuoyId: '',
  lightning: [] as LightningStrike[],
  showLightning: false,
  airQuality: [] as AirStation[],
  showAirQuality: false,
  disasterPolygons: [] as DisasterPolygon[],
  showDisasterPolygons: false,
  tles: [] as TleRecord[],
  showSatellites: false,
  cables: [] as any[],
  cableLandings: [] as any[],
  showCables: false,
  tectonicPlates: [] as any[],
  showTectonics: false,
  volcanoes: [] as any[],
  showVolcanoes: false,
  routes: null as Awaited<ReturnType<typeof api.flightRoutes>> | null,
  showRoutes: false,
  routeDensity: 1,
  focusedVolcanoId: '',
  focusedDisasterId: '',
  focusedAirStationId: '',
  /** Set by the location bar; GlobeView watches and focuses the globe. */
  focusRequest: null as { lon: number; lat: number; distance?: number } | null,
  savedRegions: [] as Array<{ name: string; lon: number; lat: number; distance?: number }>,
  hoverLon: 0 as number,
  playing: false,
  speed: 1,
  particleCount: 16000,
  showParticles: true,
  useGpuWind: true,
  showTrails: true,
  showField: true,
  showStations: true,
  layerOpacity: 0.5,
  terrainExaggeration: 1,
  showTerrain: false,
  // visual effects
  nightLights: 0.7,
  showShippingLights: true,
  cloudStrength: 0.35,
  cinematicGrade: true,
  bloom: true,
  bloomStrength: 0.85,
  hdTiles: false,
  /** Automatic high-resolution data LOD (HRRR 3km over its domain). */
  autoHiRes: true,
  hiresInfo: { active: false, resolutionKm: 25, layer: '' } as { active: boolean; resolutionKm: number; layer: string },
  tileInfo: { zoom: 0, tiles: 0, resolutionM: 0, state: 'idle', attribution: '' } as {
    zoom: number; tiles: number; resolutionM: number; state: string; attribution: string
  },
  /** null = follow real UTC clock; otherwise a simulation time (ISO string). */
  simTime: null as string | null,
  /** Live sub-solar point reported by the renderer. */
  sunInfo: { lon: 0, lat: 0, at: '' },
  status: '正在连接本地服务…',
})

let loadToken = 0

/** Bounded LRU-style cache: drop the oldest entries, never the displayed one. */
function evictCaches(keepId: string) {
  const MAX = 12
  for (const cache of [state.gridCache, state.imageCache, state.volumeCache]) {
    if (cache.size <= MAX) continue
    const keys = [...cache.keys()].filter(k => k !== keepId)
    while (cache.size > MAX && keys.length) cache.delete(keys.shift()!)
  }
}

export const store = {
  state,
  currentFrame: computed(() => state.frames[state.frameIndex] || null),
  activeLayer: computed(() => state.layers.find(l => l.layer_id === state.activeLayerId) || null),
  currentTime: computed(() => state.frames[state.frameIndex]?.valid_time || ''),
  focusedBuoy: computed(() => state.buoys.find(b => b.station_id === state.focusedBuoyId) || null),
  focusedAirStation: computed(() => state.airQuality.find(
    s => s.station_id === state.focusedAirStationId) || null),
  focusedDisaster: computed(() => state.disasterPolygons.find(
    p => p.event_id === state.focusedDisasterId) || null),
  focusedVolcano: computed(() => state.volcanoes.find(
    v => v.id === state.focusedVolcanoId) || null),

  async loadRoutes() {
    try {
      state.routes = await api.flightRoutes()
    } catch {
      state.routes = null
    }
  },

  async loadVolcanoes() {
    try {
      const res = await api.volcanoes()
      state.volcanoes = res.features
    } catch {
      state.volcanoes = []
    }
  },

  async loadTectonics() {
    try {
      const res = await api.tectonicPlates()
      state.tectonicPlates = res.features
    } catch {
      state.tectonicPlates = []
    }
  },

  async loadCables() {
    try {
      const [cables, landings] = await Promise.all([api.cables(), api.cableLandings()])
      state.cables = cables.features
      state.cableLandings = landings.features
    } catch {
      state.cables = []
      state.cableLandings = []
    }
  },

  async loadTles() {
    try {
      const res = await api.tle()
      state.tles = res.satellites
    } catch {
      state.tles = []
    }
  },

  async loadDisasterPolygons() {
    try {
      const res = await api.gdacsPolygons()
      state.disasterPolygons = res.polygons
    } catch {
      state.disasterPolygons = []
    }
  },

  async loadAirQuality() {
    try {
      const res = await api.airQuality()
      state.airQuality = res.stations
    } catch {
      state.airQuality = []
    }
  },

  async loadLightning() {
    try {
      const res = await api.lightning()
      state.lightning = res.strikes
    } catch {
      state.lightning = []
    }
  },

  async loadBuoys() {
    try {
      const res = await api.buoys()
      state.buoys = res.buoys
    } catch {
      state.buoys = []
    }
  },

  async init() {
    try {
      const health = await api.health()
      state.mode = health.mode
      state.status = health.mode === 'fixture' ? '演示模式：使用内置样本' : '在线模式'
      const layers = await api.layers()
      state.layers = sortLayers(layers.layers)
      const preferred = ['wind10', 'temp2m']
      state.activeLayerId = preferred.find(id => layers.layers.some(l => l.layer_id === id)) || layers.layers[0]?.layer_id || ''
      try { state.sources = (await api.sources()).sources } catch { /* ignore */ }
      try { state.dataStatus = await api.dataStatus() } catch { /* ignore */ }
      await Promise.all([this.selectLayer(state.activeLayerId), this.loadStations()])
      state.ready = true
      state.status = state.mode === 'fixture' ? '演示数据已就绪 · 断网可回放' : '数据已就绪'
    } catch (e: any) {
      state.apiError = e.message || String(e)
      state.status = `连接失败：${state.apiError}`
    }
  },

  async selectLayer(id: string) {
    state.activeLayerId = id
    state.frameIndex = 0
    state.playhead = 0
    state.switchingLayer = id
    const token = ++loadToken
    try {
      const res = await api.frames(id)
      if (token !== loadToken) return
      state.frames = res.frames
      state.forecast = null
      state.missingTimes = res.missing_times || []
      if (state.frames.length) await this.loadFrameData(state.frames[0].frame_id)
    } catch (e: any) {
      state.apiError = e.message || String(e)
    } finally {
      // A stale request must not clear the spinner of a newer layer.
      if (token === loadToken) state.switchingLayer = ''
    }
  },

  async setFrame(index: number) {
    const n = state.frames.length
    if (!n) return
    state.frameIndex = ((index % n) + n) % n
    state.playhead = state.frameIndex
    const frame = state.frames[state.frameIndex]
    if (frame) await this.loadFrameData(frame.frame_id)
  },

  async loadFrameData(frameId: string) {
    if (state.gridCache.has(frameId) || state.imageCache.has(frameId) || state.volumeCache.has(frameId)) {
      state.frameDataRev++  // cached data still needs to trigger a re-render on switch
      return
    }
    const manifest = await api.manifest(frameId)
    const volumeAsset = (manifest.assets || []).find((a: any) => a.role === 'volume')
    if (volumeAsset) {
      const buf = await api.asset((volumeAsset.href || '').split('/').pop() || '')
      const v = manifest.volume || {}
      state.volumeCache.set(frameId, {
        nx: v.nx, ny: v.ny, nz: v.nz, levelsHpa: v.levels_hpa || [],
        values: new Float32Array(buf),
        grid: { nx: v.nx, ny: v.ny, lon0: -180, lat0: -90, dx: 360 / (v.nx - 1), dy: 180 / (v.ny - 1), wrap_longitude: true },
      })
      evictCaches(frameId)
      state.frameDataRev++
      return
    }
    const imageAsset = (manifest.assets || []).find((a: any) => a.role === 'image')
    if (imageAsset) {
      state.imageCache.set(frameId, api.image((imageAsset.href || '').split('/').pop() || ''))
      evictCaches(frameId)
      state.frameDataRev++
      return
    }
    const gridAsset = (manifest.assets || []).find((a: any) => a.role === 'grid')
    if (!gridAsset) return
    const buffer = await api.asset((gridAsset.href || '').split('/').pop() || '')
    const g = manifest.grid
    const ncomp = (manifest.fields || []).length
    state.gridCache.set(frameId, {
      values: new Float32Array(buffer),
      grid: { nx: g.nx, ny: g.ny, lon0: g.lon0, lat0: g.lat0, dx: g.dx, dy: g.dy, wrap_longitude: !!g.wrap_longitude },
      ncomp,
    })
    evictCaches(frameId)
    state.frameDataRev++
  },

  async queryPoint(lon: number, lat: number) {
    const frame = this.currentFrame.value
    if (!frame) return
    state.hoverLon = lon
    try {
      state.selected = await api.sample(frame.frame_id, lon, lat)
    } catch (e: any) {
      state.apiError = e.message || String(e)
    }
    await this.updateForecast(lon, lat)
  },

  /** Fetch the picked point across every available forecast lead so the
   *  detail panel can draw a 72h-style time series for the active layer. */
  async updateForecast(lon: number, lat: number) {
    const frames = state.frames.slice(0, 24)
    if (!frames.length) { state.forecast = null; return }
    try {
      const samples = await Promise.all(
        frames.map(f => api.sample(f.frame_id, lon, lat)),
      )
      state.forecast = {
        lon, lat,
        points: samples.map((s, i) => ({ validTime: frames[i].valid_time, sample: s })),
      }
    } catch {
      state.forecast = null
    }
  },

  async loadStations() {
    try {
      // Show the latest observation from every station (relative to now), not
      // paired to the forecast valid time — otherwise all real stations get
      // filtered out because METAR reports are minutes old while the GFS
      // timeline sits hours ahead.
      const maxAge = state.mode === 'fixture' ? 100000 : 180
      const res = await api.stations(undefined, undefined, maxAge)
      state.stations = res.stations
    } catch (e: any) { state.apiError = e.message || String(e) }
  },

  /** Poll all real-time event / space-weather feeds. */
  async loadRealtime() {
    try {
      const { fetchAllRealtime } = await import('./realtime')
      const d = await fetchAllRealtime()
      state.realtimeEvents = d.events
      state.aurora = d.aurora
      state.solarWind = d.wind
      state.realtimeSummary = d.summary
      state.tracks = d.tracks
      state.realtimeUpdatedAt = d.updatedAt
    } catch { /* real-time layers are optional; keep last good data */ }
  },

  /** Load the HRRR 3km data layer (cached); returns false if unavailable. */
  async loadHiResData(): Promise<{ frameId: string; bbox: [number, number, number, number]; ncomp: number } | null> {
    const FID = 'hrrr-wind10'
    try {
      if (!state.gridCache.has(FID)) {
        const m = await api.manifest(FID)
        const a = (m.assets || []).find((x: any) => x.role === 'grid')
        if (!a) return null
        const buf = await api.asset((a.href || '').split('/').pop() || '')
        const g = m.grid
        state.gridCache.set(FID, {
          values: new Float32Array(buf),
          grid: { nx: g.nx, ny: g.ny, lon0: g.lon0, lat0: g.lat0, dx: g.dx, dy: g.dy, wrap_longitude: false },
          ncomp: (m.fields || []).length,
        })
        // bbox comes from the manifest (list_frames omits it).
        const bb = m.bbox
        if (Array.isArray(bb) && bb.length === 4) {
          return { frameId: FID, bbox: bb as [number, number, number, number], ncomp: (m.fields || []).length }
        }
      }
      return null
    } catch { return null }
  },

  async pollRefreshTask(taskId: string, sourceId: string) {
    for (let i = 0; i < 60; i++) {
      await new Promise(r => setTimeout(r, 1500))
      try {
        const t = await api.refreshTask(taskId)
        if (t.state === 'succeeded') { state.status = `${sourceId} 实时数据已更新`; return }
        if (t.state === 'failed') { state.status = `${sourceId} 采集失败：${t.error}（保留上次数据）`; return }
      } catch { /* keep polling */ }
    }
    state.status = `${sourceId} 采集仍在进行，可稍后刷新`
  },

  async refreshSource(id: string) {
    state.status = `正在采集 ${id}…`
    try {
      const res = await api.refresh(id)
      state.status = `已提交 ${id} 后台采集任务（${res.state}）`
      if (res.task_id) await this.pollRefreshTask(res.task_id, id)
      try { state.dataStatus = await api.dataStatus() } catch { /* ignore */ }
      await this.init()
    } catch (e: any) {
      state.status = `采集失败：${e.message}`
      state.apiError = e.message
    }
  },

  /** Advance playback. Keeps frameIndex integral so currentFrame never breaks. */
  advance(seconds: number) {
    if (!state.playing || !state.frames.length) return
    const fps = 3 * state.speed
    state.playhead = (state.playhead + seconds * fps) % state.frames.length
    const idx = Math.floor(state.playhead)
    if (idx === state.frameIndex) return
    state.frameIndex = idx
    const frame = state.frames[idx]
    if (frame) this.loadFrameData(frame.frame_id)
  },
}
