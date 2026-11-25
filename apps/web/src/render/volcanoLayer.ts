/** Instanced 3D volcano cones with lava glow driven by eruption recency. */
import * as THREE from 'three'
import { GLOBE_R, ll2xyz } from './geo'
import { coneScale, eruptionRecency, pulseFrequency, volcanoRadius, type Volcano } from './volcanoGlow'

const VERT = /* glsl */`
in float aGlow;
in float aPhase;
uniform float uTime;
out float vGlow;
out float vPulse;
out float vY;
void main(){
  vGlow = aGlow;
  vY = position.y;
  vPulse = 0.5 + 0.5 * sin(uTime * (0.4 + aGlow * 3.2) * 6.2831853 + aPhase);
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
in float vGlow;
in float vPulse;
in float vY;
out vec4 f;
void main(){
  vec3 rock = vec3(0.24, 0.18, 0.17);
  vec3 lava = mix(vec3(1.0, 0.22, 0.04), vec3(1.0, 0.70, 0.16), vPulse);
  float crater = smoothstep(1.15, 1.75, vY);
  float glow = crater * (0.25 + 0.75 * vPulse) * (0.25 + 0.75 * vGlow);
  vec3 col = mix(rock, lava, clamp(glow, 0.0, 1.0));
  f = vec4(col, 1.0);
}`

export class VolcanoLayer {
  readonly mesh: THREE.InstancedMesh
  private material: THREE.ShaderMaterial
  private volcanoes: Volcano[] = []
  private wanted = false

  constructor() {
    const geo = new THREE.ConeGeometry(1, 2, 8, 1)
    geo.translate(0, 1, 0) // base at origin, apex outward
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 } },
    })
    this.mesh = new THREE.InstancedMesh(geo, this.material, 2000)
    this.mesh.count = 0
    this.mesh.renderOrder = 3
    this.mesh.frustumCulled = false
    this.mesh.visible = false
  }

  setVolcanoes(list: Volcano[]): void {
    const count = Math.min(list.length, 2000)
    const mesh = this.mesh
    const dummy = new THREE.Object3D()
    const up = new THREE.Vector3(0, 1, 0)
    const glow = new Float32Array(count)
    const phase = new Float32Array(count)
    const positions: number[] = []
    for (let i = 0; i < count; i++) {
      const v = list[i]
      const radius = volcanoRadius(GLOBE_R, v.elev)
      const p = ll2xyz(v.lon, v.lat, radius)
      const normal = p.clone().normalize()
      dummy.position.copy(p)
      dummy.quaternion.setFromUnitVectors(up, normal)
      const s = coneScale(v.elev)
      dummy.scale.set(s, s, s)
      dummy.updateMatrix()
      mesh.setMatrixAt(i, dummy.matrix)
      const recency = eruptionRecency(v.last_year)
      glow[i] = recency
      phase[i] = (i * 2.399963) % (Math.PI * 2)
      positions.push(p.x, p.y, p.z)
    }
    mesh.count = count
    mesh.instanceMatrix.needsUpdate = true
    mesh.geometry.setAttribute('aGlow', new THREE.InstancedBufferAttribute(glow, 1))
    mesh.geometry.setAttribute('aPhase', new THREE.InstancedBufferAttribute(phase, 1))
    this.volcanoes = list.slice(0, count)
    mesh.visible = this.wanted && count > 0
    mesh.userData.volcanoes = this.volcanoes
  }

  /** Resolve a raycaster instanceId back to the volcano record. */
  volcanoAt(instanceId: number | undefined): Volcano | null {
    if (instanceId === undefined || instanceId < 0) return null
    return this.volcanoes[instanceId] || null
  }

  setVisible(v: boolean): void {
    this.wanted = !!v
    this.mesh.visible = v && this.volcanoes.length > 0
  }

  update(seconds: number): void { this.material.uniforms.uTime.value = seconds }

  dispose(): void {
    this.mesh.geometry.dispose()
    this.material.dispose()
  }
}
