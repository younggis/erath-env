/** WebGL2 GPU ping-pong particle wind layer.
 *
 * Particle state (lon / lat / age / seed) lives in two float render targets.
 * A full-screen pass advances every texel with the wind field each frame; the
 * CPU never walks the particle array. The public surface mirrors WindLayer so
 * the layer can be swapped in without touching the rest of the renderer.
 */
import * as THREE from 'three'
import { GLOBE_R } from './geo'
import type { GridInfo, WindData } from './types'

/** Minimal grid shape needed for the UV conversion (GridInfo is assignable). */
export interface WindGridUvInfo {
  lon0: number; lat0: number; dx: number; dy: number
  nx: number; ny: number
  wrap_longitude?: boolean
}

/** State texture layout: side x ceil(count / side), one texel per particle. */
export function gpuWindTextureSize(count: number): { side: number; width: number; height: number } {
  const n = Math.max(1, Math.floor(Number.isFinite(count) ? count : 1))
  const side = Math.ceil(Math.sqrt(n))
  return { side, width: side, height: Math.ceil(n / side) }
}

/** Particle index -> integer texel coordinates inside the state texture. */
export function gpuWindStateIndex(index: number, side: number): [number, number] {
  const s = Math.max(1, Math.floor(Number.isFinite(side) ? side : 1))
  const i = Math.max(0, Math.floor(Number.isFinite(index) ? index : 0))
  return [i % s, Math.floor(i / s)]
}

/** Particle index -> texel-centre UV in the state texture. */
export function gpuWindStateUv(index: number, side: number, width: number, height: number): [number, number] {
  const [x, y] = gpuWindStateIndex(index, side)
  return [(x + 0.5) / Math.max(1, width), (y + 0.5) / Math.max(1, height)]
}

/** lon/lat (degrees) -> texel-centre UV of the wind DataTexture.
 *  S wraps with RepeatWrapping, T clamps with ClampToEdgeWrapping. */
export function gpuWindGridUv(lon: number, lat: number, grid: WindGridUvInfo): [number, number] {
  const nx = Math.max(1, grid.nx)
  const ny = Math.max(1, grid.ny)
  const dx = grid.dx || 1
  const dy = grid.dy || 1
  let fi = (lon - grid.lon0) / dx
  const fj = (lat - grid.lat0) / dy
  if (grid.wrap_longitude === false) fi = Math.min(nx - 1, Math.max(0, fi))
  else fi = ((fi % nx) + nx) % nx
  const cj = Math.min(ny - 1, Math.max(0, fj))
  const u = Math.min(1, Math.max(0, (fi + 0.5) / nx))
  const v = Math.min(1, Math.max(0, (cj + 0.5) / ny))
  return [u, v]
}

/* ------------------------------------------------------------------ shaders */
const GRID_GLSL = /* glsl */`
vec2 windGridUv(float lon, float lat){
  float fi = (lon - uGrid.x) / uGrid.z;
  float fj = (lat - uGrid.y) / uGrid.w;
  if (uWrap < 0.5) fi = clamp(fi, 0.0, uGridN.x - 1.0);
  else fi = mod(fi, uGridN.x);
  fj = clamp(fj, 0.0, uGridN.y - 1.0);
  return clamp(vec2((fi + 0.5) / uGridN.x, (fj + 0.5) / uGridN.y), 0.0, 1.0);
}`

const STATE_UV_GLSL = /* glsl */`
vec2 stateUv(float index){
  return (vec2(mod(index, uStateSize.x), floor(index / uStateSize.x)) + 0.5) / uStateSize;
}`

const SIM_VERT = /* glsl */`
out vec2 vUv;
void main(){
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}`

const HASH_GLSL = /* glsl */`
float hash21(vec2 p){
  p = fract(p * vec2(123.34, 345.45));
  p += dot(p, p + 34.345);
  return fract(p.x * p.y);
}
vec4 respawn(vec2 seed){
  float a = hash21(seed + uTime * 0.731);
  float b = hash21(seed.yx * 1.37 + uTime * 0.517 + 3.1);
  float c = hash21(seed + uTime * 1.913 + 7.7);
  float lon = a * 360.0 - 180.0;
  float lat = degrees(asin(clamp(2.0 * b - 1.0, -1.0, 1.0)));
  return vec4((lon + 180.0) / 360.0, (lat + 90.0) / 180.0, 0.0, c);
}`

