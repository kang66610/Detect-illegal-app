<template>
  <div class="app-shell">
    <a class="skip-link" href="#main-content">跳到主要内容</a>
    <header class="topbar" :class="{ 'is-condensed': navigationCondensed }">
      <RouterLink class="brand" to="/" aria-label="返回检测首页">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32"><path d="M8 10.5 16 6l8 4.5v8.8L16 26l-8-6.7Z"/><circle cx="16" cy="12.2" r="2.2"/><circle cx="12.3" cy="18" r="1.7"/><circle cx="19.7" cy="18" r="1.7"/><path d="m14.2 13.7-1.1 2.7m4.7-2.7 1.1 2.7m-4.9 2h4"/></svg>
        </span>
        <span class="brand-copy"><strong>隐私合规检测</strong><small>PRIVACY INTELLIGENCE</small></span>
      </RouterLink>
      <nav class="main-nav" aria-label="主导航">
        <RouterLink to="/">应用库</RouterLink>
        <RouterLink to="/tasks">检测任务</RouterLink>
      </nav>
      <button class="topbar-cta" type="button" @click="openNewDetection">＋ 新建检测</button>
    </header>
    <main id="main-content" class="page-main">
      <router-view v-slot="{ Component, route }">
        <Transition name="route-shift" mode="out-in">
          <KeepAlive include="DetectHome,TaskProgress">
            <component :is="Component" :key="route.path" />
          </KeepAlive>
        </Transition>
      </router-view>
    </main>
    <NewDetectionDialog ref="newDetectionDialog" />
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, provide, ref } from 'vue'
import NewDetectionDialog from './components/NewDetectionDialog.vue'
import { isNavigationCondensed } from './utils/uiMotion'

const newDetectionDialog = ref(null)
const navigationCondensed = ref(false)
let navigationFrame = null
function openNewDetection() { newDetectionDialog.value?.open() }
function syncNavigationState() {
  cancelAnimationFrame(navigationFrame)
  navigationFrame = requestAnimationFrame(() => {
    navigationCondensed.value = isNavigationCondensed(window.scrollY)
  })
}
onMounted(() => {
  syncNavigationState()
  window.addEventListener('scroll', syncNavigationState, { passive: true })
})
onUnmounted(() => {
  window.removeEventListener('scroll', syncNavigationState)
  cancelAnimationFrame(navigationFrame)
})
provide('openNewDetection', openNewDetection)
</script>
