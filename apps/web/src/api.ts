/** Typed API client. All IDs are opaque strings resolved by the catalog. */
export interface Layer {
  layer_id: string
  label: string
  kind: string
  source_kind: string
  source_id: string
  attribution: string
  license_url: string
  unit: string
  display_unit: string
  palette: string
  layer_type: string
  snapshot_id: string
  dataset_id: string
  coverage: { start: string | null; end: string | null }
  frame_count: number
  state: string
}

export interface Frame {
  frame_id: string
  valid_time: string
  layer_id: string
  bbox?: any
}

export interface Sample {
  frame_id: string
  lon: number
  lat: number
  valid_time: string
  values: Array<{ id: string; unit: string; value: any; display_value: any; display_unit?: string }>
  sampling_method: string
  quality: Record<string, any>
  source_kind: string
  note?: string
}

export interface Station {
  station_id: string
  observed_at: string
  lon: number
  lat: number
  values: Record<string, any>
}

async function get<T = any>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, { signal, headers: { Accept: 'application/json' } })
  if (!res.ok) {
    let detail: any = {}
    try { detail = await res.json() } catch { /* ignore */ }
    throw new Error(detail?.error?.message || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

async function post<T = any>(path: string, body: any): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    let detail: any = {}
    try { detail = await res.json() } catch { /* ignore */ }
    throw new Error(detail?.error?.message || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export interface Buoy {
  station_id: string
  source_id: string
  observed_at: string
  received_at: string
  lon: number
  lat: number
  values: Record<string, number | null>
}

export interface LightningStrike {
  id: string
  lon: number
  lat: number
  observed_at: string
  source_id: string
  magnitude?: number | null
}

export const api = {
  health: () => get<{ status: string; mode: string; version: string }>('/api/v1/health'),
  sources: () => get<any>('/api/v1/sources'),
  dataStatus: () => get<{ mode: string; all_live: boolean; server_time: string;
    datasets: Array<{ dataset_id: string; source_id: string; state: string; fresh: boolean;
      age_minutes: number | null; timestamp: string | null; last_error: string | null;
      source_kind: string }>; note: string }>('/api/v1/data-status'),
  layers: () => get<{ layers: Layer[]; mode: string }>('/api/v1/layers'),
  frames: (layerId: string, signal?: AbortSignal) =>
    get<{ frames: Frame[]; snapshot_id: string; missing_times: string[] }>(
      `/api/v1/layers/${encodeURIComponent(layerId)}/frames`, signal),
  manifest: (frameId: string) => get<any>(`/api/v1/frames/${encodeURIComponent(frameId)}`),
  asset: async (assetId: string, signal?: AbortSignal): Promise<ArrayBuffer> => {
    const res = await fetch(`/api/v1/assets/${encodeURIComponent(assetId)}`, { signal })
    if (!res.ok) throw new Error(`资产 ${assetId} 读取失败: ${res.status}`)
    return res.arrayBuffer()
  },
  image: (assetId: string) => `/api/v1/assets/${encodeURIComponent(assetId)}`,
  sample: (frameId: string, lon: number, lat: number) =>
    get<Sample>(`/api/v1/sample?frame_id=${encodeURIComponent(frameId)}&lon=${lon}&lat=${lat}`),
  stations: (bbox?: string, at?: string, maxAgeMinutes = 120) =>
    get<{ stations: Station[] }>(`/api/v1/stations?${new URLSearchParams({
      ...(bbox ? { bbox } : {}), ...(at ? { at } : {}), max_age_minutes: String(maxAgeMinutes),
      // The observations table also holds real-time events (flights/quakes/CME);
      // the station layer must only show METAR reports.
      source_id: 'awc_metar',
    })}`),
  lightning: () => get<{ strikes: LightningStrike[]; count: number; note: string }>(
    '/api/v1/realtime/lightning'),
  buoys: () => get<{ buoys: Buoy[]; count: number; source_id: string; generated_at: string }>(
    '/api/v1/obs/buoys'),
  refresh: (sourceId: string) => post<{ task_id: string; source: string; state: string; reused?: boolean }>(
    `/api/v1/sources/${encodeURIComponent(sourceId)}/refresh`, {}),
  refreshTask: (taskId: string) => get<any>(`/api/v1/sources/refresh/${encodeURIComponent(taskId)}`),
}
