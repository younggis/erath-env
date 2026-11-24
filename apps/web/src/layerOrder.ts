/** Sort the forecast layer list by day-to-day usefulness.
 *  The catalog returns layers alphabetically, which buries 10 m wind and 2 m
 *  temperature (the ones users look at most) far down the panel. */
import type { Layer } from './api'

export const LAYER_ORDER: readonly string[] = [
  // Surface weather: the layers most people open first.
  'wind10', 'temp2m', 'mslp', 'precip', 'rh2m', 'dewpoint2m',
  'visibility_sfc', 'cloud_volume',
  // Upper-air / synoptic diagnostics.
  'gh500', 'wind500', 'vvel500', 'cape', 'cin',
  'surface_pressure', 'snow_depth',
  // Higher-resolution regional data.
  'hrrr_wind10',
  // Ocean.
  'sst', 'wave_height', 'wave_period', 'wave_direction', 'wave_drift',
  // Multi-model cloud diagnostics.
  'ifs_lcc', 'ifs_mcc', 'ifs_hcc', 'ifs_sd',
  // Ensemble uncertainty.
  'gefs_temp2m_mean', 'gefs_temp2m_spread',
  'gefs_wind10_mean', 'gefs_wind10_spread', 'gefs_wind_prob',
  // Atmospheric composition (published once upstream quota recovers).
  'cams_pm25', 'cams_aod', 'cams_dust',
]

/** Stable sort: known ids follow LAYER_ORDER, unknown ids keep catalog order
 *  and go after them, so newly added layers never disappear. */
export function sortLayers(layers: Layer[]): Layer[] {
  return layers
    .map((l, i) => ({ l, i, rank: LAYER_ORDER.indexOf(l.layer_id) }))
    .sort((a, b) => {
      const ra = a.rank < 0 ? LAYER_ORDER.length : a.rank
      const rb = b.rank < 0 ? LAYER_ORDER.length : b.rank
      return ra - rb || a.i - b.i
    })
    .map(x => x.l)
}
