/** EarthRenderer: scene + Shadertoy-inspired effects pipeline. */
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import {
  GLOBE_R, R_ATMOSPHERE, ll2xyz, xyz2ll, sphereGeometry,
  buildBasemapTexture, patchGeometry,
} from './geo'
import { rgbaFor, speedOf } from './palette'
import { FieldLayer } from './field'
import { WindLayer } from './wind'
import { GPUWindLayer } from './gpuWind'
import { WindTrails } from './windTrails'
import { StationLayer } from './stations'
import { TerrainLayer } from './terrain'
import { SkyLayer } from './sky'
import { SunLayer } from './sun'
import { PostFX } from './postfx'
import { QualityController, QUALITY_PROFILES, type QualityTier } from './quality'
import { TileLayer } from './tiles'
import { EventLayer } from './events'
import { TrackLayer } from './tracks'
import { AuroraLayer } from './aurora'
import { SolarWindLayer } from './solarwind'
import { VolumetricCloudLayer } from './volume'
import type { RealtimeEvent, AuroraData, SolarWindData, TrackData } from '../realtime'
import type { VolumeData } from './types'
import {
  ATMOS_VERT, ATMOS_FRAG, GRAT_VERT, GRAT_FRAG, makeEarthMaterial,
} from './shaders'
import { sunDirection as realSunDirection, subsolarLatitude, subsolarLongitude } from './sunpos'
import type {
  FieldData, WindData, StationPoint, TerrainData,
  PickResult, RenderStats,
} from './types'

// Initial sun direction from the real UTC clock; updated every frame.
const SUN_DIR = realSunDirection(new Date())

export class EarthRenderer {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera: THREE.PerspectiveCamera
  private controls: OrbitControls
  private earth: THREE.Mesh
  private earthMat: THREE.ShaderMaterial
  private atmosphere: THREE.Mesh
  private atmosMat: THREE.ShaderMaterial
  private sky = new SkyLayer()
  private sun = new SunLayer()
  private field = new FieldLayer()
  private hiresMesh: THREE.Mesh | null = null
  private hiresMat: THREE.MeshBasicMaterial | null = null
  private regionMesh: THREE.Mesh | null = null
  private regionMat: THREE.MeshBasicMaterial | null = null
  private wind = new WindLayer()
  private gpuWind = new GPUWindLayer()
  private trails = new WindTrails()
  private trailsWanted = true
  private windVisible = true
  private gpuWindEnabled = false
  private jet = new WindLayer(2500, GLOBE_R * 1.115) // 500 hPa upper-air ribbon
  private stations = new StationLayer()
  private terrain = new TerrainLayer()
  private tiles = new TileLayer()
  private quakeEvents = new EventLayer('quake')
  private flightEvents = new EventLayer('flight')
  private stormEvents = new EventLayer('storm')
  private cmeEvents = new EventLayer('cme')
  private eventIndex: Array<{ type: string; event: RealtimeEvent }> = []
  private eventVisible: Record<string, boolean> = {
    quake: false, flight: false, storm: false, cme: false, hazard: false, fire: false,
  }
  private hazardEvents = new EventLayer('hazard')
  private fireEvents = new EventLayer('fire')
  private tracks = new TrackLayer()
  private aurora = new AuroraLayer()
  private solarWind = new SolarWindLayer()
  private volume = new VolumetricCloudLayer()
  private graticule: THREE.LineSegments
  private gratMat: THREE.ShaderMaterial
  private postfx: PostFX
  private raycaster = new THREE.Raycaster()
  private raf = 0
  private started = false
  private disposed = false
  private quality = new QualityController()
  private pixelRatio = 1
  private onVisibility = () => {
    if (document.hidden) this.pauseLoop()
    else this.resumeLoop()
  }
  private onContextLost = (e: Event) => {
    e.preventDefault()
    this.pauseLoop()
  }
  private onContextRestored = () => {
    this.resize()
    this.resumeLoop()
  }
  private lastTime = 0
  private elapsed = 0
  private fpsFrames = 0
  private fpsTime = 0
  private fps = 0
  private resizeObserver: ResizeObserver
  private basemap: THREE.Texture | null = null
  private nightTexture: THREE.Texture | null = null
  private waveTexture: THREE.DataTexture | null = null
  private imagePatch: THREE.Mesh | null = null
  private imageLoadToken = 0
  private imageOpacity = 0.9
  private host: HTMLElement
  private playing = false
  private tileAccum = 0
  private onFrameAdvance: ((seconds: number) => void) | null = null
  private onViewChange: ((lon: number, lat: number, distance: number) => void) | null = null

