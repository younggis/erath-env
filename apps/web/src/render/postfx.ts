/** Post-processing chain: bloom for the neon/glow aesthetic. */
import * as THREE from 'three'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'
import { ShaderPass } from 'three/examples/jsm/postprocessing/ShaderPass.js'

/** Subtle cinematic grade applied in linear space before OutputPass.
 *  Tonemapping/colour-space conversion is left to OutputPass. */
const CINEMATIC_SHADER = {
  uniforms: {
    tDiffuse: { value: null as THREE.Texture | null },
    uTime: { value: 0 },
    uResolution: { value: new THREE.Vector2(1500, 950) },
  },
  vertexShader: /* glsl */`
    varying vec2 vUv;
    void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`,
  fragmentShader: /* glsl */`
    precision highp float;
    uniform sampler2D tDiffuse;
    uniform float uTime;
    uniform vec2 uResolution;
    varying vec2 vUv;
    void main(){
      vec2 c = vUv - 0.5;
      float r2 = dot(c,c);
      float vig = 1.0 - smoothstep(0.16, 0.78, r2) * 0.42;
      vec2 off = c * 0.0032 * (0.4 + r2);
      vec3 col;
      col.r = texture2D(tDiffuse, vUv + off).r;
      col.g = texture2D(tDiffuse, vUv).g;
      col.b = texture2D(tDiffuse, vUv - off).b;
      float n = fract(sin(dot(vUv * uResolution + uTime, vec2(12.9898, 78.233))) * 43758.5453);
      col += (n - 0.5) * 0.010;
      gl_FragColor = vec4(col * vig, 1.0);
    }`,
}

export class PostFX {
  readonly composer: EffectComposer
  private bloom: UnrealBloomPass
  private grade: ShaderPass
  private enabled = true

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera) {
    const size = renderer.getSize(new THREE.Vector2())
    const pr = renderer.getPixelRatio()
    // WebGL2 multisampled HDR target: off-screen AA, then linear HDR is tone
    // mapped once by OutputPass on the way to the screen.
    const target = new THREE.WebGLRenderTarget(
      Math.max(1, Math.floor(size.width * pr)),
      Math.max(1, Math.floor(size.height * pr)),
      { type: THREE.HalfFloatType, samples: 4 },
    )
    target.texture.name = 'PostFX.rt'
    this.composer = new EffectComposer(renderer, target)
    this.composer.addPass(new RenderPass(scene, camera))
    this.bloom = new UnrealBloomPass(
      new THREE.Vector2(size.width, size.height),
      0.55,  // strength
      0.5,   // radius
      1.05,  // threshold — only genuine highlights (sun, particles) bloom
    )
    this.composer.addPass(this.bloom)
    this.grade = new ShaderPass(CINEMATIC_SHADER)
    this.grade.uniforms.uResolution.value.set(size.width, size.height)
    this.composer.addPass(this.grade)
    this.composer.addPass(new OutputPass())
    // A supplied target makes EffectComposer treat width/height as device
    // pixels; restore CSS dimensions so pixel-ratio bookkeeping stays correct.
    this.setSize(size.width, size.height)
  }

  setSize(w: number, h: number): void {
    this.composer.setSize(Math.max(1, w), Math.max(1, h))
    this.grade.uniforms.uResolution.value.set(w, h)
  }

  /** Keep composer targets in sync when the renderer's pixel ratio changes. */
  setPixelRatio(pr: number): void {
    this.composer.setPixelRatio(pr)
  }

  // Keep RenderPass -> OutputPass running at all times; only bloom is toggled.
  // Earlier versions skipped the whole chain here, leaving a blank canvas.
  setEnabled(v: boolean): void { this.enabled = v; this.bloom.enabled = v }
  isEnabled(): boolean { return this.enabled }

  setGrade(v: boolean): void { this.grade.enabled = !!v }

  setStrength(v: number): void { this.bloom.strength = v }
  getStrength(): number { return this.bloom.strength }

  render(delta: number): void {
    this.grade.uniforms.uTime.value += Math.min(Math.max(delta, 0), 0.05)
    this.composer.render(delta)
  }

  dispose(): void {
    this.composer.dispose()
  }
}
