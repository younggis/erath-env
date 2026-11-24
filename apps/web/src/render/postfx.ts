/** Post-processing chain: bloom for the neon/glow aesthetic. */
import * as THREE from 'three'
import { EffectComposer } from 'three/examples/jsm/postprocessing/EffectComposer.js'
import { RenderPass } from 'three/examples/jsm/postprocessing/RenderPass.js'
import { UnrealBloomPass } from 'three/examples/jsm/postprocessing/UnrealBloomPass.js'
import { OutputPass } from 'three/examples/jsm/postprocessing/OutputPass.js'

export class PostFX {
  readonly composer: EffectComposer
  private bloom: UnrealBloomPass
  private enabled = true

  constructor(renderer: THREE.WebGLRenderer, scene: THREE.Scene, camera: THREE.Camera) {
    this.composer = new EffectComposer(renderer)
    this.composer.addPass(new RenderPass(scene, camera))
    this.bloom = new UnrealBloomPass(
      new THREE.Vector2(window.innerWidth, window.innerHeight),
      0.55,  // strength
      0.5,   // radius
      1.05,  // threshold — only genuine highlights (sun, particles) bloom
    )
    this.composer.addPass(this.bloom)
    this.composer.addPass(new OutputPass())
  }

  setSize(w: number, h: number): void {
    this.composer.setSize(w, h)
  }

  setEnabled(v: boolean): void { this.enabled = v }
  isEnabled(): boolean { return this.enabled }

  setStrength(v: number): void { this.bloom.strength = v }
  getStrength(): number { return this.bloom.strength }

  render(delta: number): void {
    if (this.enabled) this.composer.render(delta)
  }

  dispose(): void {
    this.composer.dispose()
  }
}
