// 操作历史展示的纯函数：连续同类事件折叠 + 按关注点筛选。
// 事件文案由后端 text 字段提供（timeline_text.py）；这里只做展示层组织。

export const TIMELINE_FILTERS = [
  { value: 'all', label: '全部' },
  { value: 'llm', label: '模型决策' },
  { value: 'anomaly', label: '异常与恢复' },
  { value: 'milestone', label: '关键节点' },
]

// 高频观察类事件：相邻同类合并为一行，避免长任务刷屏。
const FOLDABLE = new Set([
  'page_observed', 'screen_text_recovered',
  'external_document_scrolled', 'document_scrolled',
])

const LLM_EVENT_TYPES = new Set([
  'llm_action_proposed', 'llm_decision_overridden', 'llm_effectiveness_summary',
])

const ANOMALY_EVENT_TYPES = new Set([
  'action_failed', 'page_content_unavailable', 'page_content_retry',
  'runtime_session_lost', 'runtime_session_waiting_for_recovery', 'runtime_session_recovery_failed',
  'app_crash_detected', 'app_crash_recovering', 'app_left_foreground',
  'coverage_incomplete', 'document_content_unavailable', 'document_blank_returned',
  'document_scroll_aborted', 'document_read_incomplete', 'document_kind_mismatch',
  'external_document_unavailable', 'external_document_loading_wait',
  'manual_login_timeout', 'login_gate_unresolved', 'stale_external_document_body_rejected',
  'monitor_unavailable', 'monitor_failed', 'server_unavailable',
  'wait_loop_broken', 'loop_prevented',
])

const MILESTONE_EVENT_TYPES = new Set([
  'privacy_consent_clicked', 'consent_after_documents', 'consent_blocked_until_documents_read',
  'inline_document_opened', 'document_read_complete', 'external_document_read_complete',
  'document_already_read_skip', 'splash_document_probe_started', 'required_document_prioritized',
  'permission_prompt_without_purpose', 'permission_requested_immediately_after_consent',
  'permission_denial_function_blocked', 'permission_denial_business_action_retried',
  'special_permission_page_observed', 'special_permission_denial_probe_completed',
  'awaiting_manual_login', 'manual_login_state_verified', 'manual_login_confirmed_after_timeout',
  'runtime_session_recovered', 'apk_fresh_installed', 'monitor_started',
  'llm_effectiveness_summary', 'traversal_terminated',
])

export function foldTimelineEvents(events) {
  const groups = []
  let current = null
  for (const event of events || []) {
    const type = String(event.event_type || '')
    if (current && current.event_type === type && current.source === event.source && FOLDABLE.has(type)) {
      current.fold_count += 1
      current.fold_last = event
      continue
    }
    current = FOLDABLE.has(type) ? { ...event, fold_count: 1, fold_last: event } : event
    groups.push(current)
  }
  return groups
}

export function matchesTimelineFilter(group, filter) {
  if (filter === 'all') return true
  const type = String(group.event_type || '')
  if (filter === 'llm') {
    // 只收真正的模型链路：LLM 源事件、提案/改写/汇总事件、以及最终决策
    // 来源明确为 llm 的事件。带 decision_source 的确定性动作（如
    // deterministic_consent 的点击）不属于模型决策，不得按真值混入。
    return group.source === 'llm'
      || LLM_EVENT_TYPES.has(type)
      || group.decision_source === 'llm'
  }
  if (filter === 'anomaly') return ANOMALY_EVENT_TYPES.has(type) || group.decision_source === 'fallback'
  if (filter === 'milestone') return MILESTONE_EVENT_TYPES.has(type)
  return true
}

export function timelineView(events, filter) {
  const groups = foldTimelineEvents(events)
  if (filter === 'all') return groups
  return groups.filter((group) => matchesTimelineFilter(group, filter))
}
