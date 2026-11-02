const RUNNING_STATUSES = new Set(['preparing', 'installing', 'static_analysis', 'traversing', 'analyzing', 'reporting'])
const STOPPED_STATUSES = new Set(['paused', 'failed', 'canceled'])

export function motionProfileForStatus(status) {
  if (status === 'queued') return 'queued'
  if (status === 'completed') return 'completed'
  if (STOPPED_STATUSES.has(status)) return 'stopped'
  return RUNNING_STATUSES.has(status) ? 'running' : 'idle'
}

export function isNavigationCondensed(scrollY) {
  return Number(scrollY) >= 48
}

export function interpolateInteger(start, end, progress) {
  const ratio = Math.min(1, Math.max(0, Number(progress) || 0))
  return Math.round(Number(start) + (Number(end) - Number(start)) * ratio)
}
