import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from './features/auth/authStore'
import { resolveAuthGuard } from './features/auth/routeGuard'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/login', name: 'login', component: () => import('./pages/LoginPage.vue'), meta: { public: true, fullscreen: true } },
    { path: '/invite/:token', name: 'invite', component: () => import('./pages/InvitePage.vue'), meta: { public: true, fullscreen: true } },
    { path: '/', component: () => import('./pages/HomePage.vue') },
    { path: '/create/short-drama', component: () => import('./pages/ShortDramaPage.vue') },
    { path: '/create/remake', name: 'remake-workshop', component: () => import('./pages/RemakeWorkshopPage.vue') },
    { path: '/create/remake/:projectId/progress', name: 'remake-progress', component: () => import('./pages/RemakeProgressPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/agent', redirect: '/create/short-drama' },
    { path: '/create/short-drama/agent/:projectId', name: 'short-drama-agent', component: () => import('./pages/ShortDramaAgentPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/manual/:projectId', name: 'short-drama-manual', component: () => import('./pages/ShortDramaManualPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/storyboard/:projectId', name: 'short-drama-storyboard', component: () => import('./pages/ShortDramaStoryboardPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/video/:projectId', name: 'short-drama-video', component: () => import('./pages/ShortDramaVideoPage.vue'), meta: { fullscreen: true } },
    { path: '/projects', component: () => import('./pages/DashboardPage.vue') },
    { path: '/profile', name: 'profile', component: () => import('./pages/ProfilePage.vue') },
    { path: '/novel/:id', component: () => import('./pages/NovelPage.vue') },
    { path: '/novel/:novelId/chapter/:chapterId/step/:stepId', component: () => import('./pages/WorkflowPage.vue') },
    { path: '/assets', component: () => import('./pages/VideosPage.vue') },
    { path: '/settings', component: () => import('./pages/ConfigPage.vue'), meta: { roles: ['admin'] } },
    { path: '/billing', component: () => import('./pages/BillingPage.vue'), meta: { roles: ['admin', 'creator'] } },
    { path: '/members', name: 'members', component: () => import('./pages/MembersPage.vue'), meta: { roles: ['admin'] } },
    { path: '/teams', name: 'teams', component: () => import('./pages/TeamsPage.vue'), meta: { roles: ['admin'], superOnly: true } },
    { path: '/users', name: 'users', component: () => import('./pages/UsersPage.vue'), meta: { roles: ['admin'], superOnly: true } },
    { path: '/videos', redirect: '/assets' },
    { path: '/config', redirect: '/settings' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) await auth.bootstrap()
  const decision = resolveAuthGuard(to, auth)
  if (decision.redirect) return decision.redirect
  return true
})

export default router
