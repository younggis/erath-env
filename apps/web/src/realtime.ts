/** Real-time event & space-weather API client. */

export interface RealtimeEvent {
  observation_id: number
  station_id: string
  source_id: string
  observed_at: string
  lon: number
  lat: number
  values: Record<string, any>
}

export interface AuroraData {
  observation_time: string
  forecast_time: string
  nx: number
  ny: number
  lat0: number
  lat1: number
  lon0: number
  lon1: number
  data: number[]
  kp: number | null
  received_at: string
}

export interface SolarWindData {
  received_at: string
  time: string
  speed_kms: number
  density_pcc: number
  temperature_k: number
  bz_gsm: number | null
  kp: number | null
  history: Array<{ time: string; speed: number; density: number; temperature: number }>
}

export interface CycloneTrack {
  id: string
  name: string | null
  source: string | null
  points: Array<{
    lon: number
    lat: number
    time: string
    wind_kmh: number | null
    status: string | null
    forecast: boolean
  }>
}

export interface TrackData {
  tracks: CycloneTrack[]
  received_at: string | null
}

export interface RealtimeSummary {
  status: Record<string, string>
  kp: number | null
  solar_wind: Record<string, any>
  aurora_time: string | null
  server_time: string
}

export const EVENT_TYPES = [
  'usgs_quake', 'opensky', 'nhc_storm', 'nasa_cme',
  'gdacs', 'eonet', 'nasa_firms',
] as const
export type EventType = typeof EVENT_TYPES[number]

async function get<T>(path: string, params: Record<string, string | number> = {}): Promise<T> {
  const q = new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))
  const r = await fetch(`/api/v1${path}?${q}`)
  if (!r.ok) throw new Error(`${path} ${r.status}`)
  return r.json() as Promise<T>
}

export const realtimeApi = {
  events: (type: EventType, limit = 6000) =>
    get<{ type: string; events: RealtimeEvent[]; count: number }>('/realtime/events', { type, limit }),
  aurora: () => get<AuroraData>('/realtime/aurora'),
  solarWind: () => get<SolarWindData>('/realtime/solar-wind'),
  summary: () => get<RealtimeSummary>('/realtime/summary'),
  tracks: () => get<TrackData>('/realtime/tracks'),
}

/** Fetch every real-time dataset with per-feed error isolation. */
export async function fetchAllRealtime(): Promise<{
  events: Partial<Record<EventType, RealtimeEvent[]>>
  aurora: AuroraData | null
  wind: SolarWindData | null
  summary: RealtimeSummary | null
  tracks: TrackData | null
  updatedAt: string
}> {
  const events: Partial<Record<EventType, RealtimeEvent[]>> = {}
  const safe = async <T>(fn: () => Promise<T>): Promise<T | null> => {
    try { return await fn() } catch { return null }
  }
  const [q, f, s, c, d, e, fi, a, w, sum, tr] = await Promise.all([
    safe(() => realtimeApi.events('usgs_quake')),
    safe(() => realtimeApi.events('opensky')),
    safe(() => realtimeApi.events('nhc_storm')),
    safe(() => realtimeApi.events('nasa_cme')),
    safe(() => realtimeApi.events('gdacs')),
    safe(() => realtimeApi.events('eonet')),
    safe(() => realtimeApi.events('nasa_firms')),
    safe(() => realtimeApi.aurora()),
    safe(() => realtimeApi.solarWind()),
    safe(() => realtimeApi.summary()),
    safe(() => realtimeApi.tracks()),
  ])
  if (q) events.usgs_quake = q.events
  if (f) events.opensky = f.events
  if (s) events.nhc_storm = s.events
  if (c) events.nasa_cme = c.events
  if (d) events.gdacs = d.events
  if (e) events.eonet = e.events
  if (fi) events.nasa_firms = fi.events
  return { events, aurora: a, wind: w, summary: sum, tracks: tr,
           updatedAt: new Date().toISOString() }
}
