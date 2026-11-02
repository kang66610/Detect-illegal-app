<template>
  <section class="tasks-view">
    <header class="view-heading">
      <div>
        <p class="eyebrow">检测中心</p>
        <h1>检测任务</h1>
        <p>实时查看排队、设备分析和报告生成状态。页面每 3 秒自动刷新。</p>
      </div>
      <button class="el-button el-button--primary" type="button" @click="openNewDetection">新建检测</button>
    </header>

    <section class="task-summary" aria-label="任务概览">
      <article class="summary-item surface"><span>全部任务</span><strong>{{ tasks.length }}</strong></article>
      <article class="summary-item surface"><span>运行中</span><strong>{{ activeTasks }}</strong></article>
      <article class="summary-item surface"><span>已完成</span><strong>{{ completedTasks }}</strong></article>
      <article class="summary-item surface"><span>已覆盖页面</span><strong>{{ coveredPages }}</strong></article>
    </section>

    <section class="task-toolbar surface" aria-label="任务筛选">
      <el-input v-model="taskSearch" clearable placeholder="搜索应用名称或包名"><template #prefix><span>⌕</span></template></el-input>
      <div class="status-tabs" role="tablist" aria-label="按状态筛选">
        <button v-for="item in taskFilters" :key="item.value" type="button" :class="{ active: taskStatus === item.value }" @click="taskStatus = item.value">{{ item.label }}</button>
      </div>
      <span class="filter-count">{{ filteredTasks.length }} 项</span>
    </section>

    <p v-if="loadError" class="task-refresh-error" role="status">
      {{ loadError }}
      <button type="button" @click="load">重试</button>
    </p>

    <section v-if="filteredTasks.length" class="task-list" aria-label="任务列表">
      <section v-for="group in appGroups" :key="group.key" class="app-group">
        <div class="app-group-toggle">
          <button class="app-group-toggle-main" type="button" :aria-expanded="!isAppCollapsed(group)" @click="toggleAppGroup(group)">
            <span class="app-group-mark" aria-hidden="true">{{ isAppCollapsed(group) ? '+' : '−' }}</span>
            <span class="app-group-copy">
              <strong>{{ group.appName }}</strong>
              <small v-if="group.packageName">{{ group.packageName }}</small>
            </span>
            <span class="app-group-meta">
              <em>{{ group.tasks.length }} 次检测</em>
              <i v-if="group.activeCount">{{ group.activeCount }} 进行中</i>
              <i v-else-if="group.pausedCount" class="app-group-paused">{{ group.pausedCount }} 已暂停</i>
              <i v-else-if="group.completedCount">{{ group.completedCount }} 已完成</i>
            </span>
          </button>
          <button class="app-group-redetect" type="button" :disabled="isRedetectPending(group)" :aria-busy="isRedetectPending(group)" @click.stop="repeatAppDetection(group)">
            {{ isRedetectPending(group) ? '创建中…' : '再次检测' }}
          </button>
        </div>
        <Transition name="expand-panel">
        <div v-if="!isAppCollapsed(group)" class="app-group-body">
      <article v-for="task in visibleTasks(group)" :key="task.id" class="task-card surface" :class="[`task-card-motion-${motionProfile(task.status)}`, { 'task-card-complete': task.status === 'completed', 'task-card-running': isRunning(task.status) }]">
        <header class="task-card-head">
          <div class="task-title" :style="taskIdentityStyle(task)">
            <span class="task-id">任务 #{{ displayNo(task) }}</span>
            <h2>{{ task.app_name || '未命名应用' }}<template v-if="task.industry"> · {{ task.industry }}</template></h2>
          </div>
          <el-tag :type="statusType(task.status)" effect="light">{{ statusText(task.status) }}</el-tag>
        </header>

        <div v-if="phaseBanner(task)" class="phase-banner" :class="`phase-${motionProfile(task.status)}`"><span class="phase-dot" aria-hidden="true"></span>{{ phaseBanner(task) }}</div>

        <div v-if="task.status !== 'completed'" class="progress-line">
          <div class="progress-copy"><span>{{ stageText(task.status) }}</span><b>{{ progressOf(task) }}%</b></div>
          <el-progress :percentage="progressOf(task)" :status="progressStatus(task.status)" :stroke-width="9" :show-text="false" />
        </div>

        <ol v-if="task.status !== 'completed'" class="stage-track" :aria-label="`任务 ${task.id} 的检测阶段`">
          <li v-for="stage in stages" :key="stage.key" :class="stageClass(task.status, stage.key)">
            <i aria-hidden="true"></i><span>{{ stage.label }}</span>
          </li>
        </ol>
        <p v-if="task.status !== 'completed'" class="stage-narrative" aria-live="polite">
          <span class="stage-narrative-label">当前</span>
          <strong>{{ currentStageNarrative(task).title }}</strong>
          <span>{{ currentStageNarrative(task).detail }}</span>
          <small>下一步：{{ currentStageNarrative(task).next }}</small>
        </p>

        <section class="process-section">
          <button class="process-toggle" type="button" @click="toggleProcess(task)">
            <span>检测过程</span><small>{{ expanded[task.id] ? '收起详情' : '展开详情' }}</small><b>{{ expanded[task.id] ? '−' : '+' }}</b>
          </button>
          <div v-if="expanded[task.id]" class="process-panel">
            <ol class="process-stages">
              <li v-for="item in processStages(task)" :key="item.key" :class="item.state">
                <i></i><div><strong>{{ item.label }}</strong><span>{{ item.note }}</span></div>
              </li>
            </ol>
            <div v-if="task.progress?.step" class="process-now">已处理 {{ task.progress.step }} / {{ task.progress.limit || '—' }} 个页面 · 当前：{{ pageText(task.current_page) }}</div>
            <div v-if="timeline[task.id]?.events?.length" class="process-actions">
              <div class="history-head">
                <strong>完整操作历史 · {{ timelineRows(task.id).length }} 组 / 原始 {{ timeline[task.id].events.length }} 条<template v-if="(timeline[task.id].total || 0) > timeline[task.id].events.length">（共 {{ timeline[task.id].total }} 条）</template></strong>
                <div class="status-tabs history-filters" role="tablist" aria-label="操作历史筛选">
                  <button v-for="item in timelineFilterOptions" :key="item.value" type="button" :class="{ active: (timelineFilter[task.id] || 'all') === item.value }" @click="setTimelineFilter(task.id, item.value)">{{ item.label }}</button>
                </div>
              </div>
              <button v-if="historyFollowing[String(task.id)] === false" class="history-follow" type="button" @click="resumeHistoryFollow(task.id)">回到底部并继续跟随</button>
              <button v-if="hasOlderTimeline(task.id)" class="history-older" type="button" :disabled="isLoadingOlder(task.id)" @click="loadOlder(task.id)">
                {{ isLoadingOlder(task.id) ? '加载中…' : `加载更早操作（前 ${timeline[task.id].startIndex} 条）` }}
              </button>
              <div class="process-history" :ref="el => setHistoryPanel(task.id, el)">
                <p v-for="(event, index) in timelineRows(task.id)" :key="`${event.time}-${event.event_type}-${index}`">
                  <em :class="`event-source source-${event.source || 'legacy'}`">{{ sourceText(event) }}</em><span>{{ rowText(event) }}</span><b v-if="event.fold_count > 1" class="fold-count">×{{ event.fold_count }}</b>
                </p>
              </div>
            </div>
            <p v-else class="process-empty">{{ isRunning(task.status) ? (task.progress?.message || '正在等待首个页面操作记录…') : '暂无页面交互记录。' }}</p>
          </div>
        </section>

        <p v-if="task.status === 'failed' && task.failure_reason" class="task-failure">检测中断：{{ failureText(task.failure_reason) }}</p>

        <footer class="task-card-foot">
          <dl class="task-facts">
            <div><dt>创建时间</dt><dd>{{ formatDateTime(task.created_at) }}</dd></div>
            <div v-if="task.started_at"><dt>开始时间</dt><dd>{{ formatDateTime(task.started_at) }}</dd></div>
            <div v-if="task.finished_at"><dt>结束时间</dt><dd>{{ formatDateTime(task.finished_at) }}</dd></div>
            <div v-if="task.started_at"><dt>检测时长</dt><dd class="duration-value">{{ formatTaskDuration(task) }}</dd></div>
            <div><dt>覆盖页面</dt><dd>{{ task.pages_covered || 0 }}</dd></div>
            <div><dt>触发场景</dt><dd>{{ task.scenarios_triggered || 0 }}</dd></div>
            <div v-if="task.status === 'queued'"><dt>当前排队</dt><dd>第 {{ task.queue_position || '—' }} 位</dd></div>
            <div v-else><dt>当前环节</dt><dd>{{ task.current_page ? pageText(task.current_page) : stageText(task.status) }}</dd></div>
          </dl>
          <div class="task-actions">
            <el-button v-if="task.status === 'completed' || task.progress?.termination_report_ready" type="primary" @click="openReport(task)">查看报告</el-button>
            <el-button v-if="task.status === 'failed'" plain @click="openHistoryTail(task)">查看操作记录</el-button>
            <el-button v-if="task.status === 'failed'" :loading="isActionPending(task, 'retry')" :disabled="hasActionPending(task)" @click="retry(task)">重新检测</el-button>
            <el-button v-if="task.status === 'paused'" type="primary" plain :loading="isActionPending(task, 'resume')" :disabled="hasActionPending(task)" @click="resume(task)">继续检测</el-button>
            <el-button v-else-if="isRunning(task.status)" type="warning" plain :loading="isActionPending(task, 'pause')" :disabled="hasActionPending(task)" @click="pause(task)">暂停检测</el-button>
            <el-button v-if="isRunning(task.status) && !task.progress?.termination_requested" type="danger" plain :loading="isActionPending(task, 'terminate')" :disabled="hasActionPending(task)" @click="terminate(task)">终止检测</el-button>
            <el-button v-if="canDelete(task.status)" type="danger" plain :loading="isActionPending(task, 'delete')" :disabled="hasActionPending(task)" @click="removeTask(task)">删除</el-button>
          </div>
        </footer>
      </article>
          <button v-if="taskStatus === 'all' && (historyExpanded[group.key] || visibleTasks(group).length < group.tasks.length)" class="history-toggle" type="button" @click="toggleHistory(group)">
            {{ historyExpanded[group.key] ? '收起历史记录' : `查看其余 ${group.tasks.length - visibleTasks(group).length} 次历史检测` }}
          </button>
        </div>
        </Transition>
      </section>
    </section>

    <section v-else-if="initialLoading" class="empty-state surface" role="status" aria-live="polite">
      <div class="empty-mark loading-mark" aria-hidden="true">…</div><h2>正在加载检测任务</h2>
      <p>正在读取任务状态，请稍候。</p>
    </section>
    <section v-else class="empty-state surface">
      <div class="empty-mark" aria-hidden="true">{{ tasks.length ? '⌕' : '+' }}</div><h2>{{ tasks.length ? '没有匹配的检测任务' : '还没有检测任务' }}</h2>
      <p>{{ tasks.length ? '调整关键词或状态筛选后重试。' : '上传 APK 后，在应用库中创建首个合规检测任务。' }}</p>
      <button class="el-button el-button--primary" type="button" @click="openNewDetection">新建检测</button>
    </section>
  </section>
