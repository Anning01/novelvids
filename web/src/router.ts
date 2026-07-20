import { createRouter, createWebHashHistory } from 'vue-router'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: () => import('./pages/DashboardPage.vue') },
    { path: '/novel/:id', component: () => import('./pages/NovelPage.vue') },
    { path: '/novel/:novelId/chapter/:chapterId/step/:stepId', component: () => import('./pages/WorkflowPage.vue') },
    { path: '/videos', component: () => import('./pages/VideosPage.vue') },
    { path: '/config', component: () => import('./pages/ConfigPage.vue') },
  ],
})
