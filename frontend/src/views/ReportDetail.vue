<template>
  <div v-if="report" class="report-view">
    <header class="view-heading report-heading">
      <div>
        <p class="eyebrow">检测报告</p>
        <h1 class="report-app-identity" style="view-transition-name: task-report-identity">{{ report.app_name || '未命名应用' }} · 检测报告</h1>
        <p>{{ report.app_name || '未命名应用' }} · {{ report.report_no }}</p>
      </div>
    </header>
    <section id="summary" class="report-hero surface">
      <div class="assessment-block">
        <span>{{ assessmentLabel }}</span>
        <strong :style="{ color: scoreColor }">{{ scoreDisplay }}</strong>
        <p>{{ assessmentNote }}</p>
      </div>
      <div class="risk-block">
        <span>违规风险分布</span>
        <div><b class="risk-high"><AnimatedNumber :value="report.summary.by_risk['高'] || 0" /><small>高风险</small></b><b class="risk-medium"><AnimatedNumber :value="report.summary.by_risk['中'] || 0" /><small>中风险</small></b><b class="risk-low"><AnimatedNumber :value="report.summary.by_risk['低'] || 0" /><small>低风险</small></b></div>
      </div>
      <div class="report-meta"><span>报告编号</span><strong>{{ report.report_no }}</strong><small>{{ report.app_name || '未命名应用' }}</small></div>
      <el-dropdown class="report-export" trigger="click" popper-class="report-export-popper" @command="downloadReport">
        <el-button type="primary" class="report-export-trigger">
          导出报告 <span class="export-chevron" aria-hidden="true">⌄</span>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="pdf">
              <span class="export-option"><b>PDF 文档</b><small>固定版式，适合提交与归档</small></span>
            </el-dropdown-item>
            <el-dropdown-item command="docx">
              <span class="export-option"><b>Word 文档</b><small>可编辑的 .docx 检测报告</small></span>
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </section>

    <nav class="report-nav surface" :class="{ 'is-condensed': reportNavCondensed }" aria-label="报告页内导航">
      <a href="#summary">检测结论</a><a href="#violations">违规项</a><a href="#coverage">覆盖情况</a>
      <el-button class="report-nav-back" @click="backToTasks">← 返回检测任务</el-button>
    </nav>

    <section v-if="coverageGaps.length" class="coverage-brief">
      <header><div><span class="coverage-mark">!</span><strong>有 {{ coverageGaps.length }} 个覆盖缺口需要补充</strong></div><button type="button" @click="coverageExpanded = !coverageExpanded">{{ coverageExpanded ? '收起' : '查看全部' }}</button></header>
      <ul><li v-for="gap in visibleCoverageGaps" :key="gap">{{ gap }}</li></ul>
      <p>覆盖不足不代表“未发现违规”或“合规”；请补充登录、业务路径或服务端审计证据后复检。</p>
    </section>

    <section v-if="quality" id="method" class="quality-strip report-band">
      <article><span>规则场景尝试</span><strong>{{ quality.scenarios_attempted }} / {{ quality.scenarios_planned }}</strong><small>确定性场景计划</small></article>
      <article><span>动态事件关联</span><strong>{{ quality.time_correlated_events }} / {{ quality.dynamic_events }}</strong><small>页面—操作—API 时间链</small></article>
      <article><span>违规证据绑定</span><strong>{{ quality.evidence_bound_findings }} / {{ quality.finding_count }}</strong><small>仅统计规则专属证据</small></article>
      <article><span>人工基准召回</span><strong>{{ percentOrDash(quality.manual_baseline_recall) }}</strong><small>{{ quality.manual_baseline_false_negatives?.length ? `仍漏报 ${quality.manual_baseline_false_negatives.length} 项` : '无已知基准漏报' }}</small></article>
    </section>
    <section v-if="adjudicationCounts" class="tri-state-strip report-band">
      <div><span>发现违规</span><strong class="violation-count">{{ adjudicationCounts.violation }}</strong></div>
      <div><span>未发现违规证据</span><strong>{{ adjudicationCounts.no_violation_evidence }}</strong></div>
      <div><span>未覆盖 / 无法判定</span><strong class="uncovered-count">{{ adjudicationCounts.not_covered }}</strong></div>
      <p>“未发现违规证据”仅表示对应场景已经完成且未形成违规证据，不等同于 App 合规。</p>
    </section>
    <section class="server-audit-status report-band">
      <div>
        <strong>服务端审计检测</strong>
        <span v-if="serverEvents.length">已关联 {{ serverEvents.length }} 条脱敏业务审计事件，相关结果已参与三态判定。</span>
        <span v-else>尚未收到业务服务端审计数据；设备端无法代替核验删除执行、投诉处理和第三方传输结果。</span>
      </div>
      <em :class="serverEvents.length ? 'connected' : 'not-connected'">{{ serverEvents.length ? '已接入' : '待接入' }}</em>
    </section>

    <section id="violations" class="violation-section surface">
      <header class="violation-heading"><div><p class="eyebrow">风险发现</p><h2>违规项与证据</h2><span>高风险优先展示；展开后查看规则依据、发生位置与整改建议。</span></div><div class="risk-filters"><button v-for="item in riskFilters" :key="item.value" type="button" :class="{ active: riskFilter === item.value }" @click="riskFilter = item.value">{{ item.label }}</button></div></header>
      <el-table ref="violationTableRef" :data="filteredViolations" row-key="id" class="violation-table" @row-click="toggleViolationExpand">
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="evidence-panel">
              <section><h3>认定依据</h3><dl><div><dt>法规依据</dt><dd>{{ row.legal_basis || '—' }}</dd></div><div><dt>发生页面</dt><dd>{{ row.page || '—' }}</dd></div></dl></section>
              <section v-if="screenshotEvidence(row).length" class="evidence-screenshots"><h3>证据截图（优先）</h3><div class="evidence-screenshot-grid"><img v-for="item in screenshotEvidence(row)" :key="item.id" :src="item.url" alt="违规证据截图" loading="lazy"></div></section>
              <section v-if="textEvidence(row).length || !screenshotEvidence(row).length"><h3>证据说明</h3><dl v-if="textEvidence(row).length"><div v-for="item in textEvidence(row)" :key="item.id"><dt>{{ item.type || '文字证据' }}</dt><dd>{{ readableValue(item.meta) }}</dd></div></dl><p v-else>未取得可用截图；请结合页面、操作时间线和动态监测记录核验。</p></section>
              <section v-if="detailEntries(row.detail).length"><h3>检测证据</h3><dl><div v-for="item in detailEntries(row.detail)" :key="item.key"><dt>{{ item.label }}</dt><dd>{{ item.value }}</dd></div></dl></section>
              <aside><strong>整改建议</strong><p>{{ row.suggestion || '请依据对应法规条款补充说明和用户控制能力。' }}</p></aside>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="category" label="类别" width="220">
          <template #default="{ row }"><span class="category-cell"><b>第{{ row.category }}类</b>{{ row.category_name }}</span></template>
        </el-table-column>
        <el-table-column prop="description" label="违规描述" />
        <el-table-column prop="risk_level" label="风险等级" width="100">
          <template #default="{ row }"><el-tag :type="row.risk_level === '高' ? 'danger' : row.risk_level === '中' ? 'warning' : 'success'">{{ row.risk_level }}风险</el-tag></template>
        </el-table-column>
      </el-table>
      <div v-if="!filteredViolations.length" class="violation-empty">当前筛选条件下没有违规项。</div>
    </section>

    <section v-if="reviews.length" id="coverage" class="coverage-section surface">
      <header class="coverage-heading">
        <div>
          <p class="eyebrow">检测覆盖说明</p>
          <h2>认定方法 31 项检查范围</h2>
          <p>这里不需要逐项人工填写。系统优先执行可自动化场景；页面只保留尚未覆盖项，以及必须由服务端核对的后台事实。</p>
        </div>
        <div class="coverage-counts">
          <span>自动发现 {{ report.violations.length }}</span>
          <span>尚待核定 {{ manualChecks.length + serverChecks.length }}</span>
        </div>
      </header>

      <div class="coverage-summary">
        <article class="coverage-metric evidence"><span>已自动检测</span><strong>{{ deviceChecks.length }} 项</strong><p>设备页面、权限弹窗、Frida 动态行为可直接形成证据。</p></article>
        <article v-if="manualChecks.length" class="coverage-metric manual"><span>特殊流程补充</span><strong>{{ manualChecks.length }} 项</strong><p>自动化暂未配置的特殊业务流程；不是默认的人工填表任务。</p></article>
        <article class="coverage-metric server"><span>需服务端审计</span><strong>{{ serverChecks.length }} 项</strong><p>涉及后台处理、第三方传输和删除请求实际执行情况。</p></article>
      </div>

      <section v-if="report.violations.length" class="detected-evidence">
        <header><strong>本次已形成自动证据</strong><span>以下项目已进入报告，可查看对应截图、时间线或动态调用证据。</span></header>
        <ul><li v-for="item in report.violations" :key="item.id"><b>第{{ item.category }}类</b><span>{{ item.description }}</span><em>{{ item.risk_level }}风险</em></li></ul>
      </section>

      <div class="check-groups">
        <article class="check-group device-group">
          <header><strong>自动设备检测</strong><span>已执行；未形成证据不等于合规</span></header>
          <ul><li v-for="item in visibleDeviceChecks" :key="item.legal_key"><b>{{ item.legal_key }}</b><span>{{ item.title }}</span><em :class="checkState(item).type">{{ checkState(item).label }}</em></li></ul>
        </article>
        <article v-if="manualChecks.length" class="check-group manual-group">
          <header><strong>特殊流程补充</strong><span>仅显示尚未配置自动场景的项目，不把“未测到”写成合规</span></header>
          <ul><li v-for="item in visibleManualChecks" :key="item.legal_key"><b>{{ item.legal_key }}</b><span>{{ item.title }}</span><em>人工流程</em></li></ul>
        </article>
        <article class="check-group server-group">
          <header><strong>需要服务端审计</strong><span>由运营方提供脱敏审计结论，不在本页手工录入</span></header>
          <ul><li v-for="item in visibleServerChecks" :key="item.legal_key"><b>{{ item.legal_key }}</b><span>{{ item.title }}</span><em>服务端审计</em></li></ul>
        </article>
      </div>
      <button v-if="reviews.length > collapsedChecklistCount" type="button" class="checklist-toggle" @click="checklistExpanded = !checklistExpanded">
        {{ checklistExpanded ? '收起检查明细' : `展开全部 ${reviews.length} 项检查明细` }}
      </button>
    </section>
  </div>
  <section v-else-if="loading" class="report-state surface" aria-live="polite">
    <strong>正在加载检测报告…</strong>
    <span>正在读取违规项、覆盖范围和证据链，请稍候。</span>
  </section>
  <section v-else class="report-state surface" role="alert">
    <strong>检测报告暂时无法加载</strong>
    <span>{{ loadError || '请检查服务是否运行后重试。' }}</span>
    <div><el-button type="primary" @click="load">重试</el-button><el-button @click="backToTasks">返回检测任务</el-button></div>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import api from '../api'
