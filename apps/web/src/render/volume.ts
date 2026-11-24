/** Volumetric cloud renderer — raymarching a 3D RH-derived density texture.
 *
 * The density is a visualisation PROXY from multi-level relative humidity,
 * NOT true cloud water. A shell sphere around the globe is raymarched in the
 * fragment shader; each ray accumulates cloud density inside the shell.
 */
import * as THREE from 'three'
import { GLOBE_R } from './geo'
import type { VolumeData } from './types'

// Cloud shell radial bounds (globe radius units). 1000 hPa ~ surface,
// 500 hPa ~ upper troposphere. Exaggerated thickness for visibility.
const R_IN = GLOBE_R * 1.012
const R_OUT = GLOBE_R * 1.16

const VERT = /* glsl */`
out vec3 vWorld;
void main(){
  vec4 wp = modelMatrix * vec4(position, 1.0);
  vWorld = wp.xyz;
  gl_Position = projectionMatrix * viewMatrix * wp;
}`

const FRAG = /* glsl */`
precision highp float;
precision highp sampler3D;
uniform sampler3D uVol;
uniform vec3 uCamPos;
uniform vec3 uSunDir;
uniform float uRIn;
uniform float uROut;
uniform float uDensity;
uniform float uSteps;
uniform float uOpacity;
uniform float uTime;
in vec3 vWorld;
out vec4 fragColor;

float hash12(vec2 p){
  vec3 p3 = fract(vec3(p.xyx) * 0.1031);
  p3 += dot(p3, p3.yzx + 33.33);
  return fract((p3.x + p3.y) * p3.z);
}
// Henyey-Greenstein phase: clouds brighten toward the sun.
float hg(float cosT, float g){
  float g2 = g * g;
  return (1.0 - g2) / max(0.001, pow(1.0 + g2 - 2.0 * g * cosT, 1.5));
}
float sampleDensity(vec3 p){
  float r = length(p);
  if(r < uRIn || r > uROut) return 0.0;
  vec3 n = p / r;
  float lat = asin(clamp(n.y, -1.0, 1.0));
  float lon = atan(n.x, n.z);
  vec2 uv = vec2(lon * 0.15915494 + 0.5, lat * 0.31830989 + 0.5);
  float z = clamp((r - uRIn) / max(1e-4, uROut - uRIn), 0.0, 1.0);
  return smoothstep(0.18, 0.55, texture(uVol, vec3(uv, z)).r);
}

// ray-sphere intersection; returns (tNear, tFar), or vec2(-1) if no hit.
vec2 hitSphere(vec3 ro, vec3 rd, float R){
  float b = dot(ro, rd);
  float c = dot(ro, ro) - R*R;
  float h = b*b - c;
  if(h < 0.0) return vec2(-1.0);
  h = sqrt(h);
  return vec2(-b - h, -b + h);
}

void main(){
  vec3 ro = uCamPos;
  vec3 rd = normalize(vWorld - uCamPos);
  vec2 outer = hitSphere(ro, rd, uROut);
  if(outer.y < 0.0) discard;
  float t0 = max(outer.x, 0.0);
  float t1 = outer.y;
  // Stop at the Earth surface: clouds behind the globe must not show through.
  vec2 inner = hitSphere(ro, rd, uRIn);
  if(inner.x > 0.0) t1 = min(t1, inner.x);
  if(t1 <= t0) discard;

  vec3 sun = normalize(uSunDir);
  // Adaptive step count: grazing rays through the shell need more samples.
  float steps = clamp(uSteps * (0.65 + 0.35 * (t1 - t0) / max(0.01, uROut - uRIn)),
                      16.0, uSteps);
  float dt = (t1 - t0) / steps;
  float jitter = hash12(gl_FragCoord.xy + floor(uTime * 24.0));
  vec4 acc = vec4(0.0);
  for(float i = 0.0; i < 96.0; i++){
    if(i >= steps) break;
    float t = t0 + (i + jitter) * dt;
    vec3 p = ro + rd * t;
    float density = sampleDensity(p);
    if(density <= 0.001) continue;
    float a = clamp(density * uDensity * (dt / 0.01), 0.0, 1.0);

    // Short light march toward the sun gives soft self-shadowing inside clouds.
    float shadow = 0.0;
    vec3 lp = p;
    for(float j = 0.0; j < 4.0; j++){
      lp += sun * 0.045;
      shadow += sampleDensity(lp) * 0.25;
    }
    float trans = exp(-shadow * 1.6);
    float cosT = dot(rd, sun);
    float phase = 0.55 + 0.45 * hg(cosT, 0.35);
    float powder = 1.0 - exp(-density * 2.5);
    vec3 cloud = mix(vec3(0.52, 0.64, 0.82), vec3(1.0, 0.98, 0.94), trans);
    cloud *= (0.35 + 0.65 * trans) * phase * (0.75 + 0.25 * powder);
    acc.rgb += (1.0 - acc.a) * a * cloud;
    acc.a   += (1.0 - acc.a) * a;
    if(acc.a > 0.98) break;
  }
  acc.a *= uOpacity;
  if(acc.a < 0.003) discard;
  fragColor = vec4(acc.rgb, acc.a);
}`

