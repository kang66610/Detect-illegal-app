<template>
  <el-dialog v-model="visible" title="新建检测" width="min(92vw, 520px)" align-center destroy-on-close>
    <div class="dialog-intro">
      <span>01</span>
      <div><strong>选择检测对象</strong><p>从已上传且解析成功的 App 中选择一个样本，任务默认执行深度检测。</p></div>
    </div>

    <el-form label-position="top" class="new-detection-form">
      <el-form-item label="已上传 App">
        <el-select v-model="form.apkId" filterable :loading="loading" :disabled="loading || creating" placeholder="搜索应用名称或包名" style="width: 100%">
          <el-option v-for="apk in availableApks" :key="apk.id" :label="`${apk.app_name || '未命名应用'} · ${apk.package_name || apk.filename}`" :value="apk.id" />
        </el-select>
      </el-form-item>

      <article v-if="selectedApk" class="selected-app">
        <span>{{ appInitial(selectedApk) }}</span>
        <div><strong>{{ selectedApk.app_name || '未命名应用' }}</strong><small>{{ selectedApk.package_name || selectedApk.filename }}</small></div>
        <em>已解析</em>
      </article>
      <div v-else-if="loadError" class="no-apps no-apps-error" role="alert">
        <strong>应用列表加载失败</strong>
        <span>{{ loadError }}</span>
        <button type="button" @click="loadApps">重试</button>
      </div>
      <div v-else-if="!loading && !availableApks.length" class="no-apps">
        <strong>暂无可检测的 App</strong>
        <span>请先在应用库上传并成功解析 APK。</span>
      </div>

      <el-form-item label="所属行业"><el-select v-model="form.industry" style="width: 100%"><el-option v-for="industry in industries" :key="industry" :label="industry" :value="industry" /></el-select></el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="creating" :disabled="!form.apkId" @click="createTask">创建并开始</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import api from '../api'

const router = useRouter()
const visible = ref(false)
const loading = ref(false)
const loadError = ref('')
const creating = ref(false)
const apks = ref([])
const industries = ['通用', '金融理财', '电商购物', '社交通讯', '工具', '医疗健康', '教育', '出行']
const form = ref({ apkId: null, industry: '通用' })
const availableApks = computed(() => apks.value.filter(apk => apk.parse_status === 'success'))
const selectedApk = computed(() => availableApks.value.find(apk => apk.id === form.value.apkId) || null)

function appInitial(apk) { return String(apk?.app_name || apk?.filename || 'A').trim().slice(0, 1).toUpperCase() }
async function loadApps() {
  loading.value = true
  loadError.value = ''
  try {
    const data = (await api.get('/apks')).data
    apks.value = Array.isArray(data) ? data : []
  } catch (error) {
    loadError.value = error.response?.data?.detail || '请检查服务是否运行'
  } finally {
    loading.value = false
  }
}
async function open() {
  visible.value = true
  form.value = { apkId: null, industry: '通用' }
  await loadApps()
}
async function createTask() {
  if (!form.value.apkId) return
  creating.value = true
  try {
    await api.post('/tasks', { apk_id: form.value.apkId, industry: form.value.industry, mode: 'deep' })
    visible.value = false
    ElMessage.success('检测任务已创建')
    router.push('/tasks')
  } catch (error) { ElMessage.error(error.response?.data?.detail || '任务创建失败') }
  finally { creating.value = false }
}

defineExpose({ open })
</script>

<style scoped>
.dialog-intro { display: flex; align-items: center; gap: .8rem; margin-bottom: 1.15rem; padding: .9rem 1rem; background: linear-gradient(145deg, rgba(232,245,255,.78), rgba(255,255,255,.5)); border: 1px solid rgba(255,255,255,.88); border-radius: 1.15rem; box-shadow: 0 12px 30px rgba(54,97,128,.08), inset 0 1px 0 #fff; }
.dialog-intro > span { display: grid; width: 2.15rem; height: 2.15rem; place-items: center; color: #fff; font-size: .7rem; font-weight: 850; background: linear-gradient(145deg, #358bd2, #1d6cb3); border: 1px solid rgba(255,255,255,.38); border-radius: .72rem .72rem .72rem .3rem; box-shadow: 0 9px 20px rgba(38,116,178,.22), inset 0 1px 0 rgba(255,255,255,.4); }
.dialog-intro div { display: grid; gap: .14rem; }.dialog-intro strong { color: #21425d; font-size: .82rem; }.dialog-intro p { margin: 0; color: #718492; font-size: .7rem; }
.selected-app { display: flex; align-items: center; gap: .7rem; margin: -.25rem 0 1rem; padding: .78rem .85rem; background: rgba(255,255,255,.5); border: 1px solid rgba(255,255,255,.86); border-radius: 1rem; box-shadow: 0 10px 28px rgba(50,91,123,.07), inset 0 1px 0 #fff; }
.selected-app > span { display: grid; flex: 0 0 auto; width: 2.1rem; height: 2.1rem; place-items: center; color: #1767a5; font-size: .8rem; font-weight: 850; background: rgba(224,241,254,.78); border: 1px solid rgba(255,255,255,.86); border-radius: .72rem .72rem .72rem .28rem; box-shadow: inset 0 1px 0 #fff; }
.selected-app div { display: grid; min-width: 0; gap: .12rem; }.selected-app strong, .selected-app small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }.selected-app strong { color: #263f54; font-size: .8rem; }.selected-app small { color: #7c8c98; font-size: .67rem; }
.selected-app em { margin-left: auto; padding: .24rem .48rem; color: #287a59; font-size: .64rem; font-style: normal; font-weight: 750; background: rgba(226,246,234,.78); border-radius: .65rem; box-shadow: inset 0 1px 0 #fff; }
.no-apps { display: grid; gap: .18rem; margin: -.25rem 0 1rem; padding: .95rem; color: #718492; font-size: .7rem; background: rgba(255,255,255,.42); border: 1px solid rgba(255,255,255,.82); border-radius: 1rem; box-shadow: inset 0 1px 0 #fff; }.no-apps strong { color: #425b6e; font-size: .78rem; }
.no-apps-error { color: #9a5b1a; background: #fff8e8; border-color: #f0dfb9; }.no-apps-error strong { color: #8d5b1b; }.no-apps-error button { justify-self: start; margin-top: .35rem; padding: .3rem .55rem; color: #246fb8; font: inherit; font-size: .7rem; font-weight: 750; background: #fff; border: 1px solid #cfe0ee; border-radius: .42rem; cursor: pointer; }
</style>
