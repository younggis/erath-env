/** Local DEM terrain patch with elevation displacement and exaggeration. */
import * as THREE from 'three'
import { patchGeometry, GLOBE_R } from './geo'
import type { TerrainData } from './types'

const BASE_SCALE = 2.2e-6

export class TerrainLayer {
  readonly mesh: THREE.Mesh
  private data: TerrainData | null = null
  private exaggeration = 1
  private bbox: [number, number, number, number] = [7, 45, 7.9, 45.8]

  constructor() {
    this.mesh = new THREE.Mesh(
      new THREE.BufferGeometry(),
      new THREE.MeshStandardMaterial({
        color: 0xb9a68a, roughness: 0.95, metalness: 0.0,
        transparent: true, opacity: 0.85, side: THREE.DoubleSide,
        flatShading: false,
      }),
    )
    this.mesh.renderOrder = 3
    this.mesh.visible = false
  }

  setTerrain(data: TerrainData | null, bbox?: [number, number, number, number]): void {
    this.data = data
    if (bbox) this.bbox = bbox
    this.rebuild()
  }

  setBBox(bbox: [number, number, number, number]): void {
    this.bbox = bbox
    if (this.data) this.rebuild()
  }

  setExaggeration(v: number): void {
    this.exaggeration = v
    if (this.data) this.rebuild()
  }

  private rebuild(): void {
    this.mesh.geometry.dispose()
    if (!this.data) {
      this.mesh.geometry = new THREE.BufferGeometry()
      this.mesh.visible = false
      return
    }
    this.mesh.geometry = patchGeometry(
      this.bbox,
      GLOBE_R * 1.025,
      128, 96,
      this.data.values,
      this.data.grid,
      BASE_SCALE * this.exaggeration,
    )
    this.mesh.visible = true
  }

  setVisible(v: boolean): void { this.mesh.visible = v && !!this.data }
  hasData(): boolean { return !!this.data }

  getGrid(): TerrainData['grid'] | null { return this.data?.grid || null }

  dispose(): void {
    this.mesh.geometry.dispose()
    ;(this.mesh.material as THREE.Material).dispose()
  }
}
