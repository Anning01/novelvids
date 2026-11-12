import { createRouter, createWebHashHistory } from 'vue-router'
import { useAuthStore } from './features/auth/authStore'
import { resolveAuthGuard } from './features/auth/routeGuard'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    ...(['usage', 'keys', 'models', 'docs'] as const).map(section => ({
      path: '/platform/' + section, component: () => import('./pages/PlatformConsolePage.vue'), props: {section},
      meta: {platformOnly: true, public: ['models', 'docs'].includes(section)},
    })),
    { path: '/login', name: 'login', component: () => import('./pages/LoginPage.vue'), meta: { public: true, fullscreen: true } },
    { path: '/mcp/connect/:code', name: 'local-mcp-connect', component: () => import('./pages/LocalMcpConnectPage.vue'), meta: {fullscreen: true} },
    { path: '/invite/:token', name: 'invite', component: () => import('./pages/InvitePage.vue'), meta: { public: true, fullscreen: true } },
    { path: '/', component: () => import('./pages/HomePage.vue') },
    { path: '/create/clip/:projectId', name: 'clip-studio', component: () => import('./pages/ClipStudioPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama', component: () => import('./pages/ShortDramaPage.vue') },
    { path: '/create/remake', name: 'remake-workshop', component: () => import('./pages/RemakeWorkshopPage.vue') },
    { path: '/create/remake/:projectId/progress', name: 'remake-progress', component: () => import('./pages/RemakeProgressPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/agent', redirect: '/create/short-drama' },
    { path: '/create/short-drama/agent/:projectId', name: 'short-drama-agent', component: () => import('./pages/ShortDramaAgentPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/manual/:projectId', name: 'short-drama-manual', component: () => import('./pages/ShortDramaManualPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/storyboard/:projectId', name: 'short-drama-storyboard', component: () => import('./pages/ShortDramaStoryboardPage.vue'), meta: { fullscreen: true } },
    { path: '/create/short-drama/video/:projectId', name: 'short-drama-video', component: () => import('./pages/ShortDramaVideoPage.vue'), meta: { fullscreen: true } },
    { path: '/finished-library', component: () => import('./pages/FinishedEpisodesPage.vue'), beforeEnter: to => {
      if (to.query.project && to.query.chapter) {
        const { project, ...query } = to.query
        return { name: 'work-detail', params: { projectId: String(project) }, query }
      }
      return true
    } },
    { path: '/finished-library/:projectId', name: 'work-detail', component: () => import('./pages/PortfolioWorkPage.vue') },
    { path: '/works/:projectId', name: 'public-work', component: () => import('./pages/PortfolioWorkPage.vue'), meta: { public: true, fullscreen: true } },
    { path: '/projects', component: () => import('./pages/DashboardPage.vue') },
    { path: '/profile', name: 'profile', component: () => import('./pages/ProfilePage.vue') },
    { path: '/novel/:id', component: () => import('./pages/NovelPage.vue') },
    { path: '/novel/:novelId/chapter/:chapterId/step/:stepId', component: () => import('./pages/WorkflowPage.vue') },
    { path: '/resource-library', component: () => import('./pages/ResourceLibraryPage.vue') },
    { path: '/assets', component: () => import('./pages/VideosPage.vue'), beforeEnter: to => to.query.scope === 'public' ? { path: '/resource-library', query: { kind: to.query.category === 'audio' ? 'voice' : 'character' } } : true },
    { path: '/settings', component: () => import('./pages/ConfigPage.vue'), meta: { roles: ['admin'], superOnly: true } },
    { path: '/billing', component: () => import('./pages/BillingPage.vue'), meta: { roles: ['admin', 'creator'] } },
    { path: '/members', name: 'members', component: () => import('./pages/MembersPage.vue'), meta: { roles: ['admin'] } },
    { path: '/teams', name: 'teams', component: () => import('./pages/TeamsPage.vue'), meta: { roles: ['admin'], superOnly: true } },
    { path: '/users', name: 'users', component: () => import('./pages/UsersPage.vue'), meta: { roles: ['admin'], superOnly: true } },
    { path: '/orders', name: 'orders', component: () => import('./pages/OrdersPage.vue') },
    { path: '/videos', redirect: '/assets' },
    { path: '/config', redirect: '/settings' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) await auth.bootstrap()
  if (auth.deploymentRole === 'platform') {
    if (!to.meta.platformOnly && !['/login','/profile','/projects','/billing','/orders','/teams','/members','/users','/settings'].includes(to.path) && to.name !== 'invite') {
      return auth.canAccessBilling ? '/platform/usage' : '/platform/models'
    }
    if (['/platform/usage','/platform/keys'].includes(to.path) && auth.isLoggedIn && !auth.canAccessBilling) return '/platform/models'
  } else if (to.meta.platformOnly) return '/'
  const decision = resolveAuthGuard(to, auth)
  if (decision.redirect === '/login' && to.name === 'local-mcp-connect') {
    return {path: '/login', query: {redirect: to.fullPath}}
  }
  if (decision.redirect) return decision.redirect
  return true
})

export default router
