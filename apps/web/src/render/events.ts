/** Real-time point events with Shadertoy-style effects.
 *  Mode 0 = earthquake shockwave, 1 = aircraft streak,
 *  2 = tropical cyclone spiral, 3 = CME expanding cloud.
 */
import * as THREE from 'three'
import { ll2xyz, GLOBE_R } from './geo'
import type { RealtimeEvent } from '../realtime'

const R = GLOBE_R * 1.035

const VERT = `
attribute vec3 aColor;
attribute float aSize;
attribute float aAge;
attribute float aAngle;
varying vec3 vColor;
varying float vAge;
varying float vAngle;
uniform float uTime;
uniform float uSizeScale;
void main(){
  vColor=aColor; vAge=aAge; vAngle=aAngle;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  float pulse = 1.0 + 0.14*sin(uTime*3.0 + position.x*23.0);
  gl_PointSize = aSize * uSizeScale * pulse * (7.0 / -mv.z);
  gl_Position = projectionMatrix * mv;
}`

const FRAG = `
precision highp float;
uniform float uTime;
uniform float uMode;
varying vec3 vColor;
varying float vAge;
varying float vAngle;
void main(){
  vec2 p = gl_PointCoord*2.0-1.0;
  float r = length(p);
  if(r>1.0) discard;
  float a=0.0;
  vec3 c=vColor;
  if(uMode < 0.5){
    // Earthquake: expanding shockwave ring + bright epicentre.
    float phase = fract(vAge*0.16);
    float ringR = 0.16 + phase*0.8;
    float ring = exp(-pow((r-ringR)*15.0,2.0)) * (1.0-phase);
    float core = exp(-r*r*45.0);
    a = ring*0.95 + core;
    c = mix(vec3(0.25,0.9,1.0), vColor, 0.45+0.55*core);
  } else if(uMode < 1.5){
    // Aircraft: directional streak rotated by true track.
    float ca=cos(vAngle), sa=sin(vAngle);
    vec2 q=vec2(p.x*ca-p.y*sa, p.x*sa+p.y*ca);
    float streak = exp(-abs(q.y)*26.0) * smoothstep(1.0,0.05,abs(q.x));
    float head = exp(-length(q-vec2(0.32,0.0))*9.0);
    a = streak*0.75 + head;
    c = mix(c, vec3(1.0), head*0.6);
  } else if(uMode < 2.5){
    // Cyclone: counter-rotating spiral arms.
    float ang = atan(p.y,p.x);
    float spiral = sin(ang*3.0 - r*11.0 + uTime*2.2)*0.5+0.5;
    float eye = exp(-r*r*90.0);
    a = spiral*exp(-r*r*3.2)*smoothstep(1.0,0.25,r) + eye;
    c = mix(c, vec3(1.0), eye*0.7);
  } else {
    // CME: expanding plasma cloud with a bright leading edge.
    float phase = fract(vAge*0.05);
    float front = 0.2 + phase*0.78;
    float disk = exp(-pow((r-front)*9.0,2.0))*(1.0-phase);
    float core = exp(-r*r*16.0);
    a = disk*0.85 + core;
    c = mix(vColor, vec3(1.0,0.9,0.5), core*0.55);
  }
  a = clamp(a,0.0,1.0);
  if(a<0.02) discard;
  gl_FragColor = vec4(c*(0.28+a*0.45), a*0.13);
}`

export type EventMode = 'quake' | 'flight' | 'storm' | 'cme'
const MODE_INDEX: Record<EventMode, number> = { quake: 0, flight: 1, storm: 2, cme: 3 }

export class EventLayer {
  readonly points: THREE.Points
  private material: THREE.ShaderMaterial
  private count = 0
  private mode: EventMode

  constructor(mode: EventMode) {
    this.mode = mode
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: {
        uTime: { value: 0 }, uMode: { value: MODE_INDEX[mode] },
        uSizeScale: { value: mode === 'quake' ? 8 : mode === 'flight' ? 3 : mode === 'storm' ? 10 : 6 },
      },
      transparent: true, blending: THREE.AdditiveBlending, depthWrite: false,
    })
    this.points = new THREE.Points(new THREE.BufferGeometry(), this.material)
    this.points.renderOrder = 7
    this.points.frustumCulled = false
  }

  setEvents(events: RealtimeEvent[]): void {
    const pos: number[] = [], col: number[] = [], size: number[] = [], age: number[] = [], ang: number[] = []
    const now = Date.now() / 1000
    // Cap dense feeds (OpenSky delivers ~6000) to a render-friendly budget.
    const step = this.mode === 'flight' ? Math.max(1, Math.ceil(events.length / 1500)) : 1
    for (let ei = 0; ei < events.length; ei += step) {
      const e = events[ei]
      if (e.lon == null || e.lat == null) continue
      const p = ll2xyz(e.lon, e.lat, R)
      pos.push(p.x, p.y, p.z)
      const v = e.values || {}
      let r = 0.4, g = 0.9, b = 1.0, sz = 12
      if (this.mode === 'quake') {
        const mag = Math.max(0, Number(v.mag) || 0)
        const t = Math.min(1, mag / 7)
        r = 0.2 + t * 0.8; g = 0.85 - t * 0.35; b = 1.0 - t * 0.8
        sz = 10 + t * 38
      } else if (this.mode === 'flight') {
        const alt = Number(v.altitude_m) || 0
        const t = Math.min(1, alt / 12000)
        r = 0.35 + t * 0.6; g = 0.75 + t * 0.25; b = 1.0
        sz = 6
      } else if (this.mode === 'storm') {
        const wind = Number(v.max_wind_kt) || 40
        const t = Math.min(1, wind / 140)
        r = 0.3 + t * 0.7; g = 0.5 + t * 0.4; b = 1.0 - t * 0.6
        sz = 46 + t * 30
      } else {
        const speed = Number(v.speed_kms) || 400
        const t = Math.min(1, Math.max(0, (speed - 250) / 1500))
        r = 0.4 + t * 0.6; g = 0.6 - t * 0.25; b = 1.0
        sz = 40 + t * 30
      }
      col.push(r, g, b)
      size.push(sz)
      const tObs = Date.parse(e.observed_at) / 1000
      age.push(Number.isFinite(tObs) ? Math.max(0, now - tObs) : 0)
      ang.push(((Number(v.track_deg) || 0) * Math.PI) / 180)
    }
    const geo = this.points.geometry
    geo.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3))
    geo.setAttribute('aColor', new THREE.Float32BufferAttribute(col, 3))
    geo.setAttribute('aSize', new THREE.Float32BufferAttribute(size, 1))
    geo.setAttribute('aAge', new THREE.Float32BufferAttribute(age, 1))
    geo.setAttribute('aAngle', new THREE.Float32BufferAttribute(ang, 1))
    geo.computeBoundingSphere()
    this.count = events.length
  }

  update(time: number): void { this.material.uniforms.uTime.value = time }

  setVisible(v: boolean): void { this.points.visible = v }
  getCount(): number { return this.count }
  dispose(): void { this.points.geometry.dispose(); this.material.dispose() }
}
