/** Animated tropical-cyclone tracks from GDACS timeline observations/forecasts. */
import * as THREE from 'three'
import { ll2xyz, GLOBE_R } from './geo'
import type { CycloneTrack } from '../realtime'

const R = GLOBE_R * 1.052

const VERT = `
attribute float aProgress;
attribute float aForecast;
varying float vProgress;
varying float vForecast;
void main(){
  vProgress = aProgress; vForecast = aForecast;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`

const FRAG = `
precision highp float;
uniform float uTime;
uniform float uOpacity;
varying float vProgress;
varying float vForecast;
void main(){
  float pulse = 0.55 + 0.45 * sin(vProgress * 34.0 - uTime * 3.2);
  vec3 observed = vec3(0.35, 0.90, 1.0);
  vec3 forecast = vec3(1.0, 0.62, 0.30);
  vec3 c = mix(observed, forecast, step(0.5, vForecast));
  float a = (0.35 + 0.55 * pulse) * uOpacity * (vForecast > 0.5 ? 0.75 : 1.0);
  gl_FragColor = vec4(c, a);
}`

export class TrackLayer {
  readonly lines: THREE.LineSegments
  private material: THREE.ShaderMaterial
  private trackCount = 0

  constructor() {
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: { uTime: { value: 0 }, uOpacity: { value: 0.9 } },
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    })
    this.lines = new THREE.LineSegments(new THREE.BufferGeometry(), this.material)
    this.lines.renderOrder = 6.5
    this.lines.frustumCulled = false
    this.lines.visible = false
  }

  setTracks(tracks: CycloneTrack[]): void {
    const pos: number[] = []
    const progress: number[] = []
    const forecast: number[] = []
    let count = 0
    for (const track of tracks) {
      const pts = track.points || []
      for (let i = 1; i < pts.length; i++) {
        const a = ll2xyz(pts[i - 1].lon, pts[i - 1].lat, R)
        const b = ll2xyz(pts[i].lon, pts[i].lat, R)
        pos.push(a.x, a.y, a.z, b.x, b.y, b.z)
        progress.push((i - 1) / Math.max(1, pts.length - 1), i / Math.max(1, pts.length - 1))
        const isForecast = pts[i].forecast ? 1 : 0
        forecast.push(isForecast, isForecast)
      }
      if (pts.length > 1) count++
    }
    const geo = this.lines.geometry
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    geo.setAttribute('aProgress', new THREE.Float32BufferAttribute(progress, 1))
    geo.setAttribute('aForecast', new THREE.Float32BufferAttribute(forecast, 1))
    geo.computeBoundingSphere()
    this.trackCount = count
    this.lines.visible = count > 0 && this.lines.userData.wanted !== false
  }

  update(time: number): void { this.material.uniforms.uTime.value = time }
  setVisible(v: boolean): void {
    this.lines.userData.wanted = v
    this.lines.visible = v && this.trackCount > 0
  }
  getCount(): number { return this.trackCount }
  dispose(): void { this.lines.geometry.dispose(); this.material.dispose() }
}
