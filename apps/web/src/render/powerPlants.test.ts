import { describe, expect, it } from 'vitest'
import { FUEL_COLORS, filterValidPlants, fuelMask, pillarHeight, type PowerPlant } from './powerPlants'

const FUELS = ['Coal', 'Gas', 'Hydro', 'Nuclear', 'Solar']

describe('power plant energy pillars', () => {
  it('scales height logarithmically and keeps it bounded', () => {
    expect(pillarHeight(1)).toBeLessThan(pillarHeight(100))
    expect(pillarHeight(100)).toBeLessThan(pillarHeight(5000))
    expect(pillarHeight(1e9)).toBeCloseTo(pillarHeight(5000), 5)
    expect(Number.isFinite(pillarHeight(-5))).toBe(true)
  })

  it('maps fuels to the requested palette', () => {
    expect(FUEL_COLORS.Nuclear).toBe(0xc77dff)
    expect(FUEL_COLORS.Hydro).toBe(0x35d6f0)
    expect(FUEL_COLORS.Solar).toBe(0xffd54a)
    expect(FUEL_COLORS.Coal).toBe(0xff5a3c)
  })

  it('builds a fuel bit mask for single-type filtering', () => {
    expect(fuelMask(FUELS, 'all')).toBe(31)
    expect(fuelMask(FUELS, 'Hydro')).toBe(4)
    expect(fuelMask(FUELS, 'missing')).toBe(0)
  })

  it('drops invalid rows during cleaning', () => {
    const good: PowerPlant = [40, -74, 1200, 3, 'Plant']
    const rows: PowerPlant[] = [
      good,
      [95, -74, 10, 0, 'bad latitude'],
      [40, -74, 0, 0, 'no capacity'],
      [40, -74, 10, 9, 'bad fuel'],
    ]
    expect(filterValidPlants(rows, FUELS.length)).toEqual([good])
  })
})
