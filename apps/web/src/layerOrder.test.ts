import { describe, expect, it } from 'vitest'
import { sortLayers } from './layerOrder'
import type { Layer } from './api'

const layer = (id: string) => ({ layer_id: id }) as Layer
const ids = (ls: Layer[]) => ls.map(l => l.layer_id)

describe('sortLayers', () => {
  it('puts everyday surface weather first', () => {
    const sorted = sortLayers([layer('cape'), layer('wind10'), layer('temp2m'), layer('precip')])
    expect(ids(sorted)).toEqual(['wind10', 'temp2m', 'precip', 'cape'])
  })

  it('keeps unknown layers at the end without losing or duplicating any', () => {
    const input = ['zzz_new', 'wind10', 'aaa_new', 'sst'].map(layer)
    const sorted = sortLayers(input)
    expect(sorted).toHaveLength(input.length)
    expect(ids(sorted)).toEqual(['wind10', 'sst', 'zzz_new', 'aaa_new'])
    expect(new Set(sorted)).toEqual(new Set(input))
  })

  it('matches the current 30-layer catalog exactly', () => {
    const catalog = [
      'cape', 'cin', 'cloud_volume', 'dewpoint2m', 'gefs_temp2m_mean',
      'gefs_temp2m_spread', 'gefs_wind10_mean', 'gefs_wind10_spread',
      'gefs_wind_prob', 'gh500', 'hrrr_wind10', 'ifs_hcc', 'ifs_lcc',
      'ifs_mcc', 'ifs_sd', 'mslp', 'precip', 'rh2m', 'snow_depth', 'sst',
      'surface_pressure', 'temp2m', 'visibility_sfc', 'vvel500',
      'wave_direction', 'wave_drift', 'wave_height', 'wave_period',
      'wind10', 'wind500',
    ]
    const sorted = ids(sortLayers(catalog.map(layer)))
    expect(sorted).toEqual([
      'wind10', 'temp2m', 'mslp', 'precip', 'rh2m', 'dewpoint2m',
      'visibility_sfc', 'cloud_volume',
      'gh500', 'wind500', 'vvel500', 'cape', 'cin',
      'surface_pressure', 'snow_depth', 'hrrr_wind10',
      'sst', 'wave_height', 'wave_period', 'wave_direction', 'wave_drift',
      'ifs_lcc', 'ifs_mcc', 'ifs_hcc', 'ifs_sd',
      'gefs_temp2m_mean', 'gefs_temp2m_spread',
      'gefs_wind10_mean', 'gefs_wind10_spread', 'gefs_wind_prob',
    ])
    // No id is dropped and no id is duplicated.
    expect(new Set(sorted)).toEqual(new Set(catalog))
  })
})
