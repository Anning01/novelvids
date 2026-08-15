import { createRouter, createWebHashHistory } from 'vue-router'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: () => import('./pages/HomePage.vue') },
    { path: '/create/short-drama', component: () => import('./pages/ShortDramaPage.vue') },
    { path: '/create/short-drama/agent', redirect: '/create/short-drama' },
    { path: '/create/short-drama/agent/:projectId', name: 'short-drama-agent', component: () => import('./pages/ShortDramaAgentPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/manual/:projectId', name: 'short-drama-manual', component: () => import('./pages/ShortDramaManualPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/storyboard/:projectId', name: 'short-drama-storyboard', component: () => import('./pages/ShortDramaStoryboardPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/video/:projectId', name: 'short-drama-video', component: () => import('./pages/ShortDramaVideoPage.vue'), meta: { fullscreen: true } },
    { path: '/projects', component: () => import('./pages/DashboardPage.vue') },
    { path: '/novel/:id', component: () => import('./pages/NovelPage.vue') },
    { path: '/novel/:novelId/chapter/:chapterId/step/:stepId', component: () => import('./pages/WorkflowPage.vue') },
    { path: '/assets', component: () => import('./pages/VideosPage.vue') },
    { path: '/settings', component: () => import('./pages/ConfigPage.vue') },
    { path: '/videos', redirect: '/assets' },
    { path: '/config', redirect: '/settings' },
  ],
})