const SIM_FRAG = /* glsl */`
precision highp float;
uniform sampler2D uState;
uniform sampler2D uWindMap;
uniform vec4 uGrid;
uniform vec2 uGridN;
uniform float uWrap;
uniform float uDt;
uniform float uTime;
uniform float uSpeed;
in vec2 vUv;
out vec4 fragColor;
${GRID_GLSL}
${HASH_GLSL}
void main(){
  vec4 st = texture(uState, vUv);
  float lon = st.r * 360.0 - 180.0;
  float lat = st.g * 180.0 - 90.0;
  vec4 w = texture(uWindMap, windGridUv(lon, lat));
  // Missing data (alpha = 0) recycles the particle immediately.
  if (w.a < 0.5) {
    fragColor = respawn(vUv * vec2(1234.5, 567.8));
    return;
  }
  float scale = 4200.0 * uSpeed;
  float cosLat = max(0.08, cos(radians(lat)));
  // 1 degree of latitude ~= 111320 m, so metres -> degrees is 180/PI.
  // Using PI/180 here makes particles 3283x too slow (visually frozen).
  const float RAD_TO_DEG = 57.2957795;
  lon += w.r * uDt * scale / (111320.0 * cosLat) * RAD_TO_DEG;
  lat += w.g * uDt * scale / 111320.0 * RAD_TO_DEG;
  lon = mod(lon + 180.0, 360.0) - 180.0;
  lat = clamp(lat, -89.0, 89.0);
  st.r = (lon + 180.0) / 360.0;
  st.g = (lat + 90.0) / 180.0;
  st.b += uDt * (0.008 + 0.010 * st.a);
  if (st.b >= 1.0 || abs(lat) >= 89.0) {
    fragColor = respawn(vUv * vec2(1789.3, 931.7));
    return;
  }
  fragColor = st;
}`

const COPY_FRAG = /* glsl */`
precision highp float;
uniform sampler2D uSrc;
in vec2 vUv;
out vec4 fragColor;
void main(){ fragColor = texture(uSrc, vUv); }`

const POINTS_VERT = /* glsl */`
precision highp float;
in float aIndex;
uniform sampler2D uState;
uniform sampler2D uWindMap;
uniform vec4 uGrid;
uniform vec2 uGridN;
uniform float uWrap;
uniform vec2 uStateSize;
uniform float uRadius;
out float vSpeed;
out float vFade;
out vec2 vDir;
${GRID_GLSL}
${STATE_UV_GLSL}
void main(){
  vec4 st = texture(uState, stateUv(aIndex));
  float lon = st.r * 360.0 - 180.0;
  float lat = st.g * 180.0 - 90.0;
  vec4 w = texture(uWindMap, windGridUv(lon, lat));
  vSpeed = w.a > 0.5 ? length(w.rg) : 0.0;
  vFade = smoothstep(0.0, 0.08, st.b) * (1.0 - smoothstep(0.75, 1.0, st.b));

  float lo = radians(lon), la = radians(lat);
  float cl = cos(la), sl = sin(la);
  vec3 p = uRadius * vec3(cl * sin(lo), sl, cl * cos(lo));
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_Position = projectionMatrix * mv;
  // Screen-space streak direction: project a short step along the wind.
  float lo2 = radians(lon + 0.5 * w.r / max(0.08, cl));
  float la2 = radians(clamp(lat + 0.5 * w.g, -89.0, 89.0));
  vec3 p2 = uRadius * vec3(cos(la2) * sin(lo2), sin(la2), cos(la2) * cos(lo2));
  vec4 c2 = projectionMatrix * modelViewMatrix * vec4(p2, 1.0);
  vec2 d = c2.xy / max(0.0001, c2.w) - gl_Position.xy / max(0.0001, gl_Position.w);
  vDir = length(d) > 1e-5 ? normalize(d) : vec2(1.0, 0.0);
  gl_PointSize = clamp(8.0 + 8.0 * clamp(vSpeed / 30.0, 0.0, 1.0), 5.0, 16.0)
                 * (4.5 / max(0.75, -mv.z));
}`

