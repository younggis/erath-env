/** GLSL shader library — Shadertoy-inspired procedural effects. */
import * as THREE from 'three'

/* ------------------------------------------------------------------ shared noise */
const NOISE = /* glsl */ `
float hash21(vec2 p){ p=fract(p*vec2(123.34,345.45)); p+=dot(p,p+34.345); return fract(p.x*p.y); }
float hash31(vec3 p){ p=fract(p*0.1031); p+=dot(p,p.yzx+33.33); return fract((p.x+p.y)*p.z); }
float noise3(vec3 p){
  vec3 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  float n000=hash31(i), n100=hash31(i+vec3(1,0,0)), n010=hash31(i+vec3(0,1,0)), n110=hash31(i+vec3(1,1,0));
  float n001=hash31(i+vec3(0,0,1)), n101=hash31(i+vec3(1,0,1)), n011=hash31(i+vec3(0,1,1)), n111=hash31(i+vec3(1,1,1));
  return mix(mix(mix(n000,n100,f.x),mix(n010,n110,f.x),f.y),
             mix(mix(n001,n101,f.x),mix(n011,n111,f.x),f.y),f.z);
}
float fbm3(vec3 p){
  float v=0.0, a=0.5;
  for(int i=0;i<5;i++){ v+=a*noise3(p); p*=2.02; a*=0.5; }
  return v;
}
float noise2(vec2 p){
  vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
  return mix(mix(hash21(i),hash21(i+vec2(1,0)),f.x),
             mix(hash21(i+vec2(0,1)),hash21(i+vec2(1,1)),f.x),f.y);
}
`

/* ------------------------------------------------------------------ starfield sky */
export const SKY_VERT = /* glsl */ `
varying vec3 vDir;
void main(){
  vDir = normalize((modelMatrix * vec4(position,1.0)).xyz);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);
}`

export const SKY_FRAG = /* glsl */ `
uniform float uTime;
varying vec3 vDir;
${NOISE}
void main(){
  vec3 d = normalize(vDir);
  float t = uTime*0.012;
  // Deep-space nebula using layered fbm, tinted blue/purple/teal.
  float n1 = fbm3(d*2.6 + vec3(t,0.0,0.0));
  float n2 = fbm3(d*5.5 - vec3(0.0,t*0.6,t*0.3));
  vec3 neb = mix(vec3(0.006,0.012,0.035), vec3(0.055,0.035,0.13), smoothstep(0.35,0.8,n1));
  neb += vec3(0.02,0.10,0.20) * pow(n2,3.0) * 0.8;
  neb += vec3(0.16,0.06,0.22) * pow(fbm3(d*1.7+7.3),4.0) * 0.6;
  // Milky-way-like band inclined to the ecliptic.
  float band = exp(-pow(dot(d, normalize(vec3(0.35,0.82,0.45)))*3.2,2.0));
  neb += vec3(0.10,0.13,0.22) * band * (0.4+0.6*n1);

  // Procedural stars on a high-density spherical grid.
  vec3 sp = d*420.0;
  vec3 cell = floor(sp);
  float h = hash31(cell);
  vec3 f = fract(sp)-0.5;
  float r = length(f);
  float twinkle = 0.75 + 0.25*sin(uTime*2.2 + h*90.0);
  float star = step(0.9935,h) * smoothstep(0.32,0.0,r) * twinkle;
  float glow = step(0.9988,h) * exp(-r*9.0) * 0.8;
  vec3 starCol = mix(vec3(0.6,0.8,1.0), vec3(1.0,0.85,0.65), hash31(cell+11.3));
  vec3 col = neb + starCol*(star + glow);
  gl_FragColor = vec4(col,1.0);
}`

/* ------------------------------------------------------------------ earth surface */
export const EARTH_VERT = /* glsl */ `
varying vec2 vUv;
varying vec3 vNormalW;
varying vec3 vWorldPos;
void main(){
  vUv = uv;
  vNormalW = normalize(mat3(modelMatrix)*normal);
  vec4 wp = modelMatrix*vec4(position,1.0);
  vWorldPos = wp.xyz;
  gl_Position = projectionMatrix*viewMatrix*wp;
}`