  constructor(host: HTMLElement) {
    this.host = host
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, powerPreference: 'high-performance' })
    this.pixelRatio = Math.min(window.devicePixelRatio || 1, QUALITY_PROFILES.high.pixelRatioCap)
    this.renderer.setPixelRatio(this.pixelRatio)
    this.renderer.setSize(host.clientWidth || 800, host.clientHeight || 600)
    this.renderer.outputColorSpace = THREE.SRGBColorSpace
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    this.renderer.toneMappingExposure = 1.05
    host.appendChild(this.renderer.domElement)
    this.renderer.domElement.style.display = 'block'
    this.renderer.domElement.style.width = '100%'
    this.renderer.domElement.style.height = '100%'
    this.renderer.domElement.addEventListener('webglcontextlost', this.onContextLost)
    this.renderer.domElement.addEventListener('webglcontextrestored', this.onContextRestored)

    this.scene.background = new THREE.Color(0x02040a)
    this.camera = new THREE.PerspectiveCamera(42, (host.clientWidth || 800) / (host.clientHeight || 600), 0.002, 200)
    this.camera.position.set(0.5, 1.6, 6.4)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.07
    this.controls.enablePan = false
    this.controls.minDistance = 2.006  // ~20 km above surface — county scale
    this.controls.maxDistance = 14
    this.controls.rotateSpeed = 0.55
    this.controls.zoomSpeed = 0.8

    // Procedural sky dome (stars + nebula).
    this.scene.add(this.sky.mesh)

    // Earth surface — custom shader with day/night terminator, ocean glint,
    // city lights and animated clouds.
    this.earthMat = makeEarthMaterial(null, null)
    this.earth = new THREE.Mesh(sphereGeometry(GLOBE_R, 160, 80), this.earthMat)
    // Load the real NASA Black Marble city-light texture.
    new THREE.TextureLoader().load('/earth-night.jpg', tex => {
      tex.colorSpace = THREE.SRGBColorSpace
      this.earthMat.uniforms.uNightMap.value = tex
      this.nightTexture = tex
    })
    this.earth.renderOrder = 0
    this.scene.add(this.earth)

    // Atmosphere shell — Rayleigh-style scattering shader.
    this.atmosMat = new THREE.ShaderMaterial({
      vertexShader: ATMOS_VERT, fragmentShader: ATMOS_FRAG,
      uniforms: {
        uSunDir: { value: SUN_DIR.clone() },
        uCameraPos: { value: new THREE.Vector3() },
        uTime: { value: 0 },
      },
      transparent: true, blending: THREE.AdditiveBlending,
      side: THREE.BackSide, depthWrite: false,
    })
    this.atmosphere = new THREE.Mesh(sphereGeometry(R_ATMOSPHERE, 96, 48), this.atmosMat)
    this.atmosphere.renderOrder = 1
    this.scene.add(this.atmosphere)
    // Initialise the physically-correct sun for the current UTC instant.
    this.updateRealSun()

    // Pulsing graticule.
    this.graticule = this.buildGraticule()
    this.scene.add(this.graticule)

    // Sun billboard (behind the globe but in front of the sky).
    this.scene.add(this.sun.mesh)

    this.scene.add(this.terrain.mesh)
    this.tiles.getMeshes().forEach(m => this.scene.add(m))
    this.scene.add(this.field.mesh)
    this.scene.add(this.wind.lines)
    this.gpuWind.attachRenderer(this.renderer)
    this.scene.add(this.gpuWind.points)
    const sz = this.renderer.getSize(new THREE.Vector2())
    this.trails.attach(this.renderer, sz.x, sz.y)
    this.scene.add(this.trails.mesh)
    this.scene.add(this.jet.lines)
    this.scene.add(this.stations.points)
    this.scene.add(this.aurora.mesh)
    this.scene.add(this.solarWind.points)
    this.scene.add(this.volume.mesh)
    this.scene.add(this.quakeEvents.points)
    this.scene.add(this.flightEvents.points)
    this.scene.add(this.stormEvents.points)
    this.scene.add(this.cmeEvents.points)
    this.scene.add(this.hazardEvents.points)
    this.scene.add(this.fireEvents.points)
    this.scene.add(this.tracks.lines)
    this.solarWind.setSunDirection(SUN_DIR)

    this.postfx = new PostFX(this.renderer, this.scene, this.camera)
    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(host)
  }

  private buildGraticule(): THREE.LineSegments {
    const pts: number[] = []
    const phases: number[] = []
    let k = 0
    for (let lon = -180; lon < 180; lon += 30) {
      for (let lat = -87; lat < 87; lat += 3) {
        const a = ll2xyz(lon, lat, GLOBE_R * 1.004)
        const b = ll2xyz(lon, lat + 3, GLOBE_R * 1.004)
        pts.push(a.x, a.y, a.z, b.x, b.y, b.z)
        phases.push((k % 12) / 12, (k % 12) / 12); k++
      }
    }
    for (let lat = -60; lat <= 60; lat += 30) {
      for (let lon = -180; lon < 180; lon += 3) {
        const a = ll2xyz(lon, lat, GLOBE_R * 1.004)
        const b = ll2xyz(lon + 3, lat, GLOBE_R * 1.004)
        pts.push(a.x, a.y, a.z, b.x, b.y, b.z)
        phases.push((k % 12) / 12, (k % 12) / 12); k++
      }
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
    g.setAttribute('aPhase', new THREE.Float32BufferAttribute(phases, 1))
    this.gratMat = new THREE.ShaderMaterial({
      vertexShader: GRAT_VERT, fragmentShader: GRAT_FRAG,
      uniforms: { uTime: { value: 0 } },
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    })
    return new THREE.LineSegments(g, this.gratMat)
  }

  setBasemap(geojson: any): void {
    this.basemap = buildBasemapTexture(geojson)
    this.earthMat.uniforms.uMap.value = this.basemap
  }

  setSatelliteBasemap(url: string, onError?: () => void): void {
    new THREE.TextureLoader().load(url, tex => {
      tex.colorSpace = THREE.SRGBColorSpace
      tex.anisotropy = 8
      if (this.basemap && this.basemap !== tex) this.basemap.dispose()
      this.basemap = tex
      this.earthMat.uniforms.uMap.value = tex
    }, undefined, () => onError?.())
  }

  setField(data: FieldData | null): void { this.field.setField(data) }
  setFieldOpacity(v: number): void { this.field.setOpacity(v) }
  setFieldVisible(v: boolean): void { this.field.setVisible(v) }

  /** Feed real GFS-Wave height into the earth shader's ocean glint/foam. */
  setWaveField(values: Float32Array | null, nx = 0, ny = 0): void {
    this.waveTexture?.dispose()
    this.waveTexture = null
    if (!values || !nx || !ny || values.length !== nx * ny) {
      this.earthMat.uniforms.uWaveMap.value = null
      this.earthMat.uniforms.uWaveStrength.value = 0
      return
    }
    const pixels = new Uint8Array(nx * ny * 4)
    for (let i = 0; i < nx * ny; i++) {
      const v = Number.isFinite(values[i]) ? Math.max(0, Math.min(1, values[i] / 12)) : 0
      pixels[i * 4] = Math.round(v * 255)
      pixels[i * 4 + 3] = 255
    }
    const tex = new THREE.DataTexture(pixels, nx, ny, THREE.RGBAFormat)
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.wrapS = THREE.RepeatWrapping
    tex.needsUpdate = true
    this.waveTexture = tex
    this.earthMat.uniforms.uWaveMap.value = tex
    this.earthMat.uniforms.uWaveStrength.value = 1
  }

  /** High-resolution regional data patch (e.g. HRRR 3km) shown when zoomed in. */
  setHiResField(data: FieldData | null, bbox?: [number, number, number, number]): void {
    if (this.hiresMesh) {
      this.scene.remove(this.hiresMesh)
      this.hiresMesh.geometry.dispose()
      this.hiresMat?.map?.dispose(); this.hiresMat?.dispose()
      this.hiresMesh = null; this.hiresMat = null
    }
    if (!data || !bbox) return
    const { nx, ny } = data.grid
    const pixels = new Uint8Array(nx * ny * 4)
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const idx = (j * nx + i) * data.ncomp
      const val = data.vector && data.ncomp >= 2 ? speedOf(data.values[idx], data.values[idx + 1]) : data.values[idx]
      const o = (j * nx + i) * 4
      if (!Number.isFinite(val)) { pixels[o + 3] = 0; continue }
      const c = rgbaFor(data.palette, val, data.range)
      pixels[o] = c[0]; pixels[o + 1] = c[1]; pixels[o + 2] = c[2]; pixels[o + 3] = 245
    }
    // Feather the patch edges so the 3 km inset blends into the coarse field.
    const fade = Math.floor(Math.min(nx, ny) * 0.1)
    for (let e = 0; e < fade; e++) {
      const a = e / fade
      const alpha = Math.round(245 * a)
      for (let i = 0; i < nx; i++) {
        pixels[(e * nx + i) * 4 + 3] = Math.min(pixels[(e * nx + i) * 4 + 3], alpha)
        pixels[((ny - 1 - e) * nx + i) * 4 + 3] = Math.min(pixels[((ny - 1 - e) * nx + i) * 4 + 3], alpha)
      }
      for (let j = 0; j < ny; j++) {
        pixels[(j * nx + e) * 4 + 3] = Math.min(pixels[(j * nx + e) * 4 + 3], alpha)
        pixels[(j * nx + nx - 1 - e) * 4 + 3] = Math.min(pixels[(j * nx + nx - 1 - e) * 4 + 3], alpha)
      }
    }
    const tex = new THREE.DataTexture(pixels, nx, ny, THREE.RGBAFormat)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.magFilter = THREE.LinearFilter; tex.minFilter = THREE.LinearFilter
    tex.needsUpdate = true
    const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.92, depthWrite: false, side: THREE.FrontSide })
    const mesh = new THREE.Mesh(patchGeometry(bbox, GLOBE_R * 1.035, 128, 128), mat)
    mesh.renderOrder = 2.6
    this.scene.add(mesh)
    this.hiresMesh = mesh; this.hiresMat = mat
  }

  /** Render a regional (non-global) active field onto its own bbox patch.
   *  Separate from the LOD overlay so auto-LOD cannot clear the active layer. */
  setRegionField(data: FieldData | null, bbox?: [number, number, number, number]): void {
    if (this.regionMesh) {
      this.scene.remove(this.regionMesh)
      this.regionMesh.geometry.dispose()
      this.regionMat?.map?.dispose(); this.regionMat?.dispose()
      this.regionMesh = null; this.regionMat = null
    }
    if (!data || !bbox) return
    const { nx, ny } = data.grid
    const pixels = new Uint8Array(nx * ny * 4)
    for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++) {
      const idx = (j * nx + i) * data.ncomp
      const val = data.vector && data.ncomp >= 2 ? speedOf(data.values[idx], data.values[idx + 1]) : data.values[idx]
      const o = (j * nx + i) * 4
      if (!Number.isFinite(val)) { pixels[o + 3] = 0; continue }
      const c = rgbaFor(data.palette, val, data.range)
      pixels[o] = c[0]; pixels[o + 1] = c[1]; pixels[o + 2] = c[2]; pixels[o + 3] = 235
    }
    const tex = new THREE.DataTexture(pixels, nx, ny, THREE.RGBAFormat)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.magFilter = THREE.LinearFilter; tex.minFilter = THREE.LinearFilter
    tex.needsUpdate = true
    const mat = new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: 0.75, depthWrite: false, side: THREE.FrontSide })
    const mesh = new THREE.Mesh(patchGeometry(bbox, GLOBE_R * 1.034, 128, 128), mat)
    mesh.renderOrder = 2.7
    this.scene.add(mesh)
    this.regionMesh = mesh; this.regionMat = mat
  }

  setImagePatch(url: string | null, bbox?: [number, number, number, number]): void {
    this.imageLoadToken++  // invalidate any pending async texture load
    if (this.imagePatch) {
      this.scene.remove(this.imagePatch)
      this.imagePatch.geometry.dispose()
      const m = this.imagePatch.material as THREE.MeshBasicMaterial
      m.map?.dispose(); m.dispose()
      this.imagePatch = null
    }
    if (!url || !bbox) return
    // Guard against a stale async load completing after a different layer was
    // selected — otherwise an old patch would be added on top of the new one.
    const token = ++this.imageLoadToken
    new THREE.TextureLoader().load(url, tex => {
      if (token !== this.imageLoadToken) { tex.dispose(); return }
      tex.colorSpace = THREE.SRGBColorSpace
      const mesh = new THREE.Mesh(
        patchGeometry(bbox, GLOBE_R * 1.028, 192, 192),
        new THREE.MeshBasicMaterial({ map: tex, transparent: true, opacity: this.imageOpacity, depthWrite: false }),
      )
      mesh.renderOrder = 2
      this.imagePatch = mesh
      this.scene.add(mesh)
    })
  }

  setImageOpacity(v: number): void {
    this.imageOpacity = 0.6 + v * 0.4
    if (this.imagePatch) (this.imagePatch.material as THREE.MeshBasicMaterial).opacity = this.imageOpacity
  }

  private applyWindVisibility(): void {
    const hasSource = this.wind.hasWindSource() || this.gpuWind.hasWindSource()
    const gpu = this.gpuWindEnabled && this.gpuWind.supported
    this.wind.setVisible(this.windVisible && !gpu && hasSource)
    this.gpuWind.setVisible(this.windVisible && gpu && hasSource)
    this.trails.setVisible(this.windVisible && gpu && hasSource && this.trailsWanted)
  }

  setWindTrailsVisible(v: boolean): void { this.trailsWanted = !!v; this.applyWindVisibility() }

  setWind(data: WindData | null): void {
    this.wind.setWind(data)
    this.gpuWind.setWind(data)
    this.applyWindVisibility()
  }
  setWindCount(n: number): void {
    // The CPU fallback walks every particle per frame; cap it so a high GPU
    // density setting does not stall machines without float render targets.
    this.wind.setCount(Math.min(n, 8000))
    this.gpuWind.setWindCount(n)
  }
  setWindSpeed(s: number): void { this.wind.setSpeed(s); this.gpuWind.setSpeed(s) }
  setWindVisible(v: boolean): void { this.windVisible = v; this.applyWindVisibility() }
  setGPUWindEnabled(v: boolean): void { this.gpuWindEnabled = v; this.applyWindVisibility() }
  hasWindSource(): boolean { return this.wind.hasWindSource() || this.gpuWind.hasWindSource() }

  setJet(data: WindData | null): void { this.jet.setWind(data); this.jet.setVisible(!!data) }
  setJetVisible(v: boolean): void { this.jet.setVisible(v) }

  setStations(stations: StationPoint[]): void { this.stations.setStations(stations) }
  setStationsVisible(v: boolean): void { this.stations.setVisible(v) }

  /* ---------------- real-time events & space weather ---------------- */
  setRealtimeEvents(type: 'quake' | 'flight' | 'storm' | 'cme' | 'hazard' | 'fire',
                    events: RealtimeEvent[]): void {
    if (type === 'quake') this.quakeEvents.setEvents(events)
    else if (type === 'flight') this.flightEvents.setEvents(events)
    else if (type === 'storm') this.stormEvents.setEvents(events)
    else if (type === 'cme') this.cmeEvents.setEvents(events)
    else if (type === 'hazard') this.hazardEvents.setEvents(events)
    else this.fireEvents.setEvents(events)
    this.eventIndex = [
      ...this.eventIndex.filter(x => x.type !== type),
      ...events.map(event => ({ type, event })),
    ]
  }
  setQuakesVisible(v: boolean): void { this.quakeEvents.setVisible(v); this.eventVisible.quake = v }
  setFlightsVisible(v: boolean): void { this.flightEvents.setVisible(v); this.eventVisible.flight = v }
  setStormsVisible(v: boolean): void { this.stormEvents.setVisible(v); this.eventVisible.storm = v }
  setCmeVisible(v: boolean): void { this.cmeEvents.setVisible(v); this.eventVisible.cme = v }
  setDisastersVisible(v: boolean): void { this.hazardEvents.setVisible(v); this.eventVisible.hazard = v }
  setFiresVisible(v: boolean): void { this.fireEvents.setVisible(v); this.eventVisible.fire = v }
  setTracks(data: TrackData | null): void { this.tracks.setTracks(data?.tracks || []) }
  setTracksVisible(v: boolean): void { this.tracks.setVisible(v) }
  /* ---------------- volumetric clouds ---------------- */
  setVolume(data: VolumeData | null): void { this.volume.setVolume(data) }
  setVolumeVisible(v: boolean): void { this.volume.setVisible(v) }
  setVolumeDensity(v: number): void { this.volume.setDensity(v) }
  hasVolume(): boolean { return this.volume.hasData() }

  setAurora(data: AuroraData | null): void { this.aurora.setData(data) }
  setAuroraVisible(v: boolean): void { this.aurora.setVisible(v) }
  setSolarWind(data: SolarWindData | null): void { this.solarWind.setData(data) }
  setSolarWindVisible(v: boolean): void { this.solarWind.setVisible(v) }
  realtimeCounts(): Record<string, number> {
    return {
      quake: this.quakeEvents.getCount(), flight: this.flightEvents.getCount(),
      storm: this.stormEvents.getCount(), cme: this.cmeEvents.getCount(),
      hazard: this.hazardEvents.getCount(), fire: this.fireEvents.getCount(),
      tracks: this.tracks.getCount(),
    }
  }

  setTerrain(data: TerrainData | null, bbox?: [number, number, number, number]): void { this.terrain.setTerrain(data, bbox) }
  setTerrainExaggeration(v: number): void { this.terrain.setExaggeration(v) }
  setTerrainBBox(bbox: [number, number, number, number]): void { this.terrain.setBBox(bbox) }
  setTerrainVisible(v: boolean): void { this.terrain.setVisible(v) }
  hasTerrain(): boolean { return this.terrain.hasData() }


  /* ---------------- high-resolution tiles ---------------- */
  setTilesEnabled(v: boolean): void { this.tiles.setEnabled(v) }
  getTileStatus() { return this.tiles.getStatus() }

  /* ---------------- effect controls ---------------- */
  private realSunMode = true
  private simTimeOverride: Date | null = null

  setNightLights(v: number): void { this.earthMat.uniforms.uNightLights.value = v }
  setCloudStrength(v: number): void { this.earthMat.uniforms.uCloudStrength.value = v }
  setCinematicGrade(v: boolean): void { this.postfx.setGrade(v) }
  setBloom(v: boolean): void { this.postfx.setEnabled(v) }
  setBloomStrength(v: number): void { this.postfx.setStrength(v) }

  /** Lock rendering quality to a tier; disables FPS-driven auto adjustment.
   *  Only pixel ratio, cloud steps and bloom are touched here — particle
   *  counts, cloud density and layer visibility stay under store control. */
  setQualityTier(tier: QualityTier): void {
    this.quality.setTier(tier)
    this.applyQualityTier(tier)
  }
  getQualityTier(): QualityTier { return this.quality.tier }

  private applyQualityTier(tier: QualityTier): void {
    const profile = QUALITY_PROFILES[tier]
    this.pixelRatio = Math.min(window.devicePixelRatio || 1, profile.pixelRatioCap)
    this.renderer.setPixelRatio(this.pixelRatio)
    this.postfx.setPixelRatio(this.pixelRatio)
    this.volume.setSteps(profile.cloudSteps)
    this.postfx.setEnabled(profile.bloomEnabled)
    this.postfx.setStrength(profile.bloomStrength)
  }

  /** Set the simulation time used for the real solar calculation. Pass null
   *  to follow the wall clock. The day/night terminator always reflects this
   *  time — not a hand-picked sun angle. */
  setSimulationTime(date: Date | null): void {
    this.simTimeOverride = date
    this.realSunMode = true
    this.updateRealSun()
  }

  /** Disable real-time mode and use a manual sun position (diagnostics only). */
  setManualSun(lon: number, lat: number): void {
    this.realSunMode = false
    const dir = ll2xyz(lon, lat, 1).normalize()
    this.earthMat.uniforms.uSunDir.value.copy(dir)
    this.atmosMat.uniforms.uSunDir.value.copy(dir)
  }

  private updateRealSun(): void {
    const now = this.simTimeOverride || new Date()
    const dir = realSunDirection(now)
    this.earthMat.uniforms.uSunDir.value.copy(dir)
    this.atmosMat.uniforms.uSunDir.value.copy(dir)
    this.subSolarPoint = { lon: subsolarLongitude(now), lat: subsolarLatitude(now), at: now.toISOString() }
  }

  subSolarPoint: { lon: number; lat: number; at: string } = { lon: 0, lat: 0, at: '' }
  getSunDirection(): [number, number] { return xyz2ll(this.earthMat.uniforms.uSunDir.value as THREE.Vector3) }

  setPlaying(playing: boolean, cb?: (seconds: number) => void): void {
    this.playing = playing
    if (cb) this.onFrameAdvance = cb
  }

  setViewChangeListener(cb: (lon: number, lat: number, distance: number) => void): void { this.onViewChange = cb }

  pick(clientX: number, clientY: number): PickResult | null {
    const rect = this.renderer.domElement.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((clientX - rect.left) / rect.width) * 2 - 1,
      -((clientY - rect.top) / rect.height) * 2 + 1,
    )
    this.raycaster.setFromCamera(ndc, this.camera)
    const hit = this.raycaster.intersectObject(this.earth, false)[0]
    if (!hit) return null
    const [lon, lat] = xyz2ll(hit.point)
    const station = this.stations.pick(ndc, this.camera)
    return { lon, lat, station: station || undefined, screenX: clientX, screenY: clientY }
  }

  /** Nearest visible real-time event within a small screen radius. */
  pickEvent(clientX: number, clientY: number): { type: string; event: RealtimeEvent } | null {
    const rect = this.renderer.domElement.getBoundingClientRect()
    const camDir = this.camera.position.clone().normalize()
    let best: { type: string; event: RealtimeEvent } | null = null
    let bestDist = 26
    for (const item of this.eventIndex) {
      if (!this.eventVisible[item.type]) continue
      const p = ll2xyz(item.event.lon, item.event.lat, GLOBE_R * 1.035)
      if (p.clone().normalize().dot(camDir) < 0) continue
      const screen = p.project(this.camera)
      const sx = rect.left + (screen.x + 1) * rect.width / 2
      const sy = rect.top + (1 - screen.y) * rect.height / 2
      const d = Math.hypot(sx - clientX, sy - clientY)
      if (d < bestDist) { bestDist = d; best = item }
    }
    return best
  }

  focus(lon: number, lat: number, distance = 3.6): void {
    const target = ll2xyz(lon, lat, 1).multiplyScalar(distance)
    this.camera.position.copy(target)
    this.controls.target.set(0, 0, 0)
    this.controls.update()
  }

  private resize(): void {
    const w = this.host.clientWidth
    const h = this.host.clientHeight
    if (!w || !h) return
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    // devicePixelRatio can change when the window moves between displays.
    this.pixelRatio = Math.min(window.devicePixelRatio || 1, QUALITY_PROFILES[this.quality.tier].pixelRatioCap)
    this.renderer.setPixelRatio(this.pixelRatio)
    this.renderer.setSize(w, h)
    this.trails.setSize(w, h)
    this.postfx.setSize(w, h)
    this.postfx.setPixelRatio(this.pixelRatio)
  }

  private pauseLoop(): void {
    if (!this.raf) return
    cancelAnimationFrame(this.raf)
    this.raf = 0
  }

  private resumeLoop(): void {
    if (this.raf || !this.started || this.disposed || document.hidden) return
    this.lastTime = 0
    this.raf = requestAnimationFrame(this.loop)
  }

  start(): void {
    if (this.started || this.disposed) return
    this.started = true
    document.addEventListener('visibilitychange', this.onVisibility)
    this.resumeLoop()
  }

  private loop = (now: number): void => {
    this.raf = requestAnimationFrame(this.loop)
    const dt = Math.min(0.05, (now - (this.lastTime || now)) / 1000)
    this.lastTime = now
    this.elapsed += dt
    this.controls.update()
    if (this.playing && this.onFrameAdvance) this.onFrameAdvance(dt)
    // Keep the solar terminator in sync with real UTC (or the simulation
    // timeline). This is a physical daylight simulation, not an artist knob.
    if (this.realSunMode) this.updateRealSun()

    this.sky.update(this.elapsed)
    this.sun.update(this.elapsed, this.camera)
    this.earthMat.uniforms.uCameraPos.value.copy(this.camera.position)
    this.earthMat.uniforms.uTime.value = this.elapsed
    this.atmosMat.uniforms.uCameraPos.value.copy(this.camera.position)
    this.atmosMat.uniforms.uTime.value = this.elapsed
    this.gratMat.uniforms.uTime.value = this.elapsed
    if (this.gpuWindEnabled && this.gpuWind.supported) {
      this.gpuWind.update(dt)
      if (this.trails.mesh.visible) {
        this.trails.update(this.gpuWind.stateTexture, this.gpuWind.indexAttribute,
          this.gpuWind.stateSize, this.gpuWind.pointsRadius, this.camera)
      }
    } else this.wind.update(dt)
    this.jet.update(dt)
    this.stations.update(this.elapsed)
    this.quakeEvents.update(this.elapsed)
    this.flightEvents.update(this.elapsed)
    this.stormEvents.update(this.elapsed)
    this.cmeEvents.update(this.elapsed)
    this.hazardEvents.update(this.elapsed)
    this.fireEvents.update(this.elapsed)
    this.tracks.update(this.elapsed)
    this.aurora.update(this.elapsed)
    const sunDir = this.atmosMat.uniforms.uSunDir.value as THREE.Vector3
    this.solarWind.setSunDirection(sunDir)
    this.solarWind.update(this.elapsed)
    this.volume.update(this.camera.position, sunDir, this.elapsed)
    // High-resolution satellite tiles for the current view centre. Update at
    // most a few times per second; TileLayer dedups identical tile keys.
    this.tileAccum = (this.tileAccum || 0) + dt
    if (this.tileAccum > 0.4) {
      this.tileAccum = 0
      const dir = this.camera.position.clone().normalize()
      const [clon, clat] = xyz2ll(dir)
      const dist = this.camera.position.length() - GLOBE_R
      this.tiles.update(clon, clat, dist)
      this.onViewChange?.(clon, clat, dist)
    }

    this.postfx.render(dt)
    this.fpsFrames++
    this.fpsTime += dt
    if (this.fpsTime >= 1) {
      this.fps = this.fpsFrames / this.fpsTime
      this.fpsFrames = 0; this.fpsTime = 0
      if (this.quality.auto) {
        const before = this.quality.tier
        this.quality.sample(this.fps)
        if (this.quality.tier !== before) this.applyQualityTier(this.quality.tier)
      }
    }
  }

  getStats(): RenderStats {
    const info = this.renderer.info.render
    return { fps: Math.round(this.fps),
             particles: this.gpuWindEnabled && this.gpuWind.supported
               ? this.gpuWind.particleCount : this.wind.particleCount,
             drawCalls: info.calls, triangles: info.triangles }
  }

  dispose(): void {
    if (this.disposed) return
    this.disposed = true
    this.started = false
    document.removeEventListener('visibilitychange', this.onVisibility)
    this.renderer.domElement.removeEventListener('webglcontextlost', this.onContextLost)
    this.renderer.domElement.removeEventListener('webglcontextrestored', this.onContextRestored)
    this.pauseLoop()
    this.resizeObserver.disconnect()
    this.controls.dispose()
    this.field.dispose(); this.wind.dispose(); this.gpuWind.dispose(); this.trails.dispose(); this.jet.dispose(); this.stations.dispose()
    if (this.hiresMesh) {
      this.scene.remove(this.hiresMesh)
      this.hiresMesh.geometry.dispose()
      this.hiresMat?.map?.dispose(); this.hiresMat?.dispose()
    }
    if (this.regionMesh) {
      this.scene.remove(this.regionMesh)
      this.regionMesh.geometry.dispose()
      this.regionMat?.map?.dispose(); this.regionMat?.dispose()
    }
    this.terrain.dispose()
    this.quakeEvents.dispose(); this.flightEvents.dispose()
    this.stormEvents.dispose(); this.cmeEvents.dispose()
    this.hazardEvents.dispose(); this.fireEvents.dispose(); this.tracks.dispose()
    this.aurora.dispose(); this.solarWind.dispose(); this.volume.dispose()
    this.sky.dispose(); this.sun.dispose(); this.postfx.dispose(); this.tiles.dispose()
    if (this.imagePatch) {
      this.scene.remove(this.imagePatch)
      this.imagePatch.geometry.dispose()
      const m = this.imagePatch.material as THREE.MeshBasicMaterial
      m.map?.dispose(); m.dispose()
    }
    this.basemap?.dispose()
    this.nightTexture?.dispose()
    this.waveTexture?.dispose()
    this.earth.geometry.dispose(); this.earthMat.dispose()
    this.atmosphere.geometry.dispose(); this.atmosMat.dispose()
    this.graticule.geometry.dispose(); this.gratMat.dispose()
    this.renderer.dispose()
    this.renderer.domElement.remove()
  }
}