const POINTS_FRAG = /* glsl */`
precision highp float;
in float vSpeed;
in float vFade;
in vec2 vDir;
out vec4 fragColor;
vec3 windColor(float t){
  vec3 c = mix(vec3(0.35, 0.78, 1.00), vec3(0.40, 0.95, 0.95), smoothstep(0.00, 0.18, t));
  c = mix(c, vec3(0.70, 1.00, 0.50), smoothstep(0.18, 0.40, t));
  c = mix(c, vec3(1.00, 0.88, 0.30), smoothstep(0.40, 0.68, t));
  c = mix(c, vec3(1.00, 0.38, 0.28), smoothstep(0.68, 1.00, t));
  return c;
}
void main(){
  vec2 q = gl_PointCoord * 2.0 - 1.0;
  q.y = -q.y;
  vec2 perp = vec2(-vDir.y, vDir.x);
  float along = dot(q, vDir);
  float across = dot(q, perp);
  float d = length(vec2(along, across * 1.8));
  if (d > 1.0) discard;
  float core = exp(-d * d * 4.0);
  float t = clamp(vSpeed / 30.0, 0.0, 1.0);
  float a = (core * 0.90 + 0.20 * (1.0 - d)) * vFade * (0.45 + 0.55 * t);
  if (a < 0.012) discard;
  fragColor = vec4(windColor(t) * 1.8, a * 0.9);
}`

export class GPUWindLayer {
  readonly points: THREE.Points

  /** WebGL2 + EXT_color_buffer_float availability (known after attachRenderer). */
  get supported(): boolean { return this._supported }

  private renderer: THREE.WebGLRenderer | null = null
  private _supported = false
  private linearFloat = true
  private count: number
  private readonly radius: number
  private data: WindData | null = null
  private hasSource = false
  private wanted = true
  private initialized = false
  private rtA!: THREE.WebGLRenderTarget
  private rtB!: THREE.WebGLRenderTarget
  private read!: THREE.WebGLRenderTarget
  private write!: THREE.WebGLRenderTarget
  private initTexture!: THREE.DataTexture
  private windTexture: THREE.DataTexture | null = null
  private side = 1
  private width = 1
  private height = 1
  private simScene = new THREE.Scene()
  private simCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
  private simQuad!: THREE.Mesh
  private simMaterial!: THREE.ShaderMaterial
  private copyMaterial!: THREE.ShaderMaterial
  private copyUniforms = { uSrc: { value: null as THREE.Texture | null } }
  private material!: THREE.ShaderMaterial
  private uniforms = {
    uState: { value: null as THREE.Texture | null },
    uStateSize: { value: new THREE.Vector2(1, 1) },
    uWindMap: { value: null as THREE.Texture | null },
    uGrid: { value: new THREE.Vector4(-180, -90, 1, 1) },
    uGridN: { value: new THREE.Vector2(1, 1) },
    uWrap: { value: 1 },
    uDt: { value: 0 },
    uTime: { value: 0 },
    uSpeed: { value: 1 },
    uRadius: { value: GLOBE_R },
  }

