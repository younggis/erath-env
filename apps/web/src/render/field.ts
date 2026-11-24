/** Scalar / vector field overlay rendered as a transparent globe texture. */
import * as THREE from 'three'
import { sphereGeometry, GLOBE_R } from './geo'
import type { FieldData } from './types'
import { rgbaFor, speedOf } from './palette'

export class FieldLayer {
  readonly mesh: THREE.Mesh
  private texture: THREE.DataTexture | null = null

  constructor() {
    this.mesh = new THREE.Mesh(
      sphereGeometry(GLOBE_R * 1.03, 160, 80),
      new THREE.MeshBasicMaterial({
        transparent: true,
        opacity: 0.5,
        depthWrite: false,
        side: THREE.FrontSide,
      }),
    )
    this.mesh.renderOrder = 2
    this.mesh.visible = false
  }

  setField(data: FieldData | null): void {
    if (this.texture) {
      this.texture.dispose()
      this.texture = null
    }
    if (!data) {
      this.mesh.visible = false
      ;(this.mesh.material as THREE.MeshBasicMaterial).map = null
      ;(this.mesh.material as THREE.MeshBasicMaterial).needsUpdate = true
      return
    }
    const { nx, ny } = data.grid
    const pixels = new Uint8Array(nx * ny * 4)
    for (let j = 0; j < ny; j++) {
      for (let i = 0; i < nx; i++) {
        const idx = (j * nx + i) * data.ncomp
        let value: number
        if (data.vector && data.ncomp >= 2) {
          value = speedOf(data.values[idx], data.values[idx + 1])
        } else {
          value = data.values[idx]
        }
        const o = (j * nx + i) * 4
        if (!Number.isFinite(value)) {
          pixels[o] = 0; pixels[o + 1] = 0; pixels[o + 2] = 0; pixels[o + 3] = 0
          continue
        }
        const a = rgbaFor(data.palette, value, data.range)
        pixels[o] = a[0]; pixels[o + 1] = a[1]; pixels[o + 2] = a[2]; pixels[o + 3] = a[3]
      }
    }
    const tex = new THREE.DataTexture(pixels, nx, ny, THREE.RGBAFormat)
    tex.colorSpace = THREE.SRGBColorSpace
    tex.magFilter = THREE.LinearFilter
    tex.minFilter = THREE.LinearFilter
    tex.wrapS = data.grid.wrap_longitude ? THREE.RepeatWrapping : THREE.ClampToEdgeWrapping
    tex.needsUpdate = true
    this.texture = tex
    const mat = this.mesh.material as THREE.MeshBasicMaterial
    mat.map = tex
    mat.needsUpdate = true
    this.mesh.visible = true
  }

  setOpacity(v: number): void {
    ;(this.mesh.material as THREE.MeshBasicMaterial).opacity = v
  }

  setVisible(v: boolean): void {
    this.mesh.visible = v && !!this.texture
  }

  dispose(): void {
    this.texture?.dispose()
    this.mesh.geometry.dispose()
    ;(this.mesh.material as THREE.Material).dispose()
  }
}
