/**
 * Vue Router 路由配置
 */
import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    redirect: '/config',
  },
  {
    path: '/config',
    name: 'Config',
    component: () => import('./views/ConfigView.vue'),
    meta: { title: '配置管理' },
  },
  {
    path: '/mock',
    name: 'MockData',
    component: () => import('./views/MockDataView.vue'),
    meta: { title: 'Mock数据' },
  },
  {
    path: '/collect',
    name: 'Collect',
    component: () => import('./views/CollectView.vue'),
    meta: { title: '数据采集' },
  },
  {
    path: '/analyze',
    name: 'Analyze',
    component: () => import('./views/AnalyzeView.vue'),
    meta: { title: '评估分析' },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 路由守卫：更新页面标题
router.beforeEach((to, from, next) => {
  document.title = to.meta.title 
    ? `${to.meta.title} - SESORA` 
    : 'SESORA 云原生成熟度评估'
  next()
})

export default router