export class VolumetricCloudLayer {
  readonly mesh: THREE.Mesh
  private material: THREE.ShaderMaterial
  private texture: THREE.Data3DTexture | null = null

  constructor() {
    this.material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3,
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: {
        uVol: { value: null },
        uCamPos: { value: new THREE.Vector3() },
        uSunDir: { value: new THREE.Vector3(1, 0, 0) },
        uRIn: { value: R_IN }, uROut: { value: R_OUT },
        uDensity: { value: 0.08 }, uSteps: { value: 48 }, uOpacity: { value: 1 },
        uTime: { value: 0 },
      },
      transparent: true, depthWrite: false, depthTest: false,
      side: THREE.BackSide, blending: THREE.NormalBlending,
    })
    // Back faces: the raymarch reconstructs the real entry/exit, so drawing the
    // far shell guarantees coverage even when the camera zooms inside the shell.
    this.mesh = new THREE.Mesh(new THREE.SphereGeometry(R_OUT, 48, 32), this.material)
    this.mesh.renderOrder = 3.5
    this.mesh.frustumCulled = false
    this.mesh.visible = false
  }

  setVolume(data: VolumeData | null): void {
    this.texture?.dispose()
    this.texture = null
    if (!data || !data.values || data.values.length !== data.nx * data.ny * data.nz) {
      this.mesh.visible = false
      this.material.uniforms.uVol.value = null
      return
    }
    // Copy into a plain ArrayBuffer-backed view to satisfy WebGL's BufferSource type.
    const values = new Float32Array(data.values)
    const tex = new THREE.Data3DTexture(values, data.nx, data.ny, data.nz)
    tex.format = THREE.RedFormat
    tex.type = THREE.FloatType
    tex.minFilter = THREE.LinearFilter
    tex.magFilter = THREE.LinearFilter
    tex.wrapS = THREE.RepeatWrapping   // longitude wraps
    tex.wrapT = THREE.ClampToEdgeWrapping
    tex.wrapR = THREE.ClampToEdgeWrapping
    tex.unpackAlignment = 1
    tex.needsUpdate = true
    this.texture = tex
    this.material.uniforms.uVol.value = tex
    this.mesh.visible = true
  }

  update(camPos: THREE.Vector3, sunDir: THREE.Vector3, time = 0): void {
    ;(this.material.uniforms.uCamPos.value as THREE.Vector3).copy(camPos)
    ;(this.material.uniforms.uSunDir.value as THREE.Vector3).copy(sunDir)
    this.material.uniforms.uTime.value = time
  }

  setVisible(v: boolean): void { this.mesh.visible = v && !!this.texture }
  setDensity(v: number): void { this.material.uniforms.uDensity.value = v }
  setSteps(v: number): void { this.material.uniforms.uSteps.value = v }
  hasData(): boolean { return !!this.texture }

  dispose(): void {
    this.texture?.dispose()
    this.mesh.geometry.dispose()
    this.material.dispose()
  }
}
