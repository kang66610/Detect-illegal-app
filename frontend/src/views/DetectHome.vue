<template>
  <section class="apps-view">
    <header class="view-heading library-heading">
      <div>
        <p class="eyebrow">应用资产 / APK LIBRARY</p>
        <h1>应用样本与检测入口</h1>
        <p>上传 APK 后完成加密存储、基础静态分析，再创建真实设备检测任务。</p>
      </div>
      <div class="library-stats" aria-label="应用库概览">
        <span><b>{{ apks.length }}</b>应用样本</span>
        <span><b>{{ parsedCount }}</b>解析成功</span>
        <button type="button" class="library-refresh" :disabled="libraryLoading" @click="load">{{ libraryLoading ? '刷新中…' : '↻ 刷新' }}</button>
        <RouterLink to="/tasks">查看检测任务 →</RouterLink>
      </div>
    </header>

    <p v-if="libraryError" class="library-refresh-error" role="status">
      {{ libraryError }}
      <button type="button" @click="load">重试</button>
    </p>

    <section class="upload-panel surface">
      <div class="upload-copy">
        <span class="upload-kicker">01 / 上传样本</span>
        <h2>提交 Android APK</h2>
        <p>单文件最大 500 MB。上传后自动校验格式、加密保存，并提取权限、SDK、签名和网络端点。</p>
        <div class="upload-assurance"><span>✓ SHA-256 去重</span><span>✓ 本地加密存储</span><span>✓ 静态分析有界扫描</span></div>
      </div>
      <div class="upload-action">
        <el-upload ref="uploadRef" class="apk-upload" drag :auto-upload="false" accept=".apk" :limit="1" :show-file-list="false" :on-change="onFile" :on-exceed="onExceed">
          <div class="upload-symbol" aria-hidden="true">↑</div>
          <strong>{{ file ? file.name : '拖入 APK，或点击选择文件' }}</strong>
          <span>{{ file ? fileSize(file.size) : '仅支持 .apk 格式' }}</span>
        </el-upload>
        <div class="upload-buttons">
          <el-button type="primary" size="large" :disabled="!file" :loading="uploading" @click="upload">上传并解析</el-button>
          <el-button v-if="file" type="danger" text size="large" @click="clearFile">移除文件</el-button>
        </div>
      </div>
    </section>

    <section class="apps-table-section surface">
      <header class="section-title">
        <div><p class="eyebrow">已入库</p><h2>应用资产</h2></div>
        <span>{{ filteredApks.length }} / {{ apks.length }} 个样本</span>
      </header>

      <div class="asset-toolbar">
        <el-input v-model="search" clearable placeholder="搜索应用名称、包名或文件名">
          <template #prefix><span class="search-symbol">⌕</span></template>
        </el-input>
        <el-select v-model="statusFilter" aria-label="解析状态筛选">
          <el-option label="全部解析状态" value="all" />
          <el-option label="解析成功" value="success" />
          <el-option label="解析失败" value="failed" />
          <el-option label="格式无效" value="invalid" />
        </el-select>
      </div>

      <el-table v-if="pagedApks.length" :data="pagedApks" class="apps-table">
        <el-table-column label="应用" min-width="260">
          <template #default="{ row }">
            <div class="app-identity">
              <span :class="['app-avatar', `tone-${avatarTone(row)}`]">{{ appInitial(row) }}</span>
              <span><strong>{{ row.app_name || '未命名应用' }}</strong><small>{{ row.filename }}</small></span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="标识信息" min-width="220">
          <template #default="{ row }"><div class="package-copy"><span>{{ row.package_name || '—' }}</span><small>{{ row.sha256?.slice(0, 12) }}…</small></div></template>
        </el-table-column>
        <el-table-column label="静态画像" width="150">
          <template #default="{ row }">
            <div v-if="row.static_summary" class="static-badges">
              <span>{{ row.static_summary.url_domains?.length || 0 }} 域名</span>
              <span>{{ row.sdk_list?.length || 0 }} SDK</span>
            </div>
            <span v-else class="muted-state">待生成摘要</span>
          </template>
        </el-table-column>
        <el-table-column label="解析状态" width="110">
          <template #default="{ row }"><el-tag v-if="row.parse_status === 'success'" type="success">已解析</el-tag><el-tooltip v-else-if="row.parse_status === 'invalid'" :content="row.parse_message"><el-tag type="danger">格式无效</el-tag></el-tooltip><el-tag v-else type="warning">{{ row.parse_status }}</el-tag></template>
        </el-table-column>
        <el-table-column label="权限" width="80"><template #default="{ row }"><span class="permission-count">{{ (row.permissions || []).length }}</span></template></el-table-column>
        <el-table-column label="操作" width="250" fixed="right" class-name="action-cell">
          <template #default="{ row }">
            <el-button size="small" text @click="openDetail(row)">详情</el-button>
            <el-button size="small" type="primary" :disabled="row.parse_status !== 'success'" @click="openCreate(row)">创建检测</el-button>
            <el-button size="small" type="danger" text @click="removeApk(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div v-else-if="libraryLoading && !apks.length" class="apps-empty" role="status" aria-live="polite"><div class="empty-mark loading-mark" aria-hidden="true">…</div><strong>正在加载应用库</strong><span>正在读取已上传的 APK，请稍候。</span></div>
      <div v-else-if="libraryError && !apks.length" class="apps-empty"><div class="empty-mark" aria-hidden="true">!</div><strong>应用库暂时不可用</strong><span>请点击上方“重试”，不要把接口错误当成没有应用。</span></div>
      <div v-else-if="apks.length" class="apps-empty"><div class="empty-mark" aria-hidden="true">⌕</div><strong>没有匹配的应用</strong><span>调整关键词或解析状态后重试。</span></div>
      <div v-else class="apps-empty"><div class="empty-mark" aria-hidden="true">＋</div><strong>还没有上传样本</strong><span>从上方上传第一个 APK 文件。</span></div>
      <footer v-if="filteredApks.length > pageSize" class="table-pagination">
        <span>每页 {{ pageSize }} 项</span>
        <el-pagination v-model:current-page="page" :page-size="pageSize" :total="filteredApks.length" layout="prev, pager, next" />
      </footer>
    </section>

    <el-drawer v-model="detailVisible" size="min(92vw, 560px)" direction="rtl">
      <template #header>
        <div v-if="selectedApk" class="drawer-title"><span :class="['app-avatar', `tone-${avatarTone(selectedApk)}`]">{{ appInitial(selectedApk) }}</span><div><strong>{{ selectedApk.app_name || '未命名应用' }}</strong><small>{{ selectedApk.package_name || selectedApk.filename }}</small></div></div>
      </template>
      <div v-if="selectedApk" class="static-detail">
        <section class="detail-overview">
          <div><span>声明权限</span><strong>{{ selectedApk.permissions?.length || 0 }}</strong></div>
          <div><span>第三方 SDK</span><strong>{{ selectedApk.sdk_list?.length || 0 }}</strong></div>
          <div><span>风险提示</span><strong>{{ selectedApk.static_summary?.indicators?.length || 0 }}</strong></div>
        </section>
        <section class="detail-section">
          <h3>样本信息</h3>
          <dl><div><dt>APK 文件</dt><dd>{{ selectedApk.filename }}</dd></div><div><dt>SHA-256</dt><dd class="hash-copy">{{ selectedApk.sha256 }}</dd></div><div><dt>文件大小</dt><dd>{{ fileSize(selectedApk.size_bytes) }}</dd></div></dl>
        </section>
        <template v-if="selectedApk.static_summary">
          <section class="detail-section">
            <h3>清单与签名</h3>
            <div class="detail-chip-list">
              <span>Target SDK {{ selectedApk.static_summary.manifest?.target_sdk || '—' }}</span>
              <span>{{ signatureLabel(selectedApk) }}</span>
              <span>{{ selectedApk.static_summary.native?.count || 0 }} 个 Native 库</span>
              <span>{{ selectedApk.static_summary.manifest?.exported_components || 0 }} 个导出组件</span>
            </div>
          </section>
          <section class="detail-section">
            <h3>静态风险提示</h3>
            <div v-if="selectedApk.static_summary.indicators?.length" class="indicator-list">
              <article v-for="item in selectedApk.static_summary.indicators" :key="item.rule_id"><i :class="item.severity"></i><div><strong>{{ item.category }}</strong><span>{{ item.evidence }}</span></div></article>
            </div>
            <p v-else class="detail-empty">本次基础扫描未形成风险提示。</p>
          </section>
          <section class="detail-section">
            <h3>网络端点</h3>
            <div v-if="selectedApk.static_summary.url_domains?.length" class="domain-list"><code v-for="domain in selectedApk.static_summary.url_domains.slice(0, 24)" :key="domain">{{ domain }}</code></div>
            <p v-else class="detail-empty">未提取到网络域名。</p>
          </section>
        </template>
        <section v-else class="static-unavailable">
          <strong>该历史样本尚未生成增强静态摘要</strong>
          <p>权限、应用名称和 SDK 数据仍可正常用于检测；增强摘要将在样本重新解析后生成。</p>
        </section>
      </div>
    </el-drawer>

    <el-dialog v-model="createVisible" title="创建检测任务" width="min(92vw, 470px)" align-center>
      <p class="dialog-note">选择业务行业后，系统默认执行深度检测：在同一任务内先跑同意后收集，再重装后跑拒绝权限，结果合并进一份报告。</p>
      <el-form label-position="top">
        <el-form-item label="所属行业"><el-select v-model="form.industry" style="width:100%"><el-option v-for="industry in industries" :key="industry" :label="industry" :value="industry" /></el-select></el-form-item>
      </el-form>
      <template #footer><el-button @click="createVisible = false">暂不创建</el-button><el-button type="primary" :loading="creatingTask" :disabled="creatingTask" @click="createTask">创建并开始</el-button></template>
    </el-dialog>
  </section>