import AnimatedNumber from '../components/AnimatedNumber.vue'
import { isNavigationCondensed } from '../utils/uiMotion'

const route = useRoute()
const router = useRouter()
const report = ref(null)
const reviews = ref([])
const serverEvents = ref([])
const loading = ref(true)
const loadError = ref('')
const coverageExpanded = ref(false)
const checklistExpanded = ref(false)
const riskFilter = ref('all')
const violationTableRef = ref(null)
// 整行可点：点行等价于点展开箭头，切换该违规项的证据详情。
function toggleViolationExpand(row) {
  violationTableRef.value?.toggleRowExpansion(row)
}
const reportNavCondensed = ref(false)
let reportNavFrame = null
const riskFilters = [{ label: '全部风险', value: 'all' }, { label: '高风险', value: '高' }, { label: '中风险', value: '中' }, { label: '低风险', value: '低' }]
const automaticEvidenceCount = computed(() => Number(report.value?.summary?.total || 0))
const coverageGaps = computed(() => report.value?.summary?.coverage_gaps || [])
const visibleCoverageGaps = computed(() => coverageExpanded.value ? coverageGaps.value : coverageGaps.value.slice(0, 3))
const filteredViolations = computed(() => {
  const order = { 高: 0, 中: 1, 低: 2 }
  return [...(report.value?.violations || [])]
    .filter(item => riskFilter.value === 'all' || item.risk_level === riskFilter.value)
    .sort((a, b) => (order[a.risk_level] ?? 9) - (order[b.risk_level] ?? 9))
})
const quality = computed(() => report.value?.summary?.quality_metrics || null)
const adjudicationCounts = computed(() => report.value?.summary?.adjudication_counts || null)
const scenarioCoverage = computed(() => report.value?.summary?.scenario_coverage || {})
const completedScenarioKeys = computed(() => new Set(scenarioCoverage.value.completed_items || []))
const attemptedScenarioKeys = computed(() => new Set(scenarioCoverage.value.attempted_items || []))
const scenarioStatusByKey = computed(() => new Map((scenarioCoverage.value.items || []).map(item => [item.item, item])))
const deviceChecks = computed(() => reviews.value.filter(row => row.evidence_scope === 'device'))
const manualChecks = computed(() => reviews.value.filter(row => row.evidence_scope === 'manual'))
const serverChecks = computed(() => reviews.value.filter(row => row.evidence_scope === 'server'))
const CHECKLIST_PREVIEW_SIZE = 5
const visibleDeviceChecks = computed(() => checklistExpanded.value ? deviceChecks.value : deviceChecks.value.slice(0, CHECKLIST_PREVIEW_SIZE))
const visibleManualChecks = computed(() => checklistExpanded.value ? manualChecks.value : manualChecks.value.slice(0, CHECKLIST_PREVIEW_SIZE))
const visibleServerChecks = computed(() => checklistExpanded.value ? serverChecks.value : serverChecks.value.slice(0, CHECKLIST_PREVIEW_SIZE))
const collapsedChecklistCount = computed(() => [deviceChecks.value, manualChecks.value, serverChecks.value].reduce((total, items) => total + Math.min(items.length, CHECKLIST_PREVIEW_SIZE), 0))
const ruleChecklistKeys = {
  RULE_1_1: ['1.1'], RULE_1_3: ['1.3'], RULE_2_1: ['2.1'], RULE_2_1_SDK: ['2.1'], RULE_2_2: ['2.3'],
  RULE_3_1: ['3.1'], RULE_3_2: ['3.3'], RULE_3_4: ['3.4'], RULE_4_1: ['4.1'], RULE_4_1_CONSENT: ['4.1'],
  RULE_4_2: ['4.2'], RULE_4_3: ['4.2'], RULE_4_4: ['4.4'], RULE_4_6: ['4.6'],
  RULE_6_2: ['6.2'], RULE_6_3: ['6.5'], RULE_6_4: ['6.5'], RULE_6_5: ['6.5'],
}
const detectedChecklistKeys = computed(() => new Set(report.value?.violations.flatMap(item => ruleChecklistKeys[item.rule_id] || []) || []))
const ruleGapKeywords = {
  '1.1': ['隐私政策', '服务条款'],
  '1.3': ['隐私政策', '服务条款'],
  '2.3': ['权限弹窗', '敏感权限'],
  '3.1': ['动态监测', '敏感 API', '第三方 SDK'],
  '4.1': ['权限弹窗', '敏感权限'],
  '4.2': ['敏感业务', '权限弹窗', '敏感权限'],
  '4.4': ['动态监测', '敏感 API'],
  '4.6': ['权限弹窗', '敏感权限'],
  '6.2': ['登录后功能'],
  '6.5': ['隐私政策', '投诉', '举报', '客服', '处理时效'],
}
// These entries have a real device-side evidence producer.  The remaining
// device checklist entries stay visible, but must not be phrased as if they
// had already been automatically adjudicated.
const realAutomaticChecklistKeys = new Set(['1.3', '2.3', '3.1', '3.4', '4.1', '4.2', '4.4', '4.6', '6.2', '6.5'])
const assessmentState = computed(() => {
  if (coverageGaps.value.length) return 'in_progress'
  return automaticEvidenceCount.value ? 'reviewed' : 'pending'
})
const assessmentLabel = computed(() => coverageGaps.value.length ? '自动检测覆盖状态' : automaticEvidenceCount.value ? '自动证据评分' : '自动证据结果')
const scoreDisplay = computed(() => {
  if (coverageGaps.value.length) return '待补充'
  if (automaticEvidenceCount.value) return report.value.score
  if (assessmentState.value === 'pending') return '待核验'
  if (assessmentState.value === 'in_progress') return '核验中'
  return '未发现自动证据'
})
const assessmentNote = computed(() => {
  if (coverageGaps.value.length) return `本次仅形成 ${automaticEvidenceCount.value} 项自动证据，但仍有 ${coverageGaps.value.length} 个覆盖缺口；不能以当前分数代替完整检测结论。`
  if (assessmentState.value === 'pending') return `自动规则命中 ${automaticEvidenceCount.value} 项；31 项认定方法尚未核验，不能据此给出合规分数。`
  if (assessmentState.value === 'in_progress') return '仍有未覆盖路径，暂不展示合规分数。'
  return `该分数仅反映自动规则命中；最终认定以 31 项核验结论和服务端审计为准。`
})
const scoreColor = computed(() => coverageGaps.value.length ? '#d68620' : !automaticEvidenceCount.value ? assessmentState.value === 'in_progress' ? '#d68620' : '#6a7890' : report.value.score >= 80 ? '#27ae60' : report.value.score >= 60 ? '#d35400' : '#c0392b')
function percentOrDash(value) { return value == null ? '无基准' : `${(Number(value) * 100).toFixed(1)}%` }
const DETAIL_LABELS = {
  data_type: '数据类型', sdk: '相关 SDK', host: '网络域名', count: '发生次数',
  permissions: '相关权限', matched_by: '识别依据', evidence_source: '证据来源',
  pages_covered: '覆盖页面', termination: '终止原因', industry: '业务行业',
}
function readableValue(value) {
  if (value == null || value === '') return '—'
  if (Array.isArray(value)) return value.map(readableValue).join('、')
  if (typeof value === 'object') return Object.entries(value).slice(0, 8).map(([key, item]) => `${DETAIL_LABELS[key] || key}：${readableValue(item)}`).join('；')
  if (typeof value === 'boolean') return value ? '是' : '否'
  return String(value)
}
function detailEntries(detail) {
  if (!detail || typeof detail !== 'object') return []
  return Object.entries(detail).filter(([, value]) => value != null && value !== '').slice(0, 12).map(([key, value]) => ({ key, label: DETAIL_LABELS[key] || key.replaceAll('_', ' '), value: readableValue(value) }))
}
function checkState(item) {
  if (detectedChecklistKeys.value.has(item.legal_key)) return { label: '已形成证据', type: 'found' }
  const queueItem = scenarioStatusByKey.value.get(item.legal_key)
  if (queueItem?.state === 'evidence_observed') return { label: '场景已完整执行，未形成违规证据', type: 'pending' }
  if (queueItem?.state === 'blocked_external') return { label: `待补充：${queueItem.reason}`, type: 'missing' }
  if (queueItem?.state === 'requires_login') return { label: `待补充：${queueItem.reason}`, type: 'missing' }
  if (queueItem?.state === 'requires_server_audit') return { label: `待补充：${queueItem.reason}`, type: 'missing' }
  if (queueItem?.state === 'attempted') return { label: '场景已尝试，证据链尚未闭合', type: 'missing' }
  if (completedScenarioKeys.value.has(item.legal_key)) return { label: '场景已完整执行，未形成违规证据', type: 'pending' }
  if (attemptedScenarioKeys.value.has(item.legal_key)) return { label: '场景已尝试，证据链尚未闭合', type: 'missing' }
  const gap = coverageGaps.value.find(value => (ruleGapKeywords[item.legal_key] || []).some(keyword => value.includes(keyword)))
  if (gap) return { label: `待补充：${gap}`, type: 'missing' }
  if (!realAutomaticChecklistKeys.has(item.legal_key)) return { label: '当前未具备真实自动判定', type: 'pending' }
  return { label: '已执行条件检测，未发现可判定证据', type: 'pending' }
}
async function load() {
  loading.value = true
  loadError.value = ''
  const taskId = route.params.taskId
  try {
    const [reportResponse, reviewsResponse, serverResponse] = await Promise.all([
      api.get(`/reports/${taskId}`), api.get(`/tasks/${taskId}/reviews`),
      api.get(`/tasks/${taskId}/reviews/server-events`),
    ])
    const data = reportResponse.data || {}
    report.value = {
      ...data,
      violations: Array.isArray(data.violations) ? data.violations : [],
      summary: { ...(data.summary || {}), by_risk: { ...(data.summary?.by_risk || {}) } },
    }
    reviews.value = Array.isArray(reviewsResponse.data) ? reviewsResponse.data : []
    serverEvents.value = Array.isArray(serverResponse.data) ? serverResponse.data : []
  } catch (error) {
    loadError.value = error.response?.data?.detail || '读取报告接口失败'
  } finally {
    loading.value = false
  }
}
function downloadReport(format) { window.open(`/api/reports/${route.params.taskId}/${format}`) }
function backToTasks() {
  if (window.history.state?.back) router.back()
  else router.replace('/tasks')
}
function screenshotEvidence(row) { return (row?.evidence || []).filter(item => item.type === 'screenshot') }
function textEvidence(row) { return (row?.evidence || []).filter(item => item.type !== 'screenshot') }
function syncReportNavState() {
  cancelAnimationFrame(reportNavFrame)
  reportNavFrame = requestAnimationFrame(() => {
    reportNavCondensed.value = isNavigationCondensed(window.scrollY)
  })
}
onMounted(() => {
  load()
  syncReportNavState()
  window.addEventListener('scroll', syncReportNavState, { passive: true })
})
onUnmounted(() => {
  window.removeEventListener('scroll', syncReportNavState)
  cancelAnimationFrame(reportNavFrame)
})
</script>

