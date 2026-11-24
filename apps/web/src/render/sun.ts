/** Sun lens flare — billboard anchored in the upper-right of the view. */
import * as THREE from 'three'
import { SUN_VERT, SUN_FRAG } from './shaders'

export class SunLayer {
  readonly mesh: THREE.Mesh
  private material: THREE.ShaderMaterial
  private _right = new THREE.Vector3()
  private _up = new THREE.Vector3()
  private _forward = new THREE.Vector3()

  constructor(size = 2.8) {
    this.material = new THREE.ShaderMaterial({
      vertexShader: SUN_VERT,
      fragmentShader: SUN_FRAG,
      uniforms: { uTime: { value: 0 } },
      transparent: true,
      blending: THREE.AdditiveBlending,
      depthWrite: false,
      depthTest: false,
    })
    this.mesh = new THREE.Mesh(new THREE.PlaneGeometry(size, size), this.material)
    this.mesh.renderOrder = 50
    this.mesh.frustumCulled = false
  }

  update(time: number, camera: THREE.Camera): void {
    this.material.uniforms.uTime.value = time
    // Position as a lens flare in view space (upper-right), independent of the
    // physical sun direction that drives the surface shading.
    this._right.setFromMatrixColumn(camera.matrixWorld, 0)
    this._up.setFromMatrixColumn(camera.matrixWorld, 1)
    this._forward.set(0, 0, -1).applyQuaternion(camera.quaternion)
    const dist = 18
    this.mesh.position.copy(camera.position)
      .addScaledVector(this._forward, dist)
      .addScaledVector(this._right, dist * 0.34)
      .addScaledVector(this._up, dist * 0.26)
    this.mesh.lookAt(camera.position)
  }

  dispose(): void {
    this.mesh.geometry.dispose()
    this.material.dispose()
  }
}
