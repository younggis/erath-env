/** Screen-space wind trails: accumulates the GPU particles into a fading
 *  ping-pong buffer so the globe is covered by continuous flowing light
 *  ribbons instead of isolated dots. Back-facing particles are discarded in
 *  the vertex shader so trails never leak through the globe.
 */
import * as THREE from 'three'

const QUAD_VERT = /* glsl */`
out vec2 vUv;
void main(){
  vUv = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}`

const FADE_FRAG = /* glsl */`
precision highp float;
uniform sampler2D uPrev;
uniform float uDecay;
in vec2 vUv;
out vec4 f;
void main(){ f = texture(uPrev, vUv) * uDecay; }`

const COMPOSITE_FRAG = /* glsl */`
precision highp float;
uniform sampler2D uTrail;
in vec2 vUv;
out vec4 f;
void main(){ f = texture(uTrail, vUv); }`

const TRAIL_VERT = /* glsl */`
precision highp float;
in float aIndex;
uniform sampler2D uState;
uniform vec2 uStateSize;
uniform float uRadius;
void main(){
  vec2 uv = (vec2(mod(aIndex, uStateSize.x), floor(aIndex / uStateSize.x)) + 0.5) / uStateSize;
  vec4 st = texture(uState, uv);
  float lon = st.r * 360.0 - 180.0, lat = st.g * 180.0 - 90.0;
  float lo = radians(lon), la = radians(lat);
  vec3 p = uRadius * vec3(cos(la) * sin(lo), sin(la), cos(la) * cos(lo));
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vec3 nv = normalize(mat3(modelViewMatrix) * normalize(p));
  if (dot(nv, normalize(-mv.xyz)) < -0.02) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    gl_PointSize = 0.0;
    return;
  }
  gl_Position = projectionMatrix * mv;
  gl_PointSize = 1.3;
}`

const TRAIL_FRAG = /* glsl */`
precision highp float;
out vec4 f;
void main(){ f = vec4(0.12, 0.62, 0.95, 0.09); }`

export class WindTrails {
  /** Full-screen additive quad added to the main scene. */
  readonly mesh: THREE.Mesh

  private renderer: THREE.WebGLRenderer | null = null
  private rtA: THREE.WebGLRenderTarget | null = null
  private rtB: THREE.WebGLRenderTarget | null = null
  private read: THREE.WebGLRenderTarget | null = null
  private write: THREE.WebGLRenderTarget | null = null
  private fadeScene = new THREE.Scene()
  private trailScene = new THREE.Scene()
  private quadCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
  private fadeMat: THREE.ShaderMaterial
  private compositeMat: THREE.ShaderMaterial
  private trailMat: THREE.ShaderMaterial
  private trailGeo: THREE.BufferGeometry
  private trailPoints: THREE.Points
  private lastCam = new THREE.Matrix4()
  private hasCam = false
  private wanted = true

  constructor() {
    this.fadeMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: QUAD_VERT, fragmentShader: FADE_FRAG,
      uniforms: { uPrev: { value: null as THREE.Texture | null }, uDecay: { value: 0.975 } },
      depthTest: false, depthWrite: false,
    })
    this.compositeMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: QUAD_VERT, fragmentShader: COMPOSITE_FRAG,
      uniforms: { uTrail: { value: null as THREE.Texture | null } },
      transparent: true, depthTest: false, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.compositeMat)
    this.mesh.frustumCulled = false
    this.mesh.renderOrder = 100
    this.mesh.visible = false

    this.fadeScene.add(new THREE.Mesh(new THREE.PlaneGeometry(2, 2), this.fadeMat))

    this.trailGeo = new THREE.BufferGeometry()
    this.trailGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3), 3))
    this.trailMat = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: TRAIL_VERT, fragmentShader: TRAIL_FRAG,
      uniforms: {
        uState: { value: null as THREE.Texture | null },
        uStateSize: { value: new THREE.Vector2(1, 1) },
        uRadius: { value: 2.096 },
      },
      transparent: true, depthTest: false, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.trailPoints = new THREE.Points(this.trailGeo, this.trailMat)
    this.trailPoints.frustumCulled = false
    this.trailScene.add(this.trailPoints)
  }

  attach(renderer: THREE.WebGLRenderer, width: number, height: number): void {
    this.renderer = renderer
    this.setSize(width, height)
  }

  setSize(width: number, height: number): void {
    const w = Math.max(1, Math.floor(width * 0.5))
    const h = Math.max(1, Math.floor(height * 0.5))
    if (this.rtA && this.rtA.width === w && this.rtA.height === h) return
    this.rtA?.dispose(); this.rtB?.dispose()
    const options: THREE.RenderTargetOptions = {
      format: THREE.RGBAFormat, type: THREE.UnsignedByteType,
      minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
      depthBuffer: false, stencilBuffer: false, generateMipmaps: false,
    }
    this.rtA = new THREE.WebGLRenderTarget(w, h, options)
    this.rtB = new THREE.WebGLRenderTarget(w, h, options)
    this.read = this.rtA; this.write = this.rtB
    this.hasCam = false
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.mesh.visible = v
    if (!v) this.hasCam = false
  }

  update(stateTexture: THREE.Texture | null, indexAttr: THREE.BufferAttribute | null,
         stateSize: THREE.Vector2 | null, radius: number, camera: THREE.Camera): void {
    const renderer = this.renderer
    if (!renderer || !this.wanted || !stateTexture || !indexAttr || !this.read || !this.write) return

    // Rebind each frame: buildState() may replace the index attribute.
    // Points draw count comes from the position attribute, so it must match.
    if (this.trailGeo.getAttribute('aIndex') !== indexAttr) {
      this.trailGeo.setAttribute('aIndex', indexAttr)
      this.trailGeo.setAttribute('position',
        new THREE.BufferAttribute(new Float32Array(indexAttr.count * 3), 3))
    }
    this.trailMat.uniforms.uState.value = stateTexture
    this.trailMat.uniforms.uRadius.value = radius
    if (stateSize) (this.trailMat.uniforms.uStateSize.value as THREE.Vector2).copy(stateSize)

    // Fast decay while the camera moves to avoid smeared screen-space trails.
    const moved = this.hasCam && !this.lastCam.equals(camera.matrixWorld)
    this.fadeMat.uniforms.uDecay.value = moved ? 0.5 : 0.975
    this.lastCam.copy(camera.matrixWorld); this.hasCam = true

    const prev = renderer.getRenderTarget()
    const autoClear = renderer.autoClear
    // Fade the previous frame into the write buffer.
    this.fadeMat.uniforms.uPrev.value = this.read.texture
    renderer.setRenderTarget(this.write)
    renderer.render(this.fadeScene, this.quadCam)
    // Draw current particle positions on top (no clear).
    renderer.autoClear = false
    renderer.render(this.trailScene, camera)
    renderer.autoClear = autoClear
    renderer.setRenderTarget(prev)

    const tmp = this.read; this.read = this.write; this.write = tmp
    this.compositeMat.uniforms.uTrail.value = this.read.texture
  }

  dispose(): void {
    this.rtA?.dispose(); this.rtB?.dispose()
    this.fadeMat.dispose(); this.compositeMat.dispose(); this.trailMat.dispose()
    this.mesh.geometry.dispose()
    this.fadeScene.traverse(o => { if (o instanceof THREE.Mesh) o.geometry.dispose() })
    this.trailGeo.dispose()
    this.renderer = null
  }
}
