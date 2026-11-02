import { createRouter, createWebHistory } from 'vue-router'
import DetectHome from './views/DetectHome.vue'
import TaskProgress from './views/TaskProgress.vue'
import ReportDetail from './views/ReportDetail.vue'

// Keep the scroll position for the two primary workbench pages in memory. This
// complements KeepAlive: component state (filters, pagination, expanded cards)
// stays mounted, while the page-level scroll position is restored on return.
const preservedScroll = new Map()

function captureScroll() {
  if (typeof window === 'undefined') return { left: 0, top: 0 }
  return { left: window.scrollX, top: window.scrollY }
}

const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to, _from, savedPosition) {
    if (savedPosition) return { ...savedPosition, behavior: 'auto' }

    const preserved = preservedScroll.get(to.fullPath)
    if (preserved) return { ...preserved, behavior: 'auto' }

    return { top: 0, behavior: 'auto' }
  },
  routes: [
    { path: '/', component: DetectHome },
    { path: '/tasks', component: TaskProgress },
    { path: '/report/:taskId', component: ReportDetail },
  ],
})

router.beforeEach((_to, from) => {
  if (from.path === '/' || from.path === '/tasks') {
    preservedScroll.set(from.fullPath, captureScroll())
  }
})

export default router