export const EARTH_FRAG = /* glsl */ `
uniform sampler2D uMap;
uniform sampler2D uNightMap;
uniform vec3 uSunDir;
uniform vec3 uCameraPos;
uniform float uTime;
uniform float uNightLights;
uniform float uCloudStrength;
varying vec2 vUv;
varying vec3 vNormalW;
varying vec3 vWorldPos;
${NOISE}

void main(){
  vec3 N = normalize(vNormalW);
  vec3 V = normalize(uCameraPos - vWorldPos);
  vec3 L = normalize(uSunDir);
  float ndl = dot(N,L);
  vec3 albedo = texture2D(uMap, vUv).rgb;

  // Ocean mask from colour: blue-dominant pixels.
  float ocean = smoothstep(0.02,0.22, albedo.b - max(albedo.r,albedo.g));

  // Diffuse day lighting.
  float dayAmt = smoothstep(-0.15,0.20,ndl);
  vec3 day = albedo * (0.30 + 0.90*max(ndl,0.0));

  // Ocean specular sun glint.
  vec3 H = normalize(L+V);
  float spec = pow(max(dot(N,H),0.0),80.0) * ocean * max(ndl,0.0);
  day += vec3(0.75,0.88,1.0)*spec*1.4;

  // Warm terminator band.
  float term = exp(-pow(ndl*5.0,2.0));
  day += vec3(1.0,0.42,0.15)*term*0.30;

  // Night side: REAL NASA Black Marble city lights (no synthetic noise).
  vec3 nightTex = texture2D(uNightMap, vUv).rgb;
  float lum = dot(nightTex, vec3(0.299,0.587,0.114));
  vec3 night = albedo*0.045 + vec3(0.006,0.012,0.032);
  // Boost the real lights gently; they carry genuine city footprints.
  night += nightTex * (0.8 + 2.0*lum) * uNightLights;

  vec3 col = mix(night, day, dayAmt);

  // Animated thin cirrus veil (procedural, kept sparse so the map stays visible).
  float c = fbm3(vec3(vUv*vec2(9.0,4.5), uTime*0.008));
  float cloud = smoothstep(0.74,0.92,c) * uCloudStrength * max(ndl+0.2,0.0);
  col = mix(col, col*0.88+vec3(0.10,0.13,0.18), cloud*0.20);

  // Fresnel atmospheric rim, stronger on sunlit limb.
  float fres = pow(1.0-max(dot(N,V),0.0),3.5);
  col += vec3(0.25,0.55,1.0)*fres*(0.25+0.75*max(ndl,0.0))*0.55;

  gl_FragColor = vec4(col,1.0);
}`

/* ------------------------------------------------------------------ atmosphere glow */
export const ATMOS_VERT = /* glsl */ `
varying vec3 vNormalW;
varying vec3 vWorldPos;
void main(){
  vNormalW = normalize(mat3(modelMatrix)*normal);
  vec4 wp = modelMatrix*vec4(position,1.0);
  vWorldPos = wp.xyz;
  gl_Position = projectionMatrix*viewMatrix*wp;
}`

export const ATMOS_FRAG = /* glsl */ `
uniform vec3 uSunDir;
uniform vec3 uCameraPos;
uniform float uTime;
varying vec3 vNormalW;
varying vec3 vWorldPos;
void main(){
  vec3 N = normalize(vNormalW);
  vec3 V = normalize(uCameraPos - vWorldPos);
  vec3 L = normalize(uSunDir);
  float rim = pow(1.0 - abs(dot(N,V)), 3.0);
  float sun = max(dot(N,L),0.0);
  // Rayleigh-ish: blue on the day limb, orange near the terminator, deep blue at night.
  vec3 blue = vec3(0.22,0.55,1.0);
  vec3 warm = vec3(1.0,0.42,0.16);
  vec3 night = vec3(0.03,0.08,0.25);
  vec3 col = mix(night, blue, smoothstep(-0.25,0.6,sun));
  col = mix(col, warm, exp(-pow(sun*3.5,2.0))*0.7);
  float alpha = rim*(0.3+0.7*smoothstep(-0.4,0.5,sun));
  gl_FragColor = vec4(col*1.25, alpha*0.42);
}`

/* ------------------------------------------------------------------ sun flare (billboard) */
export const SUN_VERT = /* glsl */ `
varying vec2 vUv;
void main(){ vUv=uv; gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0); }`

export const SUN_FRAG = /* glsl */ `
uniform float uTime;
varying vec2 vUv;
${NOISE}
void main(){
  vec2 p = (vUv-0.5)*2.0;
  float r = length(p);
  float core = exp(-r*r*160.0)*1.2;
  float halo = exp(-r*r*18.0)*0.35;
  float rays = pow(max(0.0,1.0-abs(sin(atan(p.y,p.x)*8.0+uTime*0.1))),12.0)*exp(-r*3.0)*0.25;
  float sparkle = (hash31(vec3(floor(p*180.0),floor(uTime*4.0)))>0.998)?exp(-r*10.0)*0.6:0.0;
  vec3 col = vec3(1.0,0.92,0.72)*core + vec3(0.55,0.75,1.0)*halo + vec3(1.0,0.78,0.45)*rays + vec3(1.0)*sparkle;
  float a = clamp(core+halo+rays+sparkle,0.0,1.0) * smoothstep(1.0,0.55,r);
  gl_FragColor = vec4(col,a);
}`

/* ------------------------------------------------------------------ graticule glow */
export const GRAT_VERT = /* glsl */ `
attribute float aPhase;
varying float vPhase;
uniform float uTime;
void main(){
  vPhase = aPhase;
  vec3 p = position;
  gl_Position = projectionMatrix*modelViewMatrix*vec4(p,1.0);
}`

export const GRAT_FRAG = /* glsl */ `
varying float vPhase;
uniform float uTime;
void main(){
  float pulse = 0.55+0.45*sin(uTime*1.4+vPhase*6.28);
  gl_FragColor = vec4(0.35,0.72,1.0, 0.10+0.16*pulse);
}`

/** Build the earth ShaderMaterial with the given texture. */
export function makeEarthMaterial(texture: THREE.Texture | null, nightTexture: THREE.Texture | null): THREE.ShaderMaterial {
  return new THREE.ShaderMaterial({
    vertexShader: EARTH_VERT,
    fragmentShader: EARTH_FRAG,
    uniforms: {
      uMap: { value: texture },
      uNightMap: { value: nightTexture },
      uSunDir: { value: new THREE.Vector3(6, 3.5, 5).normalize() },
      uCameraPos: { value: new THREE.Vector3() },
      uTime: { value: 0 },
      uNightLights: { value: 1.0 },
      uCloudStrength: { value: 0.35 },
    },
  })
}