<style scoped>
.report-heading { margin-bottom: 1.25rem; }
.report-app-identity { animation: none; }
.report-state { display: grid; justify-items: center; gap: .55rem; min-height: 16rem; margin-top: 1rem; padding: 3rem 1.5rem; color: #718096; text-align: center; }
.report-state strong { color: #30435f; font-size: 1rem; }
.report-state span { max-width: 34rem; font-size: .78rem; line-height: 1.6; }
.report-state div { display: flex; gap: .55rem; margin-top: .65rem; }
.report-heading h1 { margin: .25rem 0; font-size: 1.35rem; }
.report-heading p:last-child { margin: 0; color: #7b8495; font-size: .82rem; }
.score-note { max-width: 22rem; margin-top: .35rem; color: #74829a; font-size: .72rem; line-height: 1.5; }.coverage-alert { margin: 0 0 1rem; }.coverage-alert ul { margin: .35rem 0; padding-left: 1.1rem; }.coverage-alert span { color: #7b653c; font-size: .78rem; }
.server-audit-status { display: flex; align-items: center; gap: 1rem; margin: .8rem 0 1rem; padding: .9rem 1rem; }.server-audit-status div { display: grid; gap: .2rem; margin-right: auto; }.server-audit-status strong { color: #2b3c56; font-size: .82rem; }.server-audit-status span { color: #75839a; font-size: .7rem; line-height: 1.5; }.server-audit-status em { padding: .3rem .55rem; border-radius: .45rem; font-size: .68rem; font-style: normal; }.server-audit-status .connected { color: #237c50; background: #eaf7ef; }.server-audit-status .not-connected { color: #a56b16; background: #fff5df; }
.quality-strip { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; margin: 0 0 1rem; overflow: hidden; background: #e6ebf3; border: 1px solid #e6ebf3; }.quality-strip article { display: grid; gap: .28rem; padding: .9rem 1rem; background: #fff; }.quality-strip span { color: #6d7c93; font-size: .7rem; }.quality-strip strong { color: #263a59; font-size: 1.15rem; font-variant-numeric: tabular-nums; }.quality-strip small { color: #8793a5; font-size: .65rem; }
.tri-state-strip { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .65rem 1rem; margin: 0 0 1rem; padding: .9rem 1rem; }.tri-state-strip div { display: flex; align-items: baseline; justify-content: space-between; padding-right: 1rem; border-right: 1px solid #e8edf4; }.tri-state-strip div:nth-child(3) { border-right: 0; }.tri-state-strip span { color: #64758e; font-size: .72rem; }.tri-state-strip strong { color: #29415f; font-size: 1.15rem; }.tri-state-strip .violation-count { color: #c64848; }.tri-state-strip .uncovered-count { color: #d08325; }.tri-state-strip p { grid-column: 1 / -1; margin: 0; color: #7c899b; font-size: .68rem; }
.coverage-section { margin-top: 1.25rem; padding: 1.35rem; }.coverage-heading { display: flex; justify-content: space-between; gap: 1.25rem; }.coverage-heading .eyebrow { margin-bottom: .3rem; }.coverage-heading h2 { margin: 0; font-size: 1.08rem; }.coverage-heading p:last-child { max-width: 48rem; margin: .45rem 0 0; color: #718097; font-size: .78rem; line-height: 1.6; }.coverage-counts { display: grid; align-content: start; gap: .35rem; min-width: 8.5rem; color: #5c6b82; font-size: .76rem; font-variant-numeric: tabular-nums; text-align: right; }.coverage-summary { display: grid; grid-template-columns: 1.1fr 1fr 1fr; gap: .7rem; margin: 1.15rem 0; }.coverage-metric { min-height: 7.3rem; padding: .9rem 1rem; border-radius: .75rem; }.coverage-metric span { display: block; color: #667892; font-size: .72rem; font-weight: 800; }.coverage-metric strong { display: block; margin: .35rem 0; color: #253550; font-size: 1.35rem; font-variant-numeric: tabular-nums; }.coverage-metric p { margin: 0; color: #718097; font-size: .7rem; line-height: 1.55; }.evidence { background: #f0f7ff; }.manual { background: #fff8ec; }.server { background: #f6f3ff; }.detected-evidence { margin: 1rem 0; padding: .9rem 1rem; background: #f0faf4; border: 1px solid #d8eddf; border-radius: .7rem; }.detected-evidence header { display: grid; gap: .2rem; }.detected-evidence header strong { color: #246443; font-size: .82rem; }.detected-evidence header span { color: #698098; font-size: .73rem; line-height: 1.55; }.detected-evidence ul { display: grid; gap: .35rem; padding: 0; margin: .7rem 0 0; list-style: none; }.detected-evidence li { display: flex; align-items: baseline; gap: .45rem; }.detected-evidence li b { color: #24704a; font-size: .7rem; }.detected-evidence li span { color: #42536a; font-size: .75rem; }.detected-evidence li em { margin-left: auto; color: #9a5a25; font-size: .68rem; font-style: normal; }.check-groups { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .8rem; margin-top: 1.1rem; }.check-group { min-width: 0; border-top: 3px solid; }.device-group { border-color: #79aee8; }.manual-group { border-color: #e5bb6b; }.server-group { border-color: #a58ee8; }.check-group header { padding: .75rem .1rem .55rem; }.check-group header strong, .check-group header span { display: block; }.check-group header strong { color: #34445e; font-size: .82rem; }.check-group header span { margin-top: .25rem; color: #7d899b; font-size: .68rem; line-height: 1.45; }.check-group ul { display: grid; gap: .3rem; padding: 0; margin: 0; list-style: none; }.check-group li { display: grid; grid-template-columns: 2.2rem minmax(0, 1fr); gap: .38rem; align-items: start; padding: .48rem 0; border-bottom: 1px solid #edf0f5; }.check-group li b { color: #63748e; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .68rem; }.check-group li span { color: #53637b; font-size: .7rem; line-height: 1.4; }.check-group li em { grid-column: 2; color: #9a6c22; font-size: .66rem; font-style: normal; }.check-group li em.found { color: #2c8756; }.check-group li em.missing { color: #b87520; }.check-group li em.pending { color: #7b8799; }.checklist-toggle { display: block; margin: 1rem auto 0; padding: .48rem .75rem; color: #41627d; font: inherit; font-size: .7rem; font-weight: 750; background: #f4f8fa; border: 1px solid #d9e4ea; border-radius: .42rem; cursor: pointer; }.checklist-toggle:hover { color: #246fb8; border-color: #b8d3e5; }
@media (max-width: 860px) { .quality-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }.server-audit-status { align-items: stretch; flex-direction: column; }.coverage-heading { flex-direction: column; }.coverage-counts { text-align: left; }.coverage-summary, .check-groups { grid-template-columns: 1fr; }.coverage-section { padding: 1rem; } }
</style>

<style scoped>
.report-hero { display: grid; grid-template-columns: minmax(15rem, 1.15fr) minmax(14rem, .9fr) minmax(14rem, 1fr) auto; gap: 1.5rem; align-items: center; margin-bottom: .7rem; padding: 1.25rem 1.35rem; }
.assessment-block, .report-meta { display: grid; gap: .2rem; min-width: 0; }
.assessment-block > span, .risk-block > span, .report-meta > span { color: #788895; font-size: .67rem; font-weight: 700; letter-spacing: .04em; }
.assessment-block > strong { font-size: clamp(1.8rem, 4vw, 2.65rem); line-height: 1.1; letter-spacing: -.055em; }
.assessment-block p { max-width: 25rem; margin: .18rem 0 0; color: #71818e; font-size: .69rem; line-height: 1.5; }
.risk-block { display: grid; gap: .55rem; }
.risk-block > div { display: flex; gap: .85rem; }
.risk-block b { display: grid; gap: .08rem; font-size: 1.25rem; font-variant-numeric: tabular-nums; }
.risk-block small { color: #7a8995; font-size: .62rem; font-weight: 650; }
.risk-high { color: #bd4b4f; }.risk-medium { color: #b97820; }.risk-low { color: #347c61; }
.report-meta strong { overflow: hidden; color: #294356; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .72rem; text-overflow: ellipsis; white-space: nowrap; }
.report-meta small { color: #738491; font-size: .7rem; }
.report-nav { position: sticky; top: 5.15rem; z-index: 6; display: flex; gap: .2rem; margin-bottom: .8rem; padding: .35rem; background: rgba(249,251,252,.92); backdrop-filter: blur(12px); }
.report-nav a { padding: .5rem .7rem; color: #607584; font-size: .7rem; font-weight: 750; text-decoration: none; border-radius: .36rem; }
.report-nav a:hover { color: #246fb8; background: #e9f2f8; }
.report-nav-back { margin-left: auto; }
.coverage-brief { margin-bottom: .9rem; padding: .9rem 1rem; color: #74571f; background: #fff8e9; border: 1px solid #ead9ae; border-radius: .72rem; }
.coverage-brief header { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
.coverage-brief header > div { display: flex; align-items: center; gap: .55rem; }
.coverage-mark { display: grid; width: 1.3rem; height: 1.3rem; place-items: center; color: #fff; font-size: .74rem; font-weight: 850; background: #b97820; border-radius: 50%; }
.coverage-brief strong { font-size: .78rem; }
.coverage-brief button { padding: .25rem .45rem; color: #8a6425; font: inherit; font-size: .67rem; font-weight: 750; background: transparent; border: 1px solid #dec890; border-radius: .32rem; cursor: pointer; }
.coverage-brief ul { display: grid; gap: .28rem; margin: .65rem 0 .5rem; padding-left: 1.25rem; }
.coverage-brief li, .coverage-brief p { color: #816b42; font-size: .69rem; line-height: 1.5; }
.coverage-brief p { margin: 0; }
.violation-section { margin-top: 1rem; overflow: hidden; scroll-margin-top: 9rem; }
.violation-heading { display: flex; align-items: end; justify-content: space-between; gap: 1rem; padding: 1.15rem 1.2rem; border-bottom: 1px solid #e4eaee; }
.violation-heading .eyebrow { margin-bottom: .25rem; }
.violation-heading h2 { margin: 0; color: #1f394d; font-size: 1.08rem; }
.violation-heading span { display: block; margin-top: .35rem; color: #7b8995; font-size: .7rem; }
.risk-filters { display: flex; gap: .18rem; padding: .2rem; background: #edf2f4; border-radius: .45rem; }
.risk-filters button { padding: .38rem .58rem; color: #6c7e8c; font: inherit; font-size: .67rem; font-weight: 700; background: transparent; border: 0; border-radius: .32rem; cursor: pointer; }
.risk-filters button.active { color: #173047; background: #fff; box-shadow: 0 2px 7px rgba(24,55,75,.09); }
.violation-table { --el-table-header-bg-color: #f7f9fa; --el-table-row-hover-bg-color: #f2f6f8; }
.violation-table :deep(th.el-table__cell) { color: #71818e; font-size: .69rem; font-weight: 800; }
.violation-table :deep(.el-table__cell) { padding: .75rem 0; }
.violation-table :deep(tbody .el-table__row) { cursor: pointer; }
.category-cell { display: grid; gap: .12rem; color: #5e7180; font-size: .7rem; line-height: 1.4; }
.category-cell b { color: #2d526b; font-size: .68rem; }
.evidence-panel { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .9rem; padding: 1rem 1.25rem; background: #f7f9fa; }
.evidence-panel section, .evidence-panel aside { min-width: 0; padding: .85rem; background: #fff; border: 1px solid #e1e8ec; border-radius: .55rem; }
.evidence-panel h3, .evidence-panel aside strong { margin: 0 0 .55rem; color: #29475b; font-size: .74rem; }
.evidence-panel dl { display: grid; gap: .48rem; margin: 0; }
.evidence-panel dl div { display: grid; grid-template-columns: 5.2rem minmax(0, 1fr); gap: .55rem; }
.evidence-panel dt { color: #81909b; font-size: .66rem; }.evidence-panel dd { margin: 0; overflow-wrap: anywhere; color: #526775; font-size: .69rem; line-height: 1.5; }
.evidence-panel aside { grid-column: 1 / -1; color: #78591f; background: #fff9eb; border-color: #eadcb7; }
.evidence-panel aside p { margin: .3rem 0 0; font-size: .7rem; line-height: 1.55; }
.evidence-screenshots { grid-column: 1 / -1; }
.evidence-screenshot-grid { display: flex; flex-wrap: wrap; gap: .65rem; }
.evidence-screenshot-grid img { display: block; max-width: min(100%, 22rem); max-height: 24rem; object-fit: contain; border: 1px solid #dfe7ec; border-radius: .45rem; background: #f5f7f8; }
.violation-empty { padding: 2rem; color: #7b8995; font-size: .75rem; text-align: center; }
#coverage { scroll-margin-top: 9rem; }
@media (max-width: 900px) {
  .report-hero { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .report-hero > .report-export { justify-self: start; }
  .violation-heading { align-items: stretch; flex-direction: column; }
  .risk-filters { align-self: flex-start; }
}
@media (max-width: 620px) {
  .report-hero { grid-template-columns: 1fr; }
  .report-nav { top: 4.7rem; overflow-x: auto; }
  .report-nav a { flex: 0 0 auto; }
  .report-nav-back { flex: 0 0 auto; }
  .evidence-panel { grid-template-columns: 1fr; }
  .evidence-panel aside { grid-column: auto; }
  .risk-filters { max-width: 100%; overflow-x: auto; }
}
</style>

<style scoped>
/* Report typography is intentionally a step larger than the data-library UI:
   long findings and evidence must remain readable during review sessions. */
.report-heading h1 { font-size: clamp(1.65rem, 3vw, 2.2rem); }
.report-heading p:last-child { font-size: .92rem; }
.assessment-block > span, .risk-block > span, .report-meta > span { font-size: .77rem; }
.assessment-block p { font-size: .8rem; line-height: 1.65; }
.risk-block b { font-size: 1.42rem; }
.risk-block small { font-size: .72rem; }
.report-meta strong { font-size: .82rem; }
.report-meta small { font-size: .8rem; }
.report-nav a { padding: .58rem .78rem; font-size: .8rem; }
.coverage-brief strong { font-size: .89rem; }
.coverage-brief button { font-size: .77rem; }
.coverage-brief li, .coverage-brief p { font-size: .79rem; }
.quality-strip span { font-size: .8rem; }
.quality-strip strong { font-size: 1.3rem; }
.quality-strip small { font-size: .75rem; }
.tri-state-strip span { font-size: .82rem; }
.tri-state-strip strong { font-size: 1.3rem; }
.tri-state-strip p { font-size: .78rem; line-height: 1.55; }
.server-audit-status strong { font-size: .93rem; }
.server-audit-status span { font-size: .8rem; }
.server-audit-status em { font-size: .78rem; }
.violation-heading h2, .coverage-heading h2 { font-size: 1.24rem; }
.violation-heading span { font-size: .8rem; }
.risk-filters button { font-size: .77rem; }
.violation-table :deep(th.el-table__cell) { font-size: .79rem; }
.violation-table :deep(td.el-table__cell) { font-size: .84rem; }
.category-cell { font-size: .8rem; }
.category-cell b { font-size: .78rem; }
.evidence-panel h3, .evidence-panel aside strong { font-size: .85rem; }
.evidence-panel dt { font-size: .76rem; }
.evidence-panel dd { font-size: .8rem; }
.evidence-panel aside p { font-size: .81rem; }
.violation-empty { font-size: .85rem; }
.coverage-heading p:last-child { font-size: .88rem; }
.coverage-counts { font-size: .86rem; }
.coverage-metric span { font-size: .82rem; }
.coverage-metric strong { font-size: 1.5rem; }
.coverage-metric p { font-size: .8rem; }
.detected-evidence header strong { font-size: .93rem; }
.detected-evidence header span { font-size: .83rem; }
.detected-evidence li b { font-size: .8rem; }
.detected-evidence li span { font-size: .85rem; }
.detected-evidence li em { font-size: .78rem; }
.check-group header strong { font-size: .93rem; }
.check-group header span { font-size: .78rem; }
.check-group li b { font-size: .78rem; }
.check-group li span { font-size: .8rem; }
.check-group li em { font-size: .76rem; }
.checklist-toggle { font-size: .8rem; }
.report-export-trigger { min-width: 7.6rem; }
.export-chevron { display: inline-block; margin-left: .45rem; font-size: 1rem; line-height: 1; transition: transform .28s cubic-bezier(.2,.8,.2,1); }
.report-export:hover .export-chevron { transform: translateY(1px); }
</style>

<style scoped>
/* The report is a reading surface: only the conclusion and findings keep
   card elevation; method, audit and tri-state sections read as dividers. */
.report-nav { transition: padding var(--motion-panel) var(--motion-ease), background var(--motion-panel) var(--motion-ease), border-radius var(--motion-panel) var(--motion-ease), box-shadow var(--motion-panel) var(--motion-ease); }
.report-nav.is-condensed { padding: .22rem; background: rgba(250,253,255,.94); border-radius: .88rem; box-shadow: 0 10px 25px rgba(48,87,117,.13), inset 0 1px 0 #fff; }
.report-nav.is-condensed a { padding-block: .42rem; }.report-nav.is-condensed :deep(.report-nav-back) { min-height: 2.1rem; }
.report-band { margin: 0; padding: 1rem 0; background: transparent; border: 0; border-top: 1px solid rgba(126,157,183,.22); border-radius: 0; box-shadow: none; }
.report-band + .report-band { border-top-color: rgba(126,157,183,.18); }
.quality-strip { gap: 0; margin: 0; overflow: visible; background: transparent; border: 0; }
.report-view .quality-strip article { padding: .25rem 1rem; background: transparent; border-right: 1px solid rgba(126,157,183,.18); box-shadow: none; }
.quality-strip article:first-child { padding-left: 0; }.quality-strip article:last-child { padding-right: 0; border-right: 0; }
.tri-state-strip { margin: 0; padding-inline: 0; }.server-audit-status { margin: 0; padding-inline: 0; background: transparent; border: 0; box-shadow: none; }
@media (max-width: 860px) { .report-view .quality-strip article { padding-inline: 0; border-right: 0; border-bottom: 1px solid rgba(126,157,183,.16); }.report-view .quality-strip article:last-child { border-bottom: 0; } }
</style>