</template>

<script setup>
defineOptions({ name: 'TaskProgress' })

import { computed, inject, nextTick, onActivated, onDeactivated, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'
import { formatLocalDateTime, formatTaskDuration, parseApiDateTime } from '../utils/dateTime'
import { TIMELINE_FILTERS, timelineView } from '../utils/timeline'
import { motionProfileForStatus } from '../utils/uiMotion'

const tasks = ref([])
const router = useRouter()
const openNewDetection = inject('openNewDetection', () => router.push('/'))
const taskSearch = ref('')
const taskStatus = ref('all')
const expanded = ref({})
const timeline = ref({})
const timelineFilter = ref({})
const olderLoading = ref({})
// 时间线按游标分页加载：首次展开只取尾部一页，向上可加载更早，轮询只追加增量。
const TIMELINE_PAGE = 200
const historyFollowing = ref({})
const historyPanels = new Map()
const historyPanelHandlers = new Map()
let timer = null
let pollingActive = false
let pollingToken = 0
let loadInFlight = null
const timelineLoads = new Map()
const loadError = ref('')
const initialLoading = ref(true)
const pendingActions = ref({})
const redetectPending = ref({})
const collapsedApps = ref({})
const historyExpanded = ref({})
const reportTransitionTaskId = ref(null)
const compactTaskLimit = 2
const taskFilters = [
  { label: '全部', value: 'all' }, { label: '运行中', value: 'active' },
  { label: '已完成', value: 'completed' }, { label: '异常', value: 'exception' },
]
const filteredTasks = computed(() => {
  const keyword = taskSearch.value.trim().toLowerCase()
  return tasks.value.filter((task) => {
    const matchesText = !keyword || [task.app_name, task.package_name, task.industry].filter(Boolean).join(' ').toLowerCase().includes(keyword)
    const matchesStatus = taskStatus.value === 'all'
      || (taskStatus.value === 'active' && (ACTIVE.includes(task.status) || task.status === 'paused'))
      || (taskStatus.value === 'completed' && task.status === 'completed')
      || (taskStatus.value === 'exception' && ['failed', 'canceled'].includes(task.status))
    return matchesText && matchesStatus
  })
})
const appGroups = computed(() => {
  const groups = new Map()
  for (const task of filteredTasks.value) {
    const key = String(task.apk_id || task.package_name || task.app_name || 'unknown')
    if (!groups.has(key)) {
      groups.set(key, {
        key,
        appName: task.app_name || '未命名应用',
        packageName: task.package_name || '',
        tasks: [],
      })
    }
    groups.get(key).tasks.push(task)
  }
  return [...groups.values()].map((group) => ({
    ...group,
    activeCount: group.tasks.filter((task) => ACTIVE.includes(task.status)).length,
    pausedCount: group.tasks.filter((task) => task.status === 'paused').length,
    completedCount: group.tasks.filter((task) => task.status === 'completed').length,
  }))
})
function isAppCollapsed(group) {
  const stored = collapsedApps.value[group.key]
  if (stored !== undefined) return stored
  if (group.activeCount || group.pausedCount) return false
  return appGroups.value[0]?.key !== group.key
}
function toggleAppGroup(group) {
  collapsedApps.value = { ...collapsedApps.value, [group.key]: !isAppCollapsed(group) }
}
function isRedetectPending(group) { return Boolean(redetectPending.value[group.key]) }
async function repeatAppDetection(group) {
  const sourceTask = group.tasks[0]
  if (!sourceTask || isRedetectPending(group)) return
  redetectPending.value = { ...redetectPending.value, [group.key]: true }
  try {
    await ElMessageBox.confirm(
      `将使用“${sourceTask.app_name || group.appName}”最近一次任务的配置（${sourceTask.industry || '通用'} · ${modeText(sourceTask.mode)}）创建新的检测任务。原有任务和报告不会被删除，是否继续？`,
      '确认再次检测',
      { confirmButtonText: '确认检测', cancelButtonText: '暂不检测', type: 'warning' },
    )
    await api.post('/tasks', {
      apk_id: sourceTask.apk_id,
      industry: sourceTask.industry || '通用',
      // The product now runs one standard deep profile. Legacy fast tasks
      // remain visible for historical reporting, but are never cloned.
      mode: 'deep',
    })
    ElMessage.success(`${group.appName} 已创建新的检测任务`)
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error.response?.data?.detail || '再次检测失败')
  } finally {
    const next = { ...redetectPending.value }
    delete next[group.key]
    redetectPending.value = next
  }
}
function syncCollapsedApps(nextTasks) {
  const groups = new Map()
  for (const task of nextTasks) {
    const key = String(task.apk_id || task.package_name || task.app_name || 'unknown')
    const group = groups.get(key) || { active: false }
    group.active = group.active || ACTIVE.includes(task.status) || task.status === 'paused'
    groups.set(key, group)
  }
  const firstKey = groups.keys().next().value
  const next = { ...collapsedApps.value }
  let changed = false
  for (const [key, group] of groups) {
    if (!Object.prototype.hasOwnProperty.call(next, key)) {
      next[key] = !group.active && key !== firstKey
      changed = true
    }
  }
  for (const key of Object.keys(next)) {
    if (!groups.has(key)) {
      delete next[key]
      changed = true
    }
  }
  if (changed) collapsedApps.value = next
}
function visibleTasks(group) {
  if (taskStatus.value !== 'all' || historyExpanded.value[group.key] || group.tasks.length <= compactTaskLimit) return group.tasks
  const active = group.tasks.filter(task => ACTIVE.includes(task.status) || task.status === 'paused')
  if (!active.length) return group.tasks.slice(0, compactTaskLimit)
  const activeIds = new Set(active.map(task => task.id))
  const recentFinished = group.tasks.find(task => !activeIds.has(task.id))
  return recentFinished ? [...active, recentFinished] : active
}
function toggleHistory(group) { historyExpanded.value = { ...historyExpanded.value, [group.key]: !historyExpanded.value[group.key] } }

