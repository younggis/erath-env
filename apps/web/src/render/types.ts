/** Shared types for the rendering engine. */
import type * as THREE from 'three'

export interface GridInfo {
  nx: number; ny: number
  lon0: number; lat0: number
  dx: number; dy: number
  wrap_longitude: boolean
}

export interface FieldData {
  frameId: string
  layerId: string
  palette: string
  range: [number, number]
  grid: GridInfo
  ncomp: number
  values: Float32Array
  vector?: boolean
  validTime?: string
}

export interface WindData {
  values: Float32Array
  grid: GridInfo
  ncomp: number
}

export interface StationPoint {
  id: string
  lon: number
  lat: number
  name?: string
  tempC?: number | null
  dewpointC?: number | null
  speedMs?: number | null
  visibility?: string | null
  observedAt?: string
}

export interface TerrainData {
  grid: GridInfo
  values: Float32Array
  exaggeration?: number
}

/** 3D cloud-density volume from multi-level RH (xyz layout). */
export interface VolumeData {
  nx: number
  ny: number
  nz: number
  levelsHpa: number[]
  values: Float32Array  // index = x + y*nx + z*nx*ny
  grid: GridInfo
}

export interface PickResult {
  lon: number
  lat: number
  station?: StationPoint
  screenX: number
  screenY: number
}

export type PickHandler = (result: PickResult) => void

export interface RenderStats {
  fps: number
  particles: number
  drawCalls: number
  triangles: number
}
