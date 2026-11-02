const EXPLICIT_TIME_ZONE = /(Z|[+-]\d{2}:?\d{2})$/i

export function parseApiDateTime(value) {
  if (!value) return null
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value
  if (typeof value === 'number') {
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? null : date
  }
  const text = String(value).trim()
  // The backend stores UTC in timezone-naive database columns. Treat API ISO
  // strings without an explicit offset as UTC before converting in the UI.
  const normalized = /^\d{4}-\d{2}-\d{2}T/.test(text) && !EXPLICIT_TIME_ZONE.test(text) ? `${text}Z` : text
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatLocalDateTime(value) {
  const date = parseApiDateTime(value)
  if (!date) return value ? String(value).replace('T', ' ').slice(0, 19) : '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }).format(date).replaceAll('/', '-')
}

export function formatTaskDuration(task) {
  const started = parseApiDateTime(task?.started_at)
  if (!started) return '尚未开始'
  const progress = task?.progress || {}
  const hasTiming = Object.prototype.hasOwnProperty.call(progress, 'timing_active_seconds')
  let totalSeconds
  if (hasTiming) {
    const frozenSeconds = Number(progress.timing_active_seconds) || 0
    const segmentStarted = parseApiDateTime(progress.timing_segment_started_at)
    const isActive = !task?.finished_at && task?.status !== 'paused' && task?.status !== 'canceled' && task?.status !== 'failed'
    const liveSeconds = isActive && segmentStarted
      ? Math.max(0, (Date.now() - segmentStarted.getTime()) / 1000)
      : 0
    totalSeconds = Math.max(0, Math.round(frozenSeconds + liveSeconds))
  } else {
    // Backward-compatible fallback for tasks created before timing metadata.
    const ended = parseApiDateTime(task?.finished_at) || (task?.status === 'paused' ? started : new Date())
    totalSeconds = Math.max(0, Math.round((ended.getTime() - started.getTime()) / 1000))
  }
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours) return `${hours}小时${String(minutes).padStart(2, '0')}分${String(seconds).padStart(2, '0')}秒`
  if (minutes) return `${minutes}分${String(seconds).padStart(2, '0')}秒`
  return `${seconds}秒`
}