  constructor(count = 8192, radius = GLOBE_R * 1.048, renderer?: THREE.WebGLRenderer) {
    this.count = Math.max(1, Math.floor(Number.isFinite(count) ? count : 8192))
    this.radius = radius
    this.uniforms.uRadius.value = radius

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(new Float32Array(this.count * 3), 3))
    geo.setAttribute('aIndex', new THREE.BufferAttribute(new Float32Array(this.count), 1))
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), radius + 0.1)
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      vertexShader: POINTS_VERT,
      fragmentShader: POINTS_FRAG,
      uniforms: this.uniforms,
      depthTest: true,
      depthWrite: false,
      transparent: true,
      blending: THREE.NormalBlending,
    })
    this.points = new THREE.Points(geo, this.material)
    this.points.renderOrder = 4
    this.points.frustumCulled = false
    this.points.visible = false

    this.simMaterial = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      vertexShader: SIM_VERT,
      fragmentShader: SIM_FRAG,
      uniforms: this.uniforms,
      depthTest: false,
      depthWrite: false,
    })
    this.copyMaterial = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      vertexShader: SIM_VERT,
      fragmentShader: COPY_FRAG,
      uniforms: this.copyUniforms,
      depthTest: false,
      depthWrite: false,
    })
    this.simQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.simMaterial)
    this.simQuad.frustumCulled = false
    this.simScene.add(this.simQuad)

    this.buildState()
    if (renderer) this.attachRenderer(renderer)
  }

  /** Supply the renderer that will draw the points; also performs the
   *  WebGL2 / EXT_color_buffer_float support check. */
  attachRenderer(renderer: THREE.WebGLRenderer): void {
    this.renderer = renderer
    let ok = false
    try {
      const gl = renderer.getContext()
      const webgl2 = typeof WebGL2RenderingContext !== 'undefined'
        ? gl instanceof WebGL2RenderingContext
        : typeof (gl as WebGL2RenderingContext).texStorage2D === 'function'
      ok = webgl2 && !!gl.getExtension('EXT_color_buffer_float')
      this.linearFloat = ok && !!gl.getExtension('OES_texture_float_linear')
    } catch {
      ok = false
      this.linearFloat = false
    }
    this._supported = ok
    if (this.windTexture) {
      this.windTexture.minFilter = this.windTexture.magFilter =
        this.linearFloat ? THREE.LinearFilter : THREE.NearestFilter
      this.windTexture.needsUpdate = true
    }
    this.applyVisibility()
  }

  private buildState(): void {
    this.rtA?.dispose()
    this.rtB?.dispose()
    this.initTexture?.dispose()
    const size = gpuWindTextureSize(this.count)
    this.side = size.side; this.width = size.width; this.height = size.height
    this.uniforms.uStateSize.value.set(this.width, this.height)

    const data = new Float32Array(this.width * this.height * 4)
    for (let i = 0; i < this.width * this.height; i++) {
      const o = i * 4
      const lon = Math.random() * 360 - 180
      const lat = THREE.MathUtils.radToDeg(Math.asin(2 * Math.random() - 1))
      data[o] = (lon + 180) / 360
      data[o + 1] = (lat + 90) / 180
      data[o + 2] = Math.random() * 0.5
      data[o + 3] = Math.random()
    }
    const tex = new THREE.DataTexture(data, this.width, this.height, THREE.RGBAFormat, THREE.FloatType)
    tex.minFilter = tex.magFilter = THREE.NearestFilter
    tex.wrapS = tex.wrapT = THREE.ClampToEdgeWrapping
    tex.generateMipmaps = false
    tex.needsUpdate = true
    this.initTexture = tex

    const options: THREE.RenderTargetOptions = {
      type: THREE.FloatType, format: THREE.RGBAFormat,
      minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter,
      depthBuffer: false, stencilBuffer: false, generateMipmaps: false,
    }
    this.rtA = new THREE.WebGLRenderTarget(this.width, this.height, options)
    this.rtB = new THREE.WebGLRenderTarget(this.width, this.height, options)
    this.rtA.texture.wrapS = this.rtA.texture.wrapT = THREE.ClampToEdgeWrapping
    this.rtB.texture.wrapS = this.rtB.texture.wrapT = THREE.ClampToEdgeWrapping
    this.read = this.rtA
    this.write = this.rtB
    this.initialized = false
    this.uniforms.uState.value = null

    const positions = new Float32Array(this.count * 3)
    const indices = new Float32Array(this.count)
    for (let i = 0; i < this.count; i++) indices[i] = i
    const geo = this.points.geometry
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    geo.setAttribute('aIndex', new THREE.BufferAttribute(indices, 1))
    geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), this.radius + 0.1)
  }

  private applyVisibility(): void {
    this.points.visible = this.wanted && this.hasSource && this._supported
  }

  private makeWindTexture(data: WindData): THREE.DataTexture | null {
    const { grid, values, ncomp } = data
    if (!grid || !values || ncomp < 2) return null
    const nx = Math.floor(grid.nx)
    const ny = Math.floor(grid.ny)
    if (!(nx > 0 && ny > 0) || values.length < nx * ny * ncomp) return null
    const rgba = new Float32Array(nx * ny * 4)
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const src = (j * nx + i) * ncomp
        const dst = (j * nx + i) * 4
        const u = values[src]
        const v = values[src + 1]
        const valid = Number.isFinite(u) && Number.isFinite(v)
        rgba[dst] = valid ? u : 0
        rgba[dst + 1] = valid ? v : 0
        rgba[dst + 2] = 0
        rgba[dst + 3] = valid ? 1 : 0
      }
    }
    const tex = new THREE.DataTexture(rgba, nx, ny, THREE.RGBAFormat, THREE.FloatType)
    tex.wrapS = THREE.RepeatWrapping
    tex.wrapT = THREE.ClampToEdgeWrapping
    tex.minFilter = tex.magFilter = this.linearFloat ? THREE.LinearFilter : THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return tex
  }

  setWind(data: WindData | null): void {
    this.windTexture?.dispose()
    this.windTexture = null
    this.uniforms.uWindMap.value = null
    this.data = data
    this.hasSource = !!data
    if (data) {
      const g: GridInfo | undefined = data.grid
      if (g) {
        this.uniforms.uGrid.value.set(g.lon0, g.lat0, g.dx || 1, g.dy || 1)
        this.uniforms.uGridN.value.set(g.nx || 1, g.ny || 1)
        this.uniforms.uWrap.value = g.wrap_longitude === false ? 0 : 1
      }
      this.windTexture = this.makeWindTexture(data)
      this.uniforms.uWindMap.value = this.windTexture
    }
    this.applyVisibility()
  }

  setWindCount(n: number): void {
    const next = Math.max(1, Math.floor(Number.isFinite(n) ? n : this.count))
    if (next === this.count) return
    this.count = next
    this.buildState()
    this.applyVisibility()
  }

  setSpeed(s: number): void {
    this.uniforms.uSpeed.value = Number.isFinite(s) ? s : 1
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.applyVisibility()
  }

  hasWindSource(): boolean { return this.hasSource }

  private ensureInitialized(): void {
    if (this.initialized || !this.renderer) return
    const renderer = this.renderer
    const prev = renderer.getRenderTarget()
    this.copyUniforms.uSrc.value = this.initTexture
    this.simQuad.material = this.copyMaterial
    renderer.setRenderTarget(this.rtA)
    renderer.render(this.simScene, this.simCamera)
    renderer.setRenderTarget(this.rtB)
    renderer.render(this.simScene, this.simCamera)
    this.simQuad.material = this.simMaterial
    renderer.setRenderTarget(prev)
    this.read = this.rtA
    this.write = this.rtB
    this.uniforms.uState.value = this.read.texture
    this.initialized = true
  }

  update(dtSeconds: number): void {
    if (!this.renderer || !this._supported || !this.hasSource || !this.wanted || !this.data) return
    this.ensureInitialized()
    const dt = Math.min(Math.max(Number.isFinite(dtSeconds) ? dtSeconds : 0, 0), 0.05)
    if (dt <= 0) return
    this.uniforms.uDt.value = dt
    this.uniforms.uTime.value += dt
    this.uniforms.uState.value = this.read.texture
    const renderer = this.renderer
    const prev = renderer.getRenderTarget()
    renderer.setRenderTarget(this.write)
    renderer.render(this.simScene, this.simCamera)
    renderer.setRenderTarget(prev)
    const tmp = this.read
    this.read = this.write
    this.write = tmp
    this.uniforms.uState.value = this.read.texture
  }

  get particleCount(): number { return this.count }

  get stateSize(): THREE.Vector2 { return this.uniforms.uStateSize.value }

  get pointsRadius(): number { return this.radius }

  /** Latest simulation state texture, for external effects (e.g. trails). */
  get stateTexture(): THREE.Texture | null {
    return this.initialized && this.read ? this.read.texture : null
  }

  /** Same instanced index attribute used to draw the particles. */
  get indexAttribute(): THREE.BufferAttribute | null {
    return this.points.geometry.getAttribute('aIndex') as THREE.BufferAttribute | null
  }

  dispose(): void {
    this.rtA?.dispose()
    this.rtB?.dispose()
    this.initTexture?.dispose()
    this.windTexture?.dispose()
    this.simQuad.geometry.dispose()
    this.copyMaterial.dispose()
    this.simMaterial.dispose()
    this.points.geometry.dispose()
    this.material.dispose()
    this.renderer = null
    this._supported = false
    this.initialized = false
  }
}
