/** Colour palettes for the render engine. Returns RGBA (0..255, alpha 0..255). */
export type RGBA = [number, number, number, number]

const STOPS: Record<string, Array<[number, number[]]>> = {
  temperature: [
    [0, [30, 12, 70]], [0.18, [38, 70, 175]], [0.38, [55, 165, 205]],
    [0.52, [115, 205, 150]], [0.68, [240, 215, 95]], [0.84, [235, 120, 50]], [1, [175, 28, 45]],
  ],
  humidity: [
    [0, [74, 62, 48]], [0.3, [150, 140, 88]], [0.55, [110, 190, 140]],
    [0.8, [50, 150, 210]], [1, [40, 68, 225]],
  ],
  pressure: [
    [0, [55, 35, 125]], [0.35, [45, 120, 200]], [0.5, [225, 230, 230]],
    [0.7, [235, 160, 80]], [1, [160, 35, 55]],
  ],
  // Cloud cover: 0% = clear sky -> transparent; thicker cloud -> more opaque.
  cloud: [[0, [90, 110, 140, 0]], [0.15, [90, 110, 140, 90]], [0.45, [170, 195, 215, 170]], [0.75, [220, 232, 240, 220]], [1, [255, 255, 255, 255]]],
  visibility: [[0, [120, 40, 40]], [0.25, [220, 130, 60]], [0.5, [230, 220, 130]], [0.75, [130, 210, 170]], [1, [60, 180, 230]]],
  // Wind: low speeds fade out so the basemap stays visible; only stronger
  // winds (jet streams) paint opaque colour. Alpha is a ramp, not a flat 245.
  wind: [[0, [60, 140, 255, 0]], [0.18, [80, 225, 225, 90]], [0.4, [170, 255, 120, 170]], [0.68, [255, 215, 70, 225]], [1, [255, 90, 70, 255]]],
  // Brightness temperature: warm (low cloud) white -> cold (high cloud) dark.
  bt: [[0, [252, 252, 252]], [0.3, [185, 210, 235]], [0.55, [95, 135, 195]], [0.78, [40, 55, 125]], [1, [10, 12, 30]]],
  bt_gray_green: [[0, [250, 250, 250]], [0.3, [200, 225, 215]], [0.55, [120, 175, 165]], [0.78, [55, 105, 110]], [1, [12, 30, 40]]],
  cloudwater: [[0, [0, 0, 0, 0]], [0.2, [80, 150, 210, 90]], [0.5, [150, 220, 240, 170]], [1, [255, 255, 255, 235]]],
  // Precipitation: alpha ramps from 0 (no rain -> transparent, basemap shows
  // through) to opaque for heavy rain. 0 mm must never paint a white sheet.
  precip: [[0, [90, 180, 230, 0]], [0.12, [90, 180, 230, 120]], [0.3, [40, 110, 210, 200]], [0.6, [150, 60, 200, 240]], [1, [220, 40, 120, 255]]],
  // Snow depth: 0 m = no snow -> transparent (basemap shows through); alpha
  // ramps up with accumulation. 0 m must not paint a pale sheet over land.
  snow: [[0, [150, 200, 235, 0]], [0.12, [150, 200, 235, 110]], [0.4, [90, 150, 220, 190]], [0.7, [60, 110, 200, 235]], [1, [40, 80, 180, 255]]],
  cape: [[0, [30, 50, 80]], [0.3, [60, 160, 120]], [0.6, [220, 210, 90]], [0.85, [240, 130, 50]], [1, [220, 40, 60]]],
  height: [[0, [40, 30, 90]], [0.3, [50, 110, 180]], [0.5, [220, 230, 230]], [0.7, [220, 150, 70]], [1, [150, 30, 50]]],
  // Vertical velocity is bipolar (-2..2): zero = no motion (the vast majority
  // of the globe). Fade the zero band to transparent so only genuine ascent
  // (blue) / descent (red) is painted over the basemap.
  vvel: [[0, [80, 200, 220, 255]], [0.3, [120, 215, 220, 150]], [0.5, [230, 230, 230, 0]], [0.7, [225, 160, 150, 150]], [1, [200, 60, 80, 255]]],
  rgb: [[0, [40, 80, 150]], [0.5, [120, 200, 140]], [1, [255, 240, 210]]],
  default: [[0, [40, 60, 80]], [0.5, [120, 180, 200]], [1, [240, 245, 250]]],
}

function lerp(a: number, b: number, t: number): number { return a + (b - a) * t }

// Heavily skewed fields (e.g. precipitation) need a log colour scale, otherwise
// the vast majority of pixels map to the palest colour and look like no data.
const LOG_PALETTES = new Set(['precip'])
const LOG_FLOOR = 0.05

export function scaledNorm(name: string, value: number, range: [number, number]): number {
  if (!LOG_PALETTES.has(name)) {
    return Math.max(0, Math.min(1, (value - range[0]) / Math.max(1e-9, range[1] - range[0])))
  }
  // Map [floor .. max] logarithmically into [0 .. 1].
  const lo = Math.log10(Math.max(LOG_FLOOR, range[0] + LOG_FLOOR))
  const hi = Math.log10(Math.max(LOG_FLOOR * 10, range[1]))
  const v = Math.log10(Math.max(LOG_FLOOR, value))
  return Math.max(0, Math.min(1, (v - lo) / Math.max(1e-9, hi - lo)))
}

export function rgbaFor(name: string, value: number, range: [number, number]): RGBA {
  const stops = STOPS[name] || STOPS.default
  const x = scaledNorm(name, value, range)
  for (let i = 0; i < stops.length - 1; i++) {
    const [p0, c0] = stops[i]
    const [p1, c1] = stops[i + 1]
    if (x >= p0 && x <= p1) {
      const f = (x - p0) / Math.max(1e-9, p1 - p0)
      const out = c0.map((v, k) => Math.round(lerp(v, c1[k], f)))
      return [out[0], out[1], out[2], out.length === 4 ? out[3] : 245] as RGBA
    }
  }
  const last = stops[stops.length - 1][1]
  return [last[0], last[1], last[2], last.length === 4 ? last[3] : 245] as RGBA
}

export function rgbFor(name: string, value: number, range: [number, number]): [number, number, number] {
  const c = rgbaFor(name, value, range)
  return [c[0], c[1], c[2]]
}

export function speedOf(u: number, v: number): number {
  if (!Number.isFinite(u) || !Number.isFinite(v)) return NaN
  return Math.hypot(u, v)
}

export function cssGradient(name: string, range: [number, number], steps = 14): string {
  return Array.from({ length: steps }, (_, i) => {
    const v = range[0] + (i / (steps - 1)) * (range[1] - range[0])
    const c = rgbaFor(name, v, range)
    return `rgb(${c[0]},${c[1]},${c[2]})`
  }).join(',')
}
