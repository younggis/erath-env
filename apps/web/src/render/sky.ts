/** Procedural starfield + nebula sky dome (Shadertoy-inspired). */
import * as THREE from 'three'
import { SKY_VERT, SKY_FRAG } from './shaders'

export class SkyLayer {
  readonly mesh: THREE.Mesh
  private material: THREE.ShaderMaterial

  constructor(radius = 60) {
    this.material = new THREE.ShaderMaterial({
      vertexShader: SKY_VERT,
      fragmentShader: SKY_FRAG,
      uniforms: { uTime: { value: 0 } },
      side: THREE.BackSide,
      depthWrite: false,
      depthTest: false,
    })
    this.mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 64, 32), this.material)
    this.mesh.renderOrder = -100
    this.mesh.frustumCulled = false
  }

  update(time: number): void {
    this.material.uniforms.uTime.value = time
  }

  dispose(): void {
    this.mesh.geometry.dispose()
    this.material.dispose()
  }
}