const stages = [
  { key: 'queued', label: '排队' }, { key: 'installing', label: '安装' },
  { key: 'static_analysis', label: '静态分析' }, { key: 'traversing', label: 'AI 遍历' },
  { key: 'analyzing', label: '证据分析' }, { key: 'reporting', label: '生成报告' },
]
const STATUS_TEXT = { queued: '排队中', preparing: '环境准备', installing: '安装应用', static_analysis: '静态分析', traversing: 'AI 遍历', analyzing: '证据分析', reporting: '生成报告', paused: '已暂停', completed: '已完成', failed: '检测失败', canceled: '已取消' }
const ACTIVE = ['queued', 'preparing', 'installing', 'static_analysis', 'traversing', 'analyzing', 'reporting']
const activeTasks = computed(() => tasks.value.filter(t => ACTIVE.includes(t.status)).length)
const completedTasks = computed(() => tasks.value.filter(t => t.status === 'completed').length)
const coveredPages = computed(() => tasks.value.reduce((total, task) => total + (task.pages_covered || 0), 0))

function statusText(status) { return STATUS_TEXT[status] || status }
function stageText(status) { return status === 'preparing' ? '正在准备检测环境' : statusText(status) }
function pageText(activity) {
  if (!activity) return '等待页面信息'
  if (/NexusLauncherActivity|LauncherActivity|com\.android\.launcher/i.test(activity)) return '系统桌面（应用尚未进入前台）'
  if (/WebView/i.test(activity)) return '应用内网页（WebView）'
  const name = String(activity).split('.').filter(Boolean).pop()
  if (!name || /^(Activity|MainActivity)$/i.test(name)) return '应用主页面'
  const pageNames = {
    Spa: '隐私/服务协议', LocationSet: '定位权限设置', Welcome: '欢迎页',
    PersonalData: '个人信息页面', Login: '登录页面', Home: '应用首页',
  }
  const shortName = name.replace(/Activity$/, '')
  if (pageNames[shortName]) return pageNames[shortName]
  return shortName || '应用页面'
}
function modeText(mode) { return mode === 'fast' ? '旧版检测（已停用）' : mode === 'history' ? '历史检测' : '深度检测' }
function isRunning(status) { return ACTIVE.includes(status) }
function motionProfile(status) { return motionProfileForStatus(status) }
function canDelete(status) { return ['completed', 'failed', 'canceled', 'paused'].includes(status) }
function actionKey(task, action) { return `${task.id}:${action}` }
function hasActionPending(task) { return Object.keys(pendingActions.value).some(key => key.startsWith(`${task.id}:`)) }
function isActionPending(task, action) { return Boolean(pendingActions.value[actionKey(task, action)]) }
async function withAction(task, action, callback) {
  const key = actionKey(task, action)
  if (hasActionPending(task)) return
  pendingActions.value = { ...pendingActions.value, [key]: true }
  try { return await callback() } finally {
    const next = { ...pendingActions.value }
    delete next[key]
    pendingActions.value = next
  }
}
function failureText(reason) { return String(reason).replace(/^ExplorationError:\s*/, '').slice(0, 260) }
function displayNo(task) {
  const chronological = [...tasks.value].sort((a, b) => parseApiDateTime(a.created_at) - parseApiDateTime(b.created_at))
  return chronological.findIndex(item => item.id === task.id) + 1
}
function formatDateTime(value) {
  return formatLocalDateTime(value)
}
function statusType(status) { return status === 'completed' ? 'success' : status === 'failed' ? 'danger' : status === 'canceled' || status === 'paused' ? 'info' : status === 'queued' ? 'warning' : 'primary' }
function progressStatus(status) { return status === 'completed' ? 'success' : status === 'failed' ? 'exception' : undefined }
function progressOf(task) {
  if (task.status === 'completed') return 100
  if (task.status === 'canceled') return Number(task.progress?.percent || 0)
  if (task.status === 'paused') return Number(task.progress?.percent || 0)
  if (task.status === 'failed') return Number(task.progress?.percent || 0)
  return Number(task.progress?.percent ?? { queued: 3, preparing: 8, installing: 17, static_analysis: 34, traversing: 56, analyzing: 76, reporting: 91 }[task.status] ?? 0)
}
function stageClass(status, key) {
  const current = stages.findIndex(stage => stage.key === (status === 'preparing' ? 'queued' : status))
  const index = stages.findIndex(stage => stage.key === key)
  if (status === 'completed') return 'done'
  if (index < current) return 'done'
  if (index === current && isRunning(status)) return 'active'
  return ''
}
function processStages(task) {
  const status = task.status === 'paused' ? task.progress?.paused_from || 'queued' : task.status
  const current = stages.findIndex(stage => stage.key === (status === 'preparing' ? 'queued' : status))
  return stages.map((stage, index) => ({
    key: stage.key,
    label: stage.label,
    state: index < current || status === 'completed' ? 'done' : index === current ? 'active' : '',
    note: index < current || status === 'completed' ? '已完成' : index === current ? (task.current_page ? pageText(task.current_page) : '正在执行') : '等待执行',
  }))
}
function currentStageNarrative(task) {
  if (task.status === 'failed') {
    return { title: '检测中断', detail: failureText(task.failure_reason || task.progress?.message || '等待处理异常。'), next: '查看操作记录或重新检测' }
  }
  if (task.status === 'canceled') {
    return task.progress?.termination_report_ready
      ? { title: '检测已终止', detail: '遍历已提前结束，终止前已形成的违规情况已生成报告。', next: '查看终止前报告' }
      : { title: '检测已取消', detail: '本次任务已停止，不会继续产生新的页面或证据。', next: '重新创建检测任务' }
  }
  const blocked = task.progress?.phase_transition_blocked
  if (blocked) {
    return {
      title: '权限阶段未启动',
      detail: blocked.reason || '第一阶段未形成有效设备会话，已阻止后续权限阶段。',
      next: '恢复设备连接后重新检测',
    }
  }
  const status = task.status === 'paused' ? task.progress?.paused_from || 'queued' : task.status
  const currentIndex = stages.findIndex(stage => stage.key === (status === 'preparing' ? 'queued' : status))
  const current = stages[Math.max(0, currentIndex)] || stages[0]
  const next = stages[currentIndex + 1]
  const detail = task.status === 'paused'
    ? `已暂停于${current.label}，可继续后从检查点恢复。`
    : task.current_page
      ? `正在处理：${pageText(task.current_page)}。`
      : task.progress?.message || '正在建立本阶段所需的检测证据。'
  return {
    title: current.label,
    detail,
    next: next ? next.label : '生成可审计报告',
  }
}
function taskIdentityStyle(task) {
  return reportTransitionTaskId.value === task.id
    ? { 'view-transition-name': 'task-report-identity' }
    : undefined
}
function conciseError(error) {
  const firstLine = String(error || '未知原因').split(/\r?\n|Stacktrace:|For documentation on this error/i)[0]
  return firstLine.replace(/\s*Message:\s*/i, '：').replace(/\s+/g, ' ').trim().slice(0, 180)
}
function actionText(event) {
  const time = event.time ? (parseApiDateTime(event.time)?.toLocaleTimeString() || '刚刚') : '刚刚'
  if (event.source === 'appium') {
    const labels = {
      session_connecting: '正在连接自动化设备', session_connected: '自动化设备连接成功',
      installing_apk: '正在安装 APK', apk_installed: 'APK 安装完成',
      activating_app: '正在启动应用', app_activated: '应用已进入前台',
      page_observed: `读取页面（${event.element_count || 0} 个可操作元素）`,
      page_content_retry: `页面内容尚未就绪，正在第 ${event.attempt || 1} 次重试`,
      page_content_recovered: `页面内容已恢复（${event.retries || 1} 次重试后读取到 ${event.element_count || 0} 个元素）`,
      page_settle_retry: `页面仍在加载，等待可点击控件（第 ${event.attempt || 1} 次）`,
      page_settled: `页面加载完成，已出现 ${event.clickable_count || 0} 个可点击控件`,
      page_loading_wait_instead_of_stop: '页面仍在加载，未按模型的结束指令停止遍历',
      page_content_unavailable: `页面内容不可读取，已停止生成合规结论（重试 ${event.retries || 0} 次）`,
      runtime_session_lost: '自动化会话中断，正在等待模拟器恢复',
      runtime_session_recovered: '模拟器已恢复，已重新连接并继续遍历',
      runtime_session_recovery_failed: '自动化会话恢复失败，已保留原始中断原因',
      document_scrolled: `向下阅读长文第 ${event.scroll_index || 1} 屏`,
      document_read_complete: Number(event.scrolls || 0) > 0 ? `长文阅读完成（共 ${event.scrolls} 次下滑）` : '旧记录：未验证到下滑，不应视为长文阅读完成',
      document_kind_mismatch: `条款入口与实际正文不一致：入口「${event.target || '未知'}」，实际为「${event.actual_target || '未知'}」；已按实际正文记账并停止重开该入口`,
      document_already_read_skip: `已跳过重复条款正文：${event.document || event.target || '已读文档'}`,
      already_read_document_body_skipped: `已读条款无需重读，正在返回继续探索：${event.document || ''}`,
      document_read_incomplete: `长文未形成完整阅读证据（未验证到页面下滑；已下滑 ${event.scrolls || 0} 次）`,
      app_crash_detected: `检测到应用崩溃：${event.reason || '已停止检测'}`,
      app_left_foreground_recovering: event.reason || '应用已到系统桌面，正在重新拉起后继续检测',
      app_foreground_recovered: '已重新进入应用，继续遍历',
      app_exit_confirmation_blocked: `已拦截退出应用确认：${event.target || ''}`,
      app_left_foreground_relaunch_exhausted: '多次回到桌面并已重新拉起，按已覆盖路径结束（不是崩溃失败）',
      app_left_foreground: `应用退出至系统桌面：${event.reason || '已停止检测'}`,
      app_exited_after_privacy_decline: `应用因拒绝隐私提示主动退出：${event.reason || '已停止检测'}`,
      unsafe_privacy_decline_blocked: `已阻止点击“不同意/拒绝”按钮：${event.target || ''}`,
      privacy_service_path_discovered: `发现${event.path_kind === 'delete' ? '注销/删除' : '投诉/举报'}入口：${(event.targets || []).join('、')}`,
      delete_obstacle_detected: '发现注销/删除流程存在可能不合理的条件',
      destructive_confirmation_blocked: '已到达注销/删除确认页；按无损策略未提交请求',
      privacy_consent_clicked: '已点击隐私政策同意按钮',
      consent_checkbox_prechecked: `首次同意页检测到默认勾选：${event.target || '同意复选框'}（已保留截图证据）`,
      awaiting_manual_login: `等待人工在模拟器登录（最长 ${event.wait_seconds || 0} 秒）`,
      manual_login_page_left: '已离开登录表单，但尚未识别到登录身份，继续遍历公开路径',
      manual_login_detected: '旧记录：仅检测到离开登录页，不能作为登录成功结论',
      manual_login_timeout: '等待人工登录超时，以下登录后场景将标记为覆盖不足',
      login_state_assessed: `登录状态复核：${event.logged_in ? (event.verification_source === 'profile_identity' ? '已识别到登录身份，继续遍历' : '模型判断已登录，继续遍历') : '未识别到登录身份，跳过登录后场景'}`,
      manual_login_state_verified: `人工登录已确认（${event.verification_source === 'profile_identity' ? '页面身份标识' : '模型复核'}），继续检测登录后场景`,
      manual_login_confirmed_after_timeout: '登录状态已复核，继续检测登录后场景',
      login_path_skipped: '跳过登录相关场景，继续检测无需登录的路径',
      login_bypass_followed: `登录超时后已走游客/跳过入口：${event.target || ''}`,
      guest_entry_prioritized: `检测到登录/注册与游客入口，进入公开主界面：${event.target || ''}`,
      login_gate_unresolved: '登录超时后仍无法进入公开主界面，已停止在登录门禁',
      login_invitation_followed: '检测到登录前置提示，已进入登录表单并等待人工登录',
      permission_prompt_without_purpose: `发现未同步说明目的的${event.permission_label || '系统'}权限申请`,
      permission_requested_immediately_after_consent: `发现处理隐私提示后立即申请${event.permission || '系统'}权限`,
      permission_denial_function_blocked: `拒绝${event.permission || '权限'}后功能被阻断`,
      special_permission_page_observed: `发现特殊系统权限：${event.permission_type || '未知'}（当前${event.permission_state === 'denied' ? '未授予' : event.permission_state === 'allowed' ? '已授予' : '状态未知'}）；不会自动修改系统设置`,
      special_permission_returned_to_app: `已保持${event.permission_type || '特殊'}权限当前状态并返回应用，继续核验其他路径`,
      special_permission_denial_probe_completed: `特殊权限拒绝后回退核验：${event.outcome === 'app_resumed' ? '应用已恢复，可继续其他场景' : '应用再次提示该权限，已记录可能的业务阻断'}`,
      special_permission_path_blocked: `应用反复要求特殊系统权限：${event.permission_type || '未知'}；已记录拒绝状态与回退结果，避免重复跳转`,
      coverage_incomplete: `自动遍历覆盖不足：${(event.gaps || []).join('；') || '请查看报告说明'}`,
      required_document_prioritized: `先阅读尚未打开的政策/协议：${event.target || ''}`,
      consent_after_documents: '已阅读可见政策/协议，点击同意进入应用',
      consent_without_opened_documents: '同意弹窗条款未能打开可读正文，勾选后进入应用继续检测（不认定条款已阅读）',
      consent_blocked_until_documents_read: `已阻止在未读完协议前点击同意，改为打开：${event.target || ''}`,
      consent_checkbox_required: `同意前先勾选复选框：${event.target || ''}`,
      inline_document_opened: `书名号链接已打开：${event.target || ''} → ${event.next_activity || ''}`,
      inline_document_open_failed: `书名号点击后未打开正文（第 ${event.attempt || 1} 次）：${event.target || ''}，将重试或记为覆盖缺口`,
      same_surface_continued: event.reason || '仍在同一页面继续处理（同意弹窗/未读条款），不是跳过关键步骤',
      duplicate_page_handled: event.reason || '再次观察到已访问过的页面，继续处理未访问目标（不是跳过关键步骤）',
      duplicate_page_observed: event.reason || '再次观察到已访问过的页面，继续处理未访问目标',
      loop_prevented: event.reason === 'duplicate_target'
        ? `当前目标已访问，改为：${{ click: '点击', back: '返回', wait: '等待', stop: '结束' }[event.replacement] || event.replacement || '其他路径'}`
        : '检测到无进展循环，已停止重复操作',
      collection_observability_permissions_granted: `已按本应用声明授予观察用权限以便捕获 SDK 采集：${(event.granted || []).join('、') || event.granted_count || 0}；相机/麦克风等仍保持拒绝，用于核验拒权`,
      runtime_permissions_reset: `已重置非观察类运行时权限（撤销 ${event.revoked_count || 0} 项）`,
      sdk_observation_tab_prioritized: `进入应用后先打开主内容页观察 SDK 采集：${event.target || ''}`,
      sdk_observation_dwelled: `已在主内容页停留 ${event.seconds || 0} 秒，观察 SDK 是否采集设备标识`,
      sdk_observation_return_to_main: '先返回应用主界面观察 SDK 采集，再阅读设置中的协议',
      wait_loop_broken: '同一页面连续等待无进展，已返回继续检测',
      external_document_loading_wait: `外部条款页仍在加载，等待正文（第 ${event.attempt || 1} 次）`,
      external_document_read_complete: `已阅读浏览器中的条款正文：${event.target || ''}`,
      external_document_unavailable: `外部条款页未加载可读正文：${event.target || ''}`,
      external_surface_returned_to_app: '已从浏览器/系统页返回应用继续检测',
      action_completed: `执行${{ click: '点击', back: '返回', wait: '等待' }[event.action] || event.action || '操作'}完成`,
      action_failed: `执行${{ click: '点击', back: '返回', wait: '等待' }[event.action] || event.action || '操作'}失败：${conciseError(event.error)}`,
    }
    return `${time} · ${labels[event.event_type] || event.event_type || '自动化操作'}${event.target ? `：${event.target}` : ''}`
  }
  if (event.source === 'frida') {
    if (event.event_type === 'api_captured') return `${time} · 捕获敏感 API：${event.api || '未知 API'}`
    if (event.event_type === 'url_captured') return `${time} · 捕获网络请求：${event.url || '未知 URL'}`
    const labels = {
      connecting: '正在连接动态监测',
      device_connected: `已连接设备：${event.device_name || event.device_id || 'Android 设备'}`,
      server_health_check: '正在检查 Frida Server',
      server_ready: 'Frida Server 已就绪',
      server_unavailable: `Frida Server 不可用：${event.error || '请启动设备端 frida-server'}`,
      spawning: '正在以受控方式启动应用进程',
      attaching: '正在附加应用进程',
      loading_hook: '正在加载敏感 API 监测规则',
      resuming: '监测规则已加载，正在恢复应用运行',
      monitor_started: '动态监测已启动',
      monitor_failed: `动态监测启动失败：${event.error || '未知原因'}`,
      monitor_stopping: '正在停止动态监测',
      monitor_stopped: `动态监测已停止（捕获 ${event.event_count || 0} 条事件）`,
    }
    return `${time} · ${labels[event.event_type] || event.event_type || '动态监测事件'}`
  }
  if (event.source === 'flowdroid') {
    if (event.event_type === 'static_analysis_started') return `${time} · 正在进行静态污点分析（大型 APK 可能需要数分钟）`
    if (event.event_type === 'static_analysis_finished') {
      const status = { completed: '已完成', inconclusive: '证据不足', interrupted: '已暂停 / 取消', failed: '执行失败', not_available: '未启用 / 不可用' }[event.status] || event.status
      return `${time} · 静态污点分析${status}，候选流 ${event.flow_count || 0} 条，耗时 ${event.elapsed_seconds || 0} 秒`
    }
    return `${time} · ${event.event_type || '静态污点分析事件'}`
  }
  const action = { click: '点击', back: '返回', wait: '等待', stop: '结束' }[event.action] || event.action || '页面记录'
  const source = event.decision_source === 'llm' ? '大模型' : event.decision_source === 'fallback' ? '本地兜底' : '页面'
  return `${time} · ${source}决策：${action}${event.target ? `：${event.target}` : ''}${event.reason ? `（${event.reason}）` : ''}`
}
const timelineFilterOptions = TIMELINE_FILTERS
function timelineState(taskId) {
  return timeline.value[String(taskId)] || { events: [], startIndex: 0, total: 0 }
}
function timelineRows(taskId) {
  const state = timelineState(taskId)
  return timelineView(state.events, timelineFilter.value[String(taskId)] || 'all')
}
function setTimelineFilter(taskId, value) {
  timelineFilter.value = { ...timelineFilter.value, [String(taskId)]: value }
}
function hasOlderTimeline(taskId) {
  const state = timeline.value[String(taskId)]
  return Boolean(state && state.startIndex > 0 && !state.exhausted)
}
function isLoadingOlder(taskId) { return Boolean(olderLoading.value[String(taskId)]) }
async function loadOlder(taskId) {
  const key = String(taskId)
  if (isLoadingOlder(taskId)) return
  olderLoading.value = { ...olderLoading.value, [key]: true }
  try { await loadTimeline(taskId, 'older') } finally {
    const next = { ...olderLoading.value }
    delete next[key]
    olderLoading.value = next
  }
}
function formatTimeShort(value) {
  const date = parseApiDateTime(value)
  if (!date) return ''
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
function rowText(group) {
  // 后端 text 不含时间：展示层统一补时间前缀；折叠组附结束时间与条数。
  if (!group.text) return actionText(group)
  const start = formatTimeShort(group.time)
  const base = start ? `${start} · ${group.text}` : group.text
  if ((group.fold_count || 1) <= 1) return base
  const end = formatTimeShort(group.fold_last?.time)
  return `${base}（至 ${end || '—'}）`
}
// 运行中/暂停任务把后端阶段文案（如“第 1/2 阶段：拒绝权限阶段”）顶到卡片显著位置。
function phaseBanner(task) {
  if (['completed', 'failed', 'canceled'].includes(task.status)) return ''
  return String(task.progress?.message || '').trim()
}
async function openHistoryTail(task) {
  expanded.value = { ...expanded.value, [task.id]: true }
  setTimelineFilter(task.id, 'all')
  await loadTimeline(task.id)
  await nextTick()
  resumeHistoryFollow(String(task.id))
}
function sourceText(event) {
  if (event.source === 'appium') return 'Appium'
  if (event.source === 'frida') return 'Frida'
  if (event.source === 'flowdroid') return 'FlowDroid'
  if (event.source === 'llm') return event.decision_source === 'fallback' ? '兜底' : 'LLM'
  return event.decision_source === 'fallback' ? '兜底' : 'LLM'
}
function setHistoryPanel(taskId, panel) {
  const key = String(taskId)
  const current = historyPanels.get(key)
  if (current === panel) return
  const oldHandler = historyPanelHandlers.get(key)
  if (current && oldHandler) current.removeEventListener('scroll', oldHandler)
  if (panel) {
    const wasFollowing = historyFollowing.value[key]
    historyPanels.set(key, panel)
    // Function refs can be re-bound when the polled timeline is patched. Do
    // not treat that DOM re-bind as a new panel: otherwise a user reading an
    // older entry is unexpectedly pulled back to the newest entry every poll.
    if (wasFollowing === undefined) {
      historyFollowing.value = { ...historyFollowing.value, [key]: true }
    }
    const handler = () => {
      const distance = panel.scrollHeight - panel.scrollTop - panel.clientHeight
      historyFollowing.value = { ...historyFollowing.value, [key]: distance <= 28 }
    }
    historyPanelHandlers.set(key, handler)
    panel.addEventListener('scroll', handler, { passive: true })
    if (timeline.value[key]?.events?.length && wasFollowing !== false) requestAnimationFrame(() => scrollHistoryToBottom(key))
  } else {
    historyPanels.delete(key)
    historyPanelHandlers.delete(key)
  }
}
function scrollHistoryToBottom(taskId) {
  const panel = historyPanels.get(String(taskId))
  if (!panel) return
  panel.scrollTop = panel.scrollHeight
}
function resumeHistoryFollow(taskId) {
  const key = String(taskId)
  historyFollowing.value = { ...historyFollowing.value, [key]: true }
  scrollHistoryToBottom(key)
}
function normalizeTimelineEnvelope(data) {
  // 兼容两条响应形态：无游标的旧端点返回纯数组；带游标返回 {total,start,events}。
  if (Array.isArray(data)) return { total: data.length, start: 0, events: data }
  return {
    total: Number(data?.total || 0),
    start: Number(data?.start || 0),
    events: Array.isArray(data?.events) ? data.events : [],
  }
}
function loadTimeline(taskId, mode = 'auto') {
  const key = String(taskId)
  if (timelineLoads.has(key)) return timelineLoads.get(key)
  const state = timeline.value[key]
  // 显式白名单三种模式；未知值一律回落，绝不能带着坏 mode 去覆盖已有历史。
  let effectiveMode = mode === 'initial' || mode === 'older' || mode === 'poll'
    ? mode
    : (state ? 'poll' : 'initial')
  // older/poll 都依赖已加载的游标状态；状态缺失时只能按首次加载兜底，
  // 否则下面的参数计算会在 try 之外解引用 undefined。
  if (effectiveMode !== 'initial' && !state) effectiveMode = 'initial'
  const params = effectiveMode === 'initial'
    ? { limit: TIMELINE_PAGE }
    : effectiveMode === 'older'
      ? { before: state.startIndex, limit: TIMELINE_PAGE }
      : { after: state.startIndex + state.events.length }
  const request = (async () => {
    try {
      const next = normalizeTimelineEnvelope((await api.get(`/tasks/${taskId}/timeline`, { params })).data)
      if (effectiveMode === 'older') {
        if (!next.events.length) {
          timeline.value = { ...timeline.value, [key]: { ...state, exhausted: true } }
          return
        }
        const panel = historyPanels.get(key)
        const previousHeight = panel?.scrollHeight || 0
        timeline.value = {
          ...timeline.value,
          [key]: { events: [...next.events, ...state.events], startIndex: next.start, total: next.total },
        }
        await nextTick()
        // 前插不改变用户阅读位置：按高度差补偿滚动。
        if (panel) panel.scrollTop += panel.scrollHeight - previousHeight
        return
      }
      if (effectiveMode === 'poll' && state) {
        const known = state.startIndex + state.events.length
        if (next.total < known) {
          // 同一任务号重跑会重建 timeline 目录：旧游标失效，重置后按首次加载重建尾部窗口。
          timeline.value = { ...timeline.value, [key]: { events: [], startIndex: 0, total: 0 } }
          setTimeout(() => { void loadTimeline(taskId, 'initial') }, 0)
          return
        }
        const fresh = next.events.filter((_, offset) => next.start + offset >= known)
        timeline.value = {
          ...timeline.value,
          [key]: {
            events: [...state.events, ...fresh],
            startIndex: state.startIndex,
            total: Math.max(next.total, state.events.length),
          },
        }
        // Re-check at response time: the user may have scrolled upward while
        // the timeline request was in flight.
        if (fresh.length && historyFollowing.value[key] !== false) {
          await nextTick()
          // Numeric task ids from the template and string keys returned by
          // Object.keys must address the same panel. Scroll after both Vue's DOM
          // flush and the browser's layout frame so every new row is visible.
          scrollHistoryToBottom(key)
          requestAnimationFrame(() => scrollHistoryToBottom(key))
        }
        return
      }
      timeline.value = {
        ...timeline.value,
        [key]: { events: next.events, startIndex: next.start, total: next.total },
      }
      if (next.events.length && historyFollowing.value[key] !== false) {
        await nextTick()
        scrollHistoryToBottom(key)
      }
    } catch {
      // Keep the last good history visible during a transient poll/API error.
      // Clearing it makes the UI look as if the audit trail was lost.
    }
  })().finally(() => timelineLoads.delete(key))
  timelineLoads.set(key, request)
  return request
}
async function toggleProcess(task) { expanded.value = { ...expanded.value, [task.id]: !expanded.value[task.id] }; if (expanded.value[task.id]) await loadTimeline(task.id) }
function load() {
  if (loadInFlight) return loadInFlight
  loadInFlight = (async () => {
    try {
      const data = (await api.get('/tasks')).data
      tasks.value = Array.isArray(data) ? data : []
      syncCollapsedApps(tasks.value)
      loadError.value = ''
      // 不能直接 map(loadTimeline)：map 会把数组下标当第二个参数传成 mode。
      await Promise.all(Object.keys(expanded.value).filter(id => expanded.value[id]).map((id) => loadTimeline(id)))
    } catch (error) {
      loadError.value = `任务列表暂时无法刷新：${error.response?.data?.detail || '请检查服务是否运行'}`
    } finally {
      initialLoading.value = false
    }
  })().finally(() => { loadInFlight = null })
  return loadInFlight
}
function openReport(task) {
  const navigate = () => router.push(`/report/${task.id}`)
  reportTransitionTaskId.value = task.id
  const reduceMotion = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (typeof document !== 'undefined' && document.startViewTransition && !reduceMotion) {
    document.startViewTransition(navigate)
    return
  }
  navigate()
}
async function retry(task) {
  await withAction(task, 'retry', async () => {
    try { await api.post(`/tasks/${task.id}/retry`); ElMessage.success('任务已重新进入队列'); await load() }
    catch (error) { ElMessage.error(error.response?.data?.detail || '重新检测失败') }
  })
}
async function pause(task) { await withAction(task, 'pause', async () => { try { await api.post(`/tasks/${task.id}/pause`); ElMessage.success('任务已暂停'); await load() } catch (error) { ElMessage.error(error.response?.data?.detail || '暂停任务失败') } }) }
async function resume(task) { await withAction(task, 'resume', async () => { try { await api.post(`/tasks/${task.id}/resume`); ElMessage.success('任务已重新进入队列，将从头执行'); await load() } catch (error) { ElMessage.error(error.response?.data?.detail || '继续任务失败') } }) }
async function terminate(task) {
  await withAction(task, 'terminate', async () => {
    try {
      await ElMessageBox.confirm(
        task.status === 'queued'
          ? '该任务尚未开始，将取消排队并释放排队占位。是否继续？'
          : '终止后将停止当前遍历，并生成终止前已形成的违规情况报告，同时释放 Worker 占用的设备。是否继续？',
        `终止检测 #${displayNo(task)}`,
        { confirmButtonText: '确认终止', cancelButtonText: '继续检测', type: 'warning' },
      )
      const response = await api.post(`/tasks/${task.id}/terminate`)
      const serverTask = response.data || {}
      // Update this card immediately. The worker may still be closing a live
      // Appium/Frida session, so waiting for a full list refresh here makes a
      // successful termination look frozen. Normal polling reconciles the
      // final canceled state in the background.
      tasks.value = tasks.value.map((item) => item.id === task.id ? {
        ...item,
        status: serverTask.status || item.status,
        progress: serverTask.progress || {
          ...(item.progress || {}),
          termination_requested: true,
          message: '终止请求已发送，正在停止遍历并释放设备',
        },
        failure_reason: serverTask.failure_reason ?? item.failure_reason,
        finished_at: serverTask.finished_at ?? item.finished_at,
      } : item)
      ElMessage.success('终止请求已发送，正在释放设备')
      void load()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(error.response?.data?.detail || '终止检测失败')
    }
  })
}
async function removeTask(task) {
  await withAction(task, 'delete', async () => {
    try {
      await ElMessageBox.confirm('删除后将清理该任务的检测记录、报告和截图证据，且不可恢复。', `删除任务 #${displayNo(task)}`, { confirmButtonText: '确认删除', cancelButtonText: '保留任务', type: 'warning' })
      await api.delete(`/tasks/${task.id}`)
      ElMessage.success('任务及其检测证据已删除')
      await load()
    } catch (error) {
      if (error !== 'cancel' && error !== 'close') ElMessage.error(error.response?.data?.detail || '删除任务失败')
    }
  })
}
async function startPolling() {
  if (pollingActive) return
  pollingActive = true
  const token = ++pollingToken
  await load()
  if (!pollingActive || token !== pollingToken) return
  timer = setInterval(() => { void load() }, 3000)
}
function stopPolling() {
  pollingActive = false
  pollingToken += 1
  if (timer) clearInterval(timer)
  timer = null
}

function clearHistoryPanels() {
  for (const [key, panel] of historyPanels) {
    const handler = historyPanelHandlers.get(key)
    if (handler) panel.removeEventListener('scroll', handler)
  }
  historyPanels.clear()
  historyPanelHandlers.clear()
  timelineLoads.clear()
}

onActivated(startPolling)
onDeactivated(stopPolling)
onUnmounted(() => { stopPolling(); clearHistoryPanels() })
</script>

<style scoped>
.task-summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: .85rem; margin-bottom: 1.4rem; }.summary-item { display: grid; gap: .35rem; padding: 1.05rem 1.15rem; }.summary-item span { color: #7b8495; font-size: .78rem; font-weight: 700; }.summary-item strong { color: #172033; font-size: 1.55rem; font-variant-numeric: tabular-nums; letter-spacing: -.05em; }
.app-group { display: grid; gap: .7rem; }.app-group-toggle { display: flex; align-items: center; gap: .75rem; width: 100%; min-width: 0; padding: .55rem .7rem .55rem .9rem; color: inherit; font: inherit; text-align: left; background: #f7f9fc; border: 1px solid #e7ecf4; border-radius: .8rem; }.app-group-toggle:hover { background: #f1f6ff; border-color: #d5e4fb; }.app-group-toggle-main { display: flex; align-items: center; flex: 1 1 auto; min-width: 0; gap: .75rem; padding: .17rem .2rem; color: inherit; font: inherit; text-align: left; background: transparent; border: 0; border-radius: .45rem; cursor: pointer; }.app-group-toggle-main:focus-visible { outline: 2px solid #175cd3; outline-offset: 2px; }.app-group-mark { display: grid; flex: 0 0 auto; width: 1.35rem; height: 1.35rem; place-items: center; color: #175cd3; font-size: .95rem; font-weight: 800; background: #e8f1ff; border-radius: .4rem; }.app-group-copy { display: grid; min-width: 0; gap: .12rem; }.app-group-copy strong { color: #1e2a40; font-size: .95rem; letter-spacing: -.02em; }.app-group-copy small { color: #7b879a; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .7rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.app-group-meta { display: flex; flex-wrap: wrap; gap: .35rem; margin-left: auto; }.app-group-meta em, .app-group-meta i { padding: .12rem .45rem; font-style: normal; font-size: .68rem; font-weight: 700; border-radius: .35rem; }.app-group-meta em { color: #526078; background: #eef2f7; }.app-group-meta i { color: #175cd3; background: #e8f1ff; }.app-group-redetect { flex: 0 0 auto; padding: .4rem .65rem; color: #175cd3; font: inherit; font-size: .7rem; font-weight: 800; white-space: nowrap; background: #e8f1ff; border: 1px solid #cfe1ff; border-radius: .5rem; cursor: pointer; }.app-group-redetect:hover:not(:disabled) { color: #fff; background: #175cd3; border-color: #175cd3; }.app-group-redetect:disabled { color: #91a6bf; background: #eef2f7; border-color: #dbe3ed; cursor: wait; }.app-group-body { display: grid; gap: .9rem; }
.tasks-view, .task-list, .task-card { min-width: 0; max-width: 100%; }.task-list { display: grid; gap: .9rem; }.task-card { padding: 1.2rem 1.25rem 1.15rem; transition: transform var(--motion-panel) var(--motion-ease), box-shadow var(--motion-route) var(--motion-ease), border-color var(--motion-panel) var(--motion-ease); }.task-card:hover { transform: translateY(-2px); box-shadow: 0 18px 40px rgba(29, 47, 83, .09); }.task-card-running { border-color: rgba(100, 166, 226, .46); }.task-card-head, .task-card-foot { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }.task-title { display: flex; align-items: baseline; gap: .7rem; min-width: 0; }.task-id { color: #768197; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .76rem; }.task-title h2 { margin: 0; color: #263047; font-size: 1rem; letter-spacing: -.02em; }.progress-line { margin: 1.25rem 0 1rem; }.progress-copy { display: flex; justify-content: space-between; margin-bottom: .45rem; color: #68748a; font-size: .78rem; }.progress-copy b { color: #175cd3; font-variant-numeric: tabular-nums; }.stage-track { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: .25rem; padding: 0; margin: 0 0 .72rem; list-style: none; }.stage-track li { position: relative; display: grid; min-width: 0; justify-items: center; gap: .42rem; color: #9aa4b5; font-size: .68rem; text-align: center; transition: color var(--motion-panel) var(--motion-ease), transform var(--motion-panel) var(--motion-ease); }.stage-track li:not(:last-child)::after { position: absolute; top: .31rem; left: calc(50% + .55rem); width: calc(100% - 1.1rem); height: 1px; background: #dce2ec; content: ''; transition: background var(--motion-panel) var(--motion-ease); }.stage-track i { position: relative; z-index: 1; width: .68rem; height: .68rem; background: #f6f8fb; border: 2px solid #c7cfdd; border-radius: 50%; transition: background var(--motion-panel) var(--motion-ease), border-color var(--motion-panel) var(--motion-ease), box-shadow var(--motion-panel) var(--motion-ease); }.stage-track .done { color: #347450; }.stage-track .done i { background: #37a466; border-color: #37a466; }.stage-track .done:not(:last-child)::after { background: #86cda2; }.stage-track .active { color: #175cd3; font-weight: 800; transform: translateY(-1px); }.stage-track .active i { background: #fff; border-color: #175cd3; box-shadow: 0 0 0 4px #e9f1ff; animation: stage-breathe 2.4s ease-in-out infinite; }.stage-narrative { display: grid; grid-template-columns: auto auto minmax(0, 1fr) auto; align-items: center; gap: .45rem; margin: 0 0 1.1rem; padding: .65rem .72rem; color: #5d718b; font-size: .72rem; background: linear-gradient(100deg, #f1f7ff, #f8fbff); border: 1px solid #dbe9fb; border-radius: .65rem; }.stage-narrative-label { padding: .16rem .36rem; color: #175cd3; font-size: .64rem; font-weight: 800; background: #dcecff; border-radius: .32rem; }.stage-narrative strong { color: #225eaa; font-size: .75rem; }.stage-narrative span:not(.stage-narrative-label) { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.stage-narrative small { color: #8392a5; font-size: .68rem; }.task-card-foot { padding-top: .15rem; }.task-facts { display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 0; }.task-facts div { display: grid; gap: .22rem; }.task-facts dt { color: #8a95a8; font-size: .7rem; }.task-facts dd { margin: 0; color: #414c60; font-size: .81rem; font-weight: 700; }.task-facts .duration-value { color: #1767a5; font-variant-numeric: tabular-nums; }.task-actions { flex: 0 0 auto; }.empty-state { display: grid; justify-items: center; padding: 4rem 1.5rem; text-align: center; }.empty-state h2 { margin: .8rem 0 .3rem; font-size: 1.1rem; }.empty-state p { margin: 0 0 1.25rem; color: #7b8495; font-size: .87rem; }.empty-mark { display: grid; width: 2.7rem; height: 2.7rem; place-items: center; color: #175cd3; font-size: 1.6rem; background: #e8f1ff; border-radius: .85rem; } @keyframes stage-breathe { 0%, 100% { box-shadow: 0 0 0 4px #e9f1ff; } 50% { box-shadow: 0 0 0 7px rgba(218, 235, 255, .45); } }
.task-failure { margin: -.25rem 0 1rem; padding: .65rem .75rem; color: #a1393e; font-size: .78rem; line-height: 1.5; background: #fff2f2; border: 1px solid #ffd4d4; border-radius: .55rem; overflow-wrap: anywhere; }
@media (max-width: 760px) { .task-summary { grid-template-columns: repeat(2, 1fr); }.task-card-head, .task-card-foot { align-items: flex-start; flex-direction: column; }.task-actions { width: 100%; }.task-actions :deep(.el-button) { width: 100%; }.stage-track { overflow-x: auto; grid-template-columns: repeat(6, minmax(4.2rem, 1fr)); padding-bottom: .25rem; }.stage-narrative { grid-template-columns: auto 1fr; }.stage-narrative span:not(.stage-narrative-label) { grid-column: 1 / -1; white-space: normal; }.stage-narrative small { grid-column: 2; }.task-facts { gap: 1rem; } }
</style>

<style scoped>
.task-toolbar { display: grid; grid-template-columns: minmax(15rem, 1fr) auto auto; gap: .8rem; align-items: center; margin: 0 0 1rem; padding: .7rem .8rem; }
.task-toolbar :deep(.el-input) { max-width: 24rem; }
.task-refresh-error { display: flex; align-items: center; gap: .65rem; margin: -.35rem 0 1rem; padding: .62rem .8rem; color: #9a5b1a; font-size: .74rem; line-height: 1.45; background: #fff8e8; border: 1px solid #f0dfb9; border-radius: .7rem; }
.task-refresh-error button { margin-left: auto; padding: .28rem .55rem; color: #246fb8; font: inherit; font-size: .7rem; font-weight: 750; background: #fff; border: 1px solid #cfe0ee; border-radius: .42rem; cursor: pointer; }
.task-refresh-error button:hover { background: #f2f8fc; border-color: #a8c8df; }
.loading-mark { color: #246fb8; animation: loading-pulse 1.2s ease-in-out infinite; }
@keyframes loading-pulse { 0%, 100% { opacity: .35; transform: scale(.92); } 50% { opacity: 1; transform: scale(1.05); } }
.status-tabs { display: flex; gap: .18rem; padding: .2rem; background: #edf2f4; border-radius: .48rem; }
.status-tabs button { padding: .42rem .68rem; color: #6c7e8c; font: inherit; font-size: .7rem; font-weight: 700; background: transparent; border: 0; border-radius: .34rem; cursor: pointer; transition: color .18s ease, background .18s ease, box-shadow .18s ease; }
.status-tabs button:hover { color: #173047; }
.status-tabs button.active { color: #173047; background: #fff; box-shadow: 0 2px 8px rgba(25,55,76,.09); }
.filter-count { color: #7b8995; font-size: .7rem; font-variant-numeric: tabular-nums; white-space: nowrap; }
.history-toggle { justify-self: center; padding: .42rem .75rem; color: #52718a; font: inherit; font-size: .7rem; font-weight: 700; background: transparent; border: 1px solid #d6e0e7; border-radius: .42rem; cursor: pointer; }
.history-toggle:hover { color: #246fb8; border-color: #9ebdd4; background: #f3f8fb; }
.task-card-complete { padding-block: 1rem; }
.task-card-complete .process-section { margin-top: .85rem; margin-bottom: .8rem; }
@media (max-width: 760px) {
  .task-toolbar { grid-template-columns: 1fr; }
  .task-toolbar :deep(.el-input) { max-width: none; }
  .status-tabs { overflow-x: auto; }
  .filter-count { display: none; }
  .app-group-toggle { align-items: flex-start; }
  .app-group-toggle-main { align-items: flex-start; }
  .app-group-meta { margin-left: auto; }
  .app-group-redetect { margin-top: .15rem; }
}
</style>

<style scoped>
.process-history p { display: flex; align-items: flex-start; gap: .35rem; }
.process-history p > span { min-width: 0; overflow-wrap: anywhere; }
.process-history .event-source { flex: 0 0 4.2rem; margin-right: 0; }
</style>

<style scoped>
/* State feedback is intentionally local to the task that changed. */
.task-card-motion-queued .phase-dot { animation-duration: 3.6s; }
.task-card-motion-running :deep(.el-progress-bar__inner) { position: relative; overflow: hidden; }
.task-card-motion-running :deep(.el-progress-bar__inner)::after { position: absolute; inset: 0; width: 36%; background: linear-gradient(90deg, transparent, rgba(255,255,255,.62), transparent); content: ''; transform: translateX(-150%); animation: progress-sheen 2.8s var(--motion-ease) infinite; }
.task-card-motion-completed { animation: task-complete-settle 520ms var(--motion-emphasis) both; }
.task-card-motion-completed .task-facts dd { animation: number-settle 460ms var(--motion-emphasis) both; }
.task-card-motion-completed .task-facts div:nth-child(2) dd { animation-delay: 45ms; }.task-card-motion-completed .task-facts div:nth-child(3) dd { animation-delay: 90ms; }.task-card-motion-completed .task-facts div:nth-child(n+4) dd { animation-delay: 135ms; }
.task-card-motion-stopped .phase-dot, .task-card-motion-stopped .stage-track .active i { animation: none; }
.task-card-motion-stopped .task-actions :deep(.el-button--primary), .task-card-motion-stopped .task-actions :deep(.el-button--warning) { box-shadow: 0 0 0 3px rgba(232,183,99,.16); }
.process-panel { background: transparent; }.process-history { padding-inline: 0; background: transparent; border: 0; border-radius: 0; }.process-actions p { padding-block: .18rem; }
@keyframes progress-sheen { to { transform: translateX(420%); } }
@keyframes task-complete-settle { from { box-shadow: 0 0 0 rgba(74,151,105,0); transform: translateY(4px); } to { box-shadow: 0 16px 34px rgba(52,124,97,.12); transform: translateY(0); } }
@keyframes number-settle { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
</style>

<style scoped>
.process-section { min-width: 0; max-width: 100%; margin: 0 0 1.1rem; border: 1px solid #e7ecf4; border-radius: .72rem; overflow: hidden; }
.process-toggle { display: flex; align-items: center; width: 100%; gap: .55rem; padding: .72rem .86rem; color: #38465d; font: inherit; font-size: .78rem; font-weight: 800; text-align: left; background: #fafcff; border: 0; cursor: pointer; }
.process-toggle small { color: #8490a2; font-weight: 600; }.process-toggle b { margin-left: auto; color: #175cd3; font-size: 1.1rem; }
.process-panel { min-width: 0; padding: .8rem .9rem .9rem; border-top: 1px solid #e7ecf4; background: #fff; }.process-stages { display: grid; gap: .65rem; padding: 0; margin: 0; list-style: none; }.process-stages li { display: flex; align-items: flex-start; gap: .65rem; color: #919cad; }.process-stages li i { flex: 0 0 auto; width: .55rem; height: .55rem; margin-top: .28rem; background: #dce3ed; border-radius: 50%; }.process-stages li div { display: grid; min-width: 0; gap: .1rem; }.process-stages strong { color: #526078; font-size: .76rem; }.process-stages span { font-size: .71rem; }.process-stages .done { color: #4b8d66; }.process-stages .done i { background: #44a76d; }.process-stages .done strong { color: #36794f; }.process-stages .active { color: #1768d5; }.process-stages .active i { background: #fff; border: 2px solid #1768d5; box-shadow: 0 0 0 3px #e7f0ff; }.process-stages .active strong { color: #175cd3; }.process-now { min-width: 0; margin: .75rem 0 0; padding: .6rem .7rem; overflow-wrap: anywhere; color: #205ea8; font-size: .72rem; background: #f1f7ff; border-radius: .45rem; }.process-actions { position: relative; min-width: 0; margin-top: .75rem; }.process-actions strong { color: #647188; font-size: .72rem; }.history-follow { float: right; padding: .18rem .5rem; color: #175cd3; font: inherit; font-size: .68rem; font-weight: 700; background: #f1f7ff; border: 1px solid #cfe1ff; border-radius: .35rem; cursor: pointer; }.process-history { clear: both; max-width: 100%; max-height: 18rem; margin-top: .35rem; padding: .25rem .55rem .45rem; overflow-y: auto; overflow-x: hidden; background: #fafcff; border: 0; border-radius: .45rem; }.process-actions p, .process-empty { max-width: 100%; margin: .35rem 0 0; overflow-wrap: anywhere; word-break: break-word; color: #66758c; font-size: .71rem; line-height: 1.55; }.event-source { display: inline-block; min-width: 3.3rem; margin-right: .35rem; padding: .04rem .3rem; color: #53657e; font-style: normal; font-weight: 800; text-align: center; background: #e9eef5; border-radius: .25rem; }.source-appium { color: #185db8; background: #e8f1ff; }.source-llm { color: #7544a8; background: #f1eaff; }.source-frida { color: #12705b; background: #e4f7ef; }.source-flowdroid { color: #9a5f16; background: #fff0d6; }.source-legacy { color: #8b6514; background: #fff3d9; }.phase-banner { display: flex; align-items: center; gap: .45rem; margin-top: .55rem; padding: .45rem .65rem; color: #175cd3; font-size: .74rem; font-weight: 700; background: #f1f7ff; border: 1px solid #cfe1ff; border-radius: .45rem; overflow-wrap: anywhere; }.phase-dot { flex: 0 0 auto; width: .5rem; height: .5rem; background: #1768d5; border-radius: 50%; animation: phase-pulse 1.6s ease-in-out infinite; }@keyframes phase-pulse { 0%, 100% { opacity: .35; } 50% { opacity: 1; } }.history-head { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .7rem; }.history-filters { display: inline-flex; gap: .25rem; margin-left: auto; }.history-filters button { padding: .14rem .5rem; color: #647188; font: inherit; font-size: .68rem; background: #eef2f8; border: 1px solid transparent; border-radius: .35rem; cursor: pointer; }.history-filters button.active { color: #175cd3; font-weight: 700; background: #f1f7ff; border-color: #cfe1ff; }.history-older { display: block; width: 100%; margin-top: .4rem; padding: .3rem 0; color: #526078; font: inherit; font-size: .7rem; background: #eef2f8; border: 1px dashed #c9d4e4; border-radius: .4rem; cursor: pointer; }.history-older:disabled { opacity: .6; cursor: default; }.fold-count { margin-left: .35rem; padding: .02rem .35rem; color: #526078; font-size: .66rem; font-weight: 700; background: #e9eef5; border-radius: .3rem; }
</style>

<style scoped>
.app-group-meta i.app-group-paused { color: #9a641c; background: #fff1d8; }
</style>
