/** Instanced 3D energy pillars for the WRI global power plant database. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'

export type PowerPlant = [lat: number, lon: number, mw: number, fuel: number, name: string]
export interface PowerPlantsData { fuels: string[]; plants: PowerPlant[] }

/** Display colour per WRI primary fuel (nuclear purple, hydro cyan, solar gold, thermal orange-red). */
export const FUEL_COLORS: Record<string, number> = {
  Nuclear: 0xc77dff,
  Hydro: 0x35d6f0,
  Solar: 0xffd54a,
  Coal: 0xff5a3c,
  Gas: 0xff8a4c,
  Oil: 0xff6a2a,
  Petcoke: 0xff4d2e,
  Cogeneration: 0xff7043,
  Biomass: 0x7fd35b,
  Waste: 0x8bd450,
  Geothermal: 0xff5fa2,
  Storage: 0x6fa8ff,
  'Wave and Tidal': 0x4fd0c0,
  Wind: 0xbfeaff,
  Other: 0xb0b7c3,
}

const MAX_CAPACITY_MW = 5000

/** Log-scaled pillar height in globe units; bounded so pillars never pierce the globe. */
export function pillarHeight(mw: number): number {
  const t = Math.min(1, Math.log10(1 + Math.max(0, mw)) / Math.log10(1 + MAX_CAPACITY_MW))
  return GLOBE_R * (0.006 + 0.05 * t)
}

/** Defensive client-side cleaning; the bundled asset is already validated server-side. */
export function filterValidPlants(plants: PowerPlant[], fuelCount: number): PowerPlant[] {
  return plants.filter(p =>
    Array.isArray(p) && p.length === 5 &&
    Number.isFinite(p[0]) && p[0] >= -90 && p[0] <= 90 &&
    Number.isFinite(p[1]) && p[1] >= -180 && p[1] <= 180 &&
    Number.isFinite(p[2]) && p[2] > 0 &&
    Number.isInteger(p[3]) && p[3] >= 0 && p[3] < fuelCount &&
    typeof p[4] === 'string')
}

/** Bit mask for the fuel-filter uniform; 'all' enables every WRI fuel. */
export function fuelMask(fuels: string[], selected: string): number {
  if (selected === 'all') return (1 << fuels.length) - 1
  const idx = fuels.indexOf(selected)
  return idx < 0 ? 0 : 1 << idx
}

const VERT = /* glsl */`
in vec3 aColor;
in float aFuel;
uniform uint uFuelMask;
out vec3 vColor;
out float vY;
void main(){
  if ((uFuelMask & (1u << uint(aFuel))) == 0u) {
    gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
    vColor = vec3(0.0);
    vY = 0.0;
    return;
  }
  vColor = aColor;
  vY = position.y;
  #ifdef USE_INSTANCING
    mat4 im = instanceMatrix;
  #else
    mat4 im = mat4(1.0);
  #endif
  vec4 world = modelMatrix * im * vec4(position, 1.0);
  gl_Position = projectionMatrix * viewMatrix * world;
}`

const FRAG = /* glsl */`
precision highp float;
in vec3 vColor;
in float vY;
uniform float uTime;
out vec4 f;
void main(){
  float tip = smoothstep(0.55, 1.0, vY);
  float pulse = 0.93 + 0.07 * sin(uTime * 2.0 + vY * 4.0);
  vec3 col = vColor * (0.5 + 1.2 * tip) * pulse;
  f = vec4(col, (0.30 + 0.55 * tip) * pulse);
}`

export class PowerPlantLayer {
  readonly mesh: THREE.InstancedMesh
  private material: THREE.ShaderMaterial
  private fuels: string[] = []
  private wanted = false

  constructor(capacity = 40_000) {
    const geo = new THREE.CylinderGeometry(0.5, 0.5, 1, 5, 1, true)
    geo.translate(0, 0.5, 0) // base at origin, grows outward along +Y
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 }, uFuelMask: { value: 0x7fff } },
      transparent: true, depthTest: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.mesh = new THREE.InstancedMesh(geo, this.material, capacity)
    this.mesh.count = 0
    this.mesh.renderOrder = 3
    this.mesh.frustumCulled = false
    this.mesh.visible = false
  }

  setData(data: PowerPlantsData): void {
    const plants = filterValidPlants(data.plants, data.fuels.length)
    const count = Math.min(plants.length, this.mesh.instanceMatrix.count)
    const dummy = new THREE.Object3D()
    const up = new THREE.Vector3(0, 1, 0)
    const colors = new Float32Array(count * 3)
    const fuelIdx = new Float32Array(count)
    for (let i = 0; i < count; i++) {
      const [lat, lon, mw, fuel] = plants[i]
      const pos = ll2xyz(lon, lat, GLOBE_R * 1.001) // lift base off the surface
      dummy.position.copy(pos)
      dummy.quaternion.setFromUnitVectors(up, pos.clone().normalize())
      const h = pillarHeight(mw)
      dummy.scale.set(GLOBE_R * 0.0016, h, GLOBE_R * 0.0016)
      dummy.updateMatrix()
      this.mesh.setMatrixAt(i, dummy.matrix)
      const hex = FUEL_COLORS[data.fuels[fuel]] ?? 0xffffff
      colors[i * 3] = ((hex >> 16) & 255) / 255
      colors[i * 3 + 1] = ((hex >> 8) & 255) / 255
      colors[i * 3 + 2] = (hex & 255) / 255
      fuelIdx[i] = fuel
    }
    this.fuels = data.fuels
    this.mesh.count = count
    this.mesh.instanceMatrix.needsUpdate = true
    this.mesh.geometry.setAttribute('aColor', new THREE.InstancedBufferAttribute(colors, 3))
    this.mesh.geometry.setAttribute('aFuel', new THREE.InstancedBufferAttribute(fuelIdx, 1))
    this.mesh.visible = this.wanted && count > 0
  }

  /** Restrict rendering to one WRI fuel type; 'all' shows every plant. */
  setFuel(selected: string): void {
    this.material.uniforms.uFuelMask.value = fuelMask(this.fuels, selected)
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.mesh.visible = v && this.mesh.count > 0
  }

  update(seconds: number): void { this.material.uniforms.uTime.value = seconds }

  dispose(): void {
    this.mesh.geometry.dispose()
    this.material.dispose()
  }
}
