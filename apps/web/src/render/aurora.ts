/** Real-time aurora curtain driven by NOAA SWPC OVATION probability.
 *  A translucent sphere just above the surface samples the probability grid
 *  at each fragment and adds animated, flowing green/violet curtains.
 */
import * as THREE from 'three'
import { GLOBE_R } from './geo'
import type { AuroraData } from '../realtime'

const NOISE = `
float hash31(vec3 p){ p=fract(p*0.1031); p+=dot(p,p.yzx+33.33); return fract((p.x+p.y)*p.z); }
float noise3(vec3 p){
  vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(mix(hash31(i),hash31(i+vec3(1,0,0)),f.x),mix(hash31(i+vec3(0,1,0)),hash31(i+vec3(1,1,0)),f.x),f.y),
             mix(mix(hash31(i+vec3(0,0,1)),hash31(i+vec3(1,0,1)),f.x),mix(hash31(i+vec3(0,1,1)),hash31(i+vec3(1,1,1)),f.x),f.y),f.z);
}`

const VERT = `
varying vec3 vPos;
void main(){
  vPos = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);
}`

const FRAG = `
precision highp float;
uniform sampler2D uAurora;
uniform float uTime;
uniform float uKp;
uniform float uOpacity;
varying vec3 vPos;
${NOISE}
void main(){
  float r = length(vPos);
  vec3 n = vPos / max(r, 0.0001);
  float lat = degrees(asin(clamp(n.y,-1.0,1.0)));
  float lon = degrees(atan(n.z, n.x));
  vec2 uv = vec2((lon+180.0)/360.0, (lat+90.0)/180.0);
  float prob = texture2D(uAurora, uv).r;
  // Soft polar mask, stronger in the auroral oval (55-75°).
  float mask = smoothstep(58.0, 66.0, abs(lat)) * (1.0 - smoothstep(76.0, 85.0, abs(lat)));
  // Flowing curtain structure.
  float t = uTime * 0.06;
  float wave = noise3(vec3(lon*0.09, lat*0.12, t)) * 0.6
             + noise3(vec3(lon*0.22, lat*0.25, t*1.7)) * 0.4;
  float curtain = smoothstep(0.35, 0.85, wave);
  float ray = 0.55 + 0.45*sin(lon*0.9 + uTime*0.7 + wave*6.0);
  float kpGain = 0.12 + clamp(uKp,0.0,9.0)*0.05;
  float a = prob * mask * curtain * ray * kpGain * uOpacity * 0.16;
  if(a < 0.004) discard;
  vec3 green = vec3(0.12, 0.85, 0.42);
  vec3 violet = vec3(0.5, 0.2, 0.85);
  float mixv = smoothstep(0.3, 0.9, wave) * (0.4 + abs(lat)/90.0*0.6);
  vec3 col = mix(green, violet, mixv) * (0.35 + a*0.6);
  gl_FragColor = vec4(col, clamp(a,0.0,0.3));
}`

export class AuroraLayer {
  readonly mesh: THREE.Mesh
  private material: THREE.ShaderMaterial
  private texture: THREE.DataTexture | null = null

  constructor() {
    this.material = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: {
        uAurora: { value: null }, uTime: { value: 0 },
        uKp: { value: 0 }, uOpacity: { value: 1 },
      },
      transparent: true, blending: THREE.AdditiveBlending,
      depthWrite: false, side: THREE.FrontSide,
    })
    this.mesh = new THREE.Mesh(
      new THREE.SphereGeometry(GLOBE_R * 1.045, 96, 64),
      this.material,
    )
    this.mesh.renderOrder = 5
  }

  setData(data: AuroraData | null): void {
    if (!data || !data.data || !data.nx || !data.ny) {
      this.mesh.visible = false
      return
    }
    const { nx, ny } = data
    const pixels = new Uint8Array(nx * ny * 4)
    for (let i = 0; i < nx * ny; i++) {
      const v = Math.max(0, Math.min(255, data.data[i] || 0))
      pixels[i * 4] = v; pixels[i * 4 + 1] = v; pixels[i * 4 + 2] = v; pixels[i * 4 + 3] = 255
    }
    this.texture?.dispose()
    this.texture = new THREE.DataTexture(pixels, nx, ny, THREE.RGBAFormat)
    this.texture.wrapS = THREE.RepeatWrapping
    this.texture.wrapT = THREE.ClampToEdgeWrapping
    this.texture.minFilter = THREE.LinearFilter
    this.texture.magFilter = THREE.LinearFilter
    this.texture.needsUpdate = true
    this.material.uniforms.uAurora.value = this.texture
    this.material.uniforms.uKp.value = data.kp || 0
    this.mesh.visible = true
  }

  update(time: number): void { this.material.uniforms.uTime.value = time }
  setVisible(v: boolean): void {
    this.mesh.userData.wanted = v
    this.mesh.visible = v && !!this.texture
  }
  setOpacity(v: number): void { this.material.uniforms.uOpacity.value = v }
  hasData(): boolean { return !!this.texture }
  dispose(): void { this.mesh.geometry.dispose(); this.material.dispose(); this.texture?.dispose() }
}