</template>

<script setup>
defineOptions({ name: 'DetectHome' })

import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '../api'

const router = useRouter()
const uploadRef = ref(null)
const file = ref(null)
const uploading = ref(false)
const apks = ref([])
const search = ref('')
const statusFilter = ref('all')
const page = ref(1)
const pageSize = 8
const createVisible = ref(false)
const detailVisible = ref(false)
const selectedApk = ref(null)
const creatingTask = ref(false)
const libraryLoading = ref(false)
const libraryError = ref('')
let libraryLoadPromise = null
const industries = ['通用', '金融理财', '电商购物', '社交通讯', '工具', '医疗健康', '教育', '出行']
const form = ref({ industry: '通用', apkId: null })

const parsedCount = computed(() => apks.value.filter(item => item.parse_status === 'success').length)
const filteredApks = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return apks.value.filter((item) => {
    const matchesStatus = statusFilter.value === 'all' || item.parse_status === statusFilter.value
    const haystack = [item.app_name, item.package_name, item.filename].filter(Boolean).join(' ').toLowerCase()
    return matchesStatus && (!keyword || haystack.includes(keyword))
  })
})
const pagedApks = computed(() => filteredApks.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([search, statusFilter], () => { page.value = 1 })

function onFile(uploadFile) { file.value = uploadFile.raw }
function onExceed(files) { uploadRef.value?.clearFiles(); uploadRef.value?.handleStart(files[0]) }
function clearFile() { uploadRef.value?.clearFiles(); file.value = null }
function fileSize(size) { return `${(Number(size || 0) / 1024 / 1024).toFixed(Number(size || 0) > 1024 * 1024 ? 1 : 2)} MB` }
function appInitial(row) { return String(row?.app_name || row?.filename || 'A').trim().slice(0, 1).toUpperCase() }
function avatarTone(row) {
  const seed = String(row?.package_name || row?.filename || row?.id || '')
  const index = [...seed].reduce((total, char) => total + char.charCodeAt(0), 0) % 4
  return ['blue', 'cyan', 'teal', 'sky'][index]
}
function signatureLabel(row) {
  const signature = row.static_summary?.signature
  if (!signature?.signed) return '未识别签名'
  const schemes = Object.entries(signature.schemes || {}).filter(([, value]) => value).map(([name]) => name.toUpperCase())
  return schemes.length ? `${schemes.join('/')} 签名` : '已签名'
}
async function upload() { uploading.value = true; const data = new FormData(); data.append('file', file.value); try { await api.post('/apks', data, { timeout: 120000 }); ElMessage.success('APK 已上传并完成解析'); clearFile(); await load() } catch (error) { ElMessage.error(error.response?.data?.detail || (error.code === 'ECONNABORTED' ? '解析耗时较长，请稍后刷新应用库查看结果' : '上传失败，请检查 APK 文件')) } finally { uploading.value = false } }
function openDetail(row) { selectedApk.value = row; detailVisible.value = true }
function openCreate(row) { form.value.apkId = row.id; createVisible.value = true }
async function createTask() {
  if (creatingTask.value || !form.value.apkId) return
  creatingTask.value = true
  try {
    await api.post('/tasks', { apk_id: form.value.apkId, industry: form.value.industry, mode: 'deep' })
    createVisible.value = false
    ElMessage.success('检测任务已创建')
    router.push('/tasks')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '任务创建失败')
  } finally {
    creatingTask.value = false
  }
}
async function removeApk(row) {
  try {
    await ElMessageBox.confirm(`删除“${row.filename}”会同时删除它的全部已结束检测任务、报告和证据，且不可恢复。运行中的任务需要先取消。`, '删除 APK', { confirmButtonText: '确认删除', cancelButtonText: '保留 APK', type: 'warning' })
    await api.delete(`/apks/${row.id}`)
    ElMessage.success('APK 及关联检测数据已删除')
    await load()
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(error.response?.data?.detail || '删除 APK 失败')
  }
}
function load() {
  if (libraryLoadPromise) return libraryLoadPromise
  libraryLoading.value = true
  libraryLoadPromise = (async () => {
    try {
      apks.value = (await api.get('/apks')).data
      libraryError.value = ''
      const maxPage = Math.max(1, Math.ceil(filteredApks.value.length / pageSize))
      if (page.value > maxPage) page.value = maxPage
    } catch (error) {
      libraryError.value = `应用库暂时无法刷新：${error.response?.data?.detail || '请检查服务是否运行'}`
    } finally {
      libraryLoading.value = false
      libraryLoadPromise = null
    }
  })()
  return libraryLoadPromise
}
onMounted(load)
</script>

