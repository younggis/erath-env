/** Tectonic boundary classification + globe-safe curve radius. */
export type BoundaryKind = 'ridge' | 'subduction' | 'transform'

export interface BoundaryProps {
  Name?: string
  PlateA?: string
  PlateB?: string
  Type?: string
}

const DIVERGENT = new Set([
  'NA-EU', 'EU-NA', 'NA-AF', 'AF-NA', 'AF-SA', 'SA-AF', 'AN-AF', 'AF-AN',
  'PA-AN', 'AN-PA', 'AU-AN', 'AN-AU', 'IN-AU', 'AU-IN', 'PS-PA', 'PA-PS',
  'CO-NA', 'NA-CO', 'SO-AF', 'AF-SO',
])

/** Classify from the upstream Type field; where absent, infer from plate pair. */
export function classifyBoundary(props: BoundaryProps): BoundaryKind {
  const type = (props.Type || '').toLowerCase()
  if (type.includes('subduction')) return 'subduction'
  if (type.includes('ridge') || type.includes('divergent')) return 'ridge'
  if (type.includes('transform')) return 'transform'
  const a = (props.PlateA || '').toUpperCase()
  const b = (props.PlateB || '').toUpperCase()
  if (DIVERGENT.has(`${a}-${b}`) || DIVERGENT.has(`${b}-${a}`)) return 'ridge'
  return 'transform'
}

/** Radius safely above the globe mesh so lines never z-fight with the surface. */
export function boundaryRadius(globeRadius: number): number {
  return globeRadius * 1.012
}
