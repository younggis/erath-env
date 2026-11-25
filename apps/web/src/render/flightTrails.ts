/** Short ADS-B trail arcs lifted to each aircraft's barometric altitude. */
import * as THREE from 'three'
import { EARTH_KM, flightRadius, ll2xyz } from './geo'
import type { RealtimeEvent } from '../realtime'

const TRAIL_KM = 28

function destination(latDeg: number, lonDeg: number, bearing: number,
                     angle: number): [number, number] {
  const la = latDeg * Math.PI / 180
  const lo = lonDeg * Math.PI / 180
  const sinLa = Math.sin(la) * Math.cos(angle) + Math.cos(la) * Math.sin(angle) * Math.cos(bearing)
  const lat2 = Math.asin(Math.max(-1, Math.min(1, sinLa)))
  const lon2 = lo + Math.atan2(Math.sin(bearing) * Math.sin(angle) * Math.cos(la),
                               Math.cos(angle) - Math.sin(la) * sinLa)
  return [lon2 * 180 / Math.PI, lat2 * 180 / Math.PI]
}

export class FlightTrailLayer {
  readonly lines: THREE.LineSegments
  private material: THREE.LineBasicMaterial

  constructor() {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(0), 3))
    this.material = new THREE.LineBasicMaterial({
      color: 0x8fe8ff, transparent: true, opacity: 0.5, depthWrite: false,
      blending: THREE.AdditiveBlending,
    })
    this.lines = new THREE.LineSegments(geo, this.material)
    this.lines.renderOrder = 7
    this.lines.frustumCulled = false
    this.lines.visible = false
  }

  setFlights(events: RealtimeEvent[]): void {
    const positions: number[] = []
    const step = Math.max(1, Math.ceil(events.length / 1500))
    const angle = TRAIL_KM / EARTH_KM
    for (let i = 0; i < events.length; i += step) {
      const e = events[i]
      if (e.lon == null || e.lat == null) continue
      const v = e.values || {}
      const raw = v.baro_altitude_m ?? v.altitude_m
      const alt = Number(raw) || 0
      if (alt < 0) continue // never draw below the surface
      const radius = flightRadius(alt)
      const track = Number(v.true_track_deg ?? v.track_deg) || 0
      const [lon0, lat0] = destination(e.lat, e.lon, (track + 180) * Math.PI / 180, angle)
      const a = ll2xyz(lon0, lat0, radius)
      const b = ll2xyz(e.lon, e.lat, radius)
      positions.push(a.x, a.y, a.z, b.x, b.y, b.z)
    }
    this.lines.geometry.setAttribute('position',
      new THREE.BufferAttribute(new Float32Array(positions), 3))
  }

  setVisible(v: boolean): void {
    this.lines.visible = v && this.lines.geometry.getAttribute('position').count > 0
  }

  dispose(): void {
    this.lines.geometry.dispose()
    this.material.dispose()
  }
}