<style scoped>
.library-heading { align-items: center; }
.library-stats { display: flex; align-items: center; gap: 1.15rem; padding: .7rem .85rem; color: #6d7e8e; font-size: .72rem; background: rgba(255,255,255,.62); border: 1px solid #dfe6eb; border-radius: .65rem; }
.library-stats span { display: grid; gap: .05rem; }
.library-stats b { color: #173047; font-size: 1rem; font-variant-numeric: tabular-nums; }
.library-refresh { padding: .3rem .45rem; color: #4e7188; font: inherit; font-size: .68rem; font-weight: 750; background: transparent; border: 1px solid #d7e3ea; border-radius: .4rem; cursor: pointer; white-space: nowrap; }
.library-refresh:hover:not(:disabled) { color: #246fb8; background: #f2f8fc; border-color: #aac9dc; }
.library-refresh:disabled { color: #9baab5; cursor: wait; }
.library-stats a { padding-left: 1rem; color: #246fb8; font-weight: 750; text-decoration: none; border-left: 1px solid #dfe6eb; }
.library-refresh-error { display: flex; align-items: center; gap: .65rem; margin: -.55rem 0 1rem; padding: .62rem .8rem; color: #9a5b1a; font-size: .74rem; line-height: 1.45; background: #fff8e8; border: 1px solid #f0dfb9; border-radius: .7rem; }
.library-refresh-error button { margin-left: auto; padding: .28rem .55rem; color: #246fb8; font: inherit; font-size: .7rem; font-weight: 750; background: #fff; border: 1px solid #cfe0ee; border-radius: .42rem; cursor: pointer; }
.library-refresh-error button:hover { background: #f2f8fc; border-color: #a8c8df; }
.loading-mark { color: #246fb8; animation: loading-pulse 1.2s ease-in-out infinite; }
@keyframes loading-pulse { 0%, 100% { opacity: .35; transform: scale(.92); } 50% { opacity: 1; transform: scale(1.05); } }
.upload-panel { display: grid; grid-template-columns: minmax(0, .9fr) minmax(25rem, 1.1fr); gap: 2.4rem; align-items: center; padding: 1.75rem; margin-bottom: 1.25rem; overflow: hidden; }
.upload-kicker { color: #246fb8; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .68rem; font-weight: 800; letter-spacing: .09em; }
.upload-copy h2 { margin: .65rem 0 .45rem; color: #173047; font-size: 1.25rem; letter-spacing: -.035em; }
.upload-copy p { max-width: 28rem; margin: 0; color: #718291; font-size: .84rem; line-height: 1.7; }
.upload-assurance { display: flex; flex-wrap: wrap; gap: .45rem .8rem; margin-top: 1rem; color: #4f6f83; font-size: .68rem; font-weight: 650; }
.upload-action { display: grid; grid-template-columns: 1fr auto; gap: .75rem; align-items: stretch; }
.upload-buttons { display: grid; grid-template-columns: 1fr; gap: .45rem; }
.upload-buttons :deep(.el-button) { margin-left: 0; }
.apk-upload :deep(.el-upload) { width: 100%; }
.apk-upload :deep(.el-upload-dragger) { display: grid; min-height: 7.8rem; padding: 1rem; color: #526879; border: 1px dashed #adc0ce; border-radius: .65rem; background: linear-gradient(145deg, #f9fbfc, #f0f5f8); place-content: center; transition: border .2s ease, background .2s ease, transform .2s ease; }
.apk-upload :deep(.el-upload-dragger:hover) { border-color: #246fb8; background: #edf5fb; transform: translateY(-1px); }
.apk-upload strong { display: block; max-width: 22rem; margin: .35rem 0; overflow: hidden; color: #31495c; font-size: .83rem; text-overflow: ellipsis; white-space: nowrap; }
.apk-upload span { color: #82909d; font-size: .72rem; }
.upload-symbol { display: grid; width: 1.9rem; height: 1.9rem; margin: 0 auto; place-items: center; color: #fff; font-size: 1rem; font-weight: 800; background: #246fb8; border-radius: .45rem; box-shadow: 0 6px 14px rgba(36,111,184,.2); }
.apps-table-section { overflow: hidden; }
.section-title { display: flex; align-items: center; justify-content: space-between; padding: 1.15rem 1.3rem; border-bottom: 1px solid #e6ebef; }
.section-title .eyebrow { margin-bottom: .25rem; }
.section-title h2 { margin: 0; color: #173047; font-size: 1.08rem; letter-spacing: -.025em; }
.section-title > span { color: #7a8996; font-size: .73rem; font-weight: 700; }
.asset-toolbar { display: grid; grid-template-columns: minmax(18rem, 1fr) 12rem; gap: .65rem; padding: .85rem 1.1rem; background: #f8fafb; border-bottom: 1px solid #e8edf0; }
.search-symbol { color: #55738a; font-size: 1.05rem; }
.apps-table { --el-table-header-bg-color: #f7f9fa; --el-table-row-hover-bg-color: #f1f6f9; }
.apps-table :deep(th.el-table__cell) { color: #718291; font-size: .7rem; font-weight: 800; letter-spacing: .035em; }
.apps-table :deep(.el-table__cell) { padding: .72rem 0; }
.app-identity { display: flex; align-items: center; gap: .72rem; min-width: 0; }
.app-avatar { display: grid; flex: 0 0 auto; width: 2.15rem; height: 2.15rem; place-items: center; color: #1767a5; font-size: .86rem; font-weight: 850; background: #e7f2fc; border: 1px solid #c9dff1; border-radius: .62rem .62rem .62rem .2rem; box-shadow: 0 4px 10px rgba(52,111,154,.1); }
.app-avatar.tone-blue { color: #1767a5; background: #e7f2fc; border-color: #c9dff1; }
.app-avatar.tone-cyan { color: #087e94; background: #e5f7fa; border-color: #c2e8ed; }
.app-avatar.tone-teal { color: #287a69; background: #e8f6f2; border-color: #cae7de; }
.app-avatar.tone-sky { color: #316fb4; background: #edf3ff; border-color: #d3e0f6; }
.app-identity > span:last-child, .package-copy { display: grid; min-width: 0; gap: .16rem; }
.app-identity strong { overflow: hidden; color: #263e51; font-size: .84rem; text-overflow: ellipsis; white-space: nowrap; }
.app-identity small, .package-copy small { overflow: hidden; color: #84919c; font-size: .67rem; text-overflow: ellipsis; white-space: nowrap; }
.package-copy span { overflow: hidden; color: #526778; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .72rem; text-overflow: ellipsis; white-space: nowrap; }
.static-badges { display: flex; flex-wrap: wrap; gap: .25rem; }
.static-badges span { padding: .18rem .34rem; color: #476a82; font-size: .63rem; font-weight: 700; background: #edf3f6; border-radius: .3rem; }
.muted-state { color: #97a2ac; font-size: .69rem; }
.permission-count { color: #314e63; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: .82rem; font-weight: 750; font-variant-numeric: tabular-nums; }
.table-pagination { display: flex; align-items: center; justify-content: space-between; padding: .8rem 1.1rem; color: #84919c; font-size: .7rem; border-top: 1px solid #e8edf0; }
.apps-empty { display: grid; justify-items: center; gap: .5rem; padding: 4rem 1rem; color: #7b8995; font-size: .8rem; }
.apps-empty strong { color: #334b5d; font-size: .94rem; }
.empty-mark { display: grid; width: 2.4rem; height: 2.4rem; place-items: center; color: #246fb8; font-size: 1.25rem; background: #e8f1f7; border-radius: .58rem; }
.drawer-title { display: flex; align-items: center; gap: .7rem; }
.drawer-title div { display: grid; gap: .15rem; }
.drawer-title strong { color: #173047; font-size: 1rem; }
.drawer-title small { color: #7c8a96; font-size: .68rem; }
.static-detail { display: grid; gap: 1.4rem; }
.detail-overview { display: grid; grid-template-columns: repeat(3, 1fr); gap: .55rem; }
.detail-overview div { display: grid; gap: .25rem; padding: .8rem; background: #f1f5f7; border-radius: .58rem; }
.detail-overview span { color: #718391; font-size: .67rem; }
.detail-overview strong { color: #173047; font-size: 1.2rem; font-variant-numeric: tabular-nums; }
.detail-section h3 { margin: 0 0 .7rem; color: #284154; font-size: .79rem; letter-spacing: .04em; }
.detail-section dl { display: grid; gap: .55rem; margin: 0; }
.detail-section dl div { display: grid; grid-template-columns: 5rem 1fr; gap: .6rem; }
.detail-section dt { color: #82909b; font-size: .69rem; }
.detail-section dd { min-width: 0; margin: 0; overflow-wrap: anywhere; color: #465d6e; font-size: .72rem; }
.hash-copy { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.detail-chip-list, .domain-list { display: flex; flex-wrap: wrap; gap: .4rem; }
.detail-chip-list span, .domain-list code { padding: .3rem .45rem; color: #46667d; font-size: .68rem; background: #eef3f6; border: 1px solid #e0e8ed; border-radius: .35rem; }
.indicator-list { display: grid; gap: .45rem; }
.indicator-list article { display: flex; align-items: flex-start; gap: .55rem; padding: .58rem .65rem; background: #f8fafb; border: 1px solid #e8edf0; border-radius: .45rem; }
.indicator-list i { flex: 0 0 auto; width: .48rem; height: .48rem; margin-top: .22rem; background: #7b92a3; border-radius: 50%; }
.indicator-list i.high { background: #bd4b4f; }.indicator-list i.medium { background: #b97820; }.indicator-list i.low { background: #347c61; }
.indicator-list div { display: grid; gap: .1rem; }
.indicator-list strong { color: #354f62; font-size: .7rem; }.indicator-list span { color: #71818e; font-size: .68rem; line-height: 1.45; }
.detail-empty, .static-unavailable p { margin: 0; color: #7c8a95; font-size: .72rem; line-height: 1.6; }
.static-unavailable { padding: .9rem; color: #79591e; background: #fff8e8; border: 1px solid #efdfb8; border-radius: .58rem; }
.static-unavailable strong { font-size: .76rem; }.static-unavailable p { margin-top: .3rem; color: #8b744a; }
.dialog-note { margin: 0 0 1rem; color: #758492; font-size: .82rem; line-height: 1.65; }
.apps-table :deep(.action-cell .cell) { display: flex; align-items: center; gap: .25rem; min-height: 2.45rem; padding-inline: .45rem; white-space: nowrap; }
.apps-table :deep(.action-cell .el-button), .apps-table :deep(.action-cell .el-button + .el-button) { flex: 0 0 auto; margin-left: 0; }
@media (max-width: 800px) {
  .library-stats { width: 100%; justify-content: space-between; }
  .upload-panel { grid-template-columns: 1fr; gap: 1.35rem; padding: 1.25rem; }
  .upload-action, .asset-toolbar { grid-template-columns: 1fr; }
  .upload-buttons :deep(.el-button) { width: 100%; }
}
@media (max-width: 560px) {
  .library-stats span { display: none; }
  .library-stats a { width: 100%; padding: 0; border: 0; text-align: center; }
  .detail-overview { grid-template-columns: 1fr; }
}
</style>

<style scoped>
/* Library text is used for repeated review, so it is one step larger than
   the compact task list while preserving the existing layout proportions. */
.library-heading h1 { font-size: clamp(2rem, 3.2vw, 2.75rem); }
.library-heading p:not(.eyebrow) { font-size: 1rem; }
.library-stats { font-size: .82rem; }.library-stats b { font-size: 1.1rem; }.library-refresh, .library-stats a { font-size: .78rem; }
.upload-kicker { font-size: .76rem; }.upload-copy h2 { font-size: 1.42rem; }.upload-copy p { font-size: .96rem; }.upload-assurance { font-size: .78rem; }
.apk-upload strong { font-size: .94rem; }.apk-upload span { font-size: .82rem; }
.section-title h2 { font-size: 1.24rem; }.section-title > span { font-size: .82rem; }
.asset-toolbar :deep(.el-input__inner), .asset-toolbar :deep(.el-select__placeholder), .asset-toolbar :deep(.el-select__selected-item) { font-size: .96rem; }
.apps-table :deep(th.el-table__cell) { font-size: .82rem; }.apps-table :deep(td.el-table__cell) { font-size: .9rem; }.apps-table :deep(td .cell) { line-height: 1.45; }
.app-identity strong { font-size: .98rem; }.app-identity small, .package-copy small { font-size: .78rem; }.package-copy span { font-size: .82rem; }
.static-badges span { font-size: .72rem; }.muted-state { font-size: .78rem; }.permission-count { font-size: .9rem; }.apps-table :deep(.el-button) { font-size: .82rem; }
.table-pagination { font-size: .8rem; }
@media (max-width: 800px) { .library-heading p:not(.eyebrow) { font-size: .95rem; }.upload-copy p { font-size: .9rem; } }
</style>

<style scoped>
/* The detail drawer is a reading surface too; keep labels and values
   distinguishable without widening the drawer. */
.drawer-title strong { font-size: 1.1rem; }.drawer-title small { font-size: .78rem; }
.detail-overview span { font-size: .76rem; }.detail-overview strong { font-size: 1.3rem; }
.detail-section h3 { font-size: .88rem; }.detail-section dt { font-size: .77rem; }.detail-section dd { font-size: .81rem; }
.detail-chip-list span, .domain-list code { font-size: .76rem; }.indicator-list strong { font-size: .8rem; }.indicator-list span { font-size: .77rem; }
.detail-empty, .static-unavailable p { font-size: .8rem; }.static-unavailable strong { font-size: .84rem; }.dialog-note { font-size: .9rem; }
</style>
