import { createRouter, createWebHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  // Public routes
  {
    path: '/',
    name: 'home',
    component: () => import('@/views/HomeView.vue'),
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
  },
  {
    path: '/register',
    name: 'register',
    component: () => import('@/views/RegisterView.vue'),
  },

  // Dashboard (项目管理大厅)
  {
    path: '/dashboard',
    name: 'dashboard',
    component: () => import('@/views/DashboardView.vue'),
    meta: { requiresAuth: true },
  },

  // Legacy novels route - redirect to dashboard
  {
    path: '/novels',
    redirect: '/dashboard',
  },

  // Editor Layout (书籍工作台)
  {
    path: '/editor/:novelId',
    component: () => import('@/layouts/EditorLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      // 默认重定向到资产库
      {
        path: '',
        redirect: { name: 'editor-assets' },
      },

      // 全局资产库
      {
        path: 'assets',
        name: 'editor-assets',
        component: () => import('@/views/editor/AssetsView.vue'),
      },

      // 章节工作流
      {
        path: 'chapter/:chapterId',
        component: () => import('@/layouts/ChapterLayout.vue'),
        children: [
          {
            path: '',
            redirect: { name: 'chapter-extraction' },
          },
          {
            path: 'extraction',
            name: 'chapter-extraction',
            component: () => import('@/views/editor/ExtractionView.vue'),
          },
          {
            path: 'asset-review',
            name: 'chapter-asset-review',
            component: () => import('@/views/editor/AssetReviewView.vue'),
          },
          {
            path: 'storyboard',
            name: 'chapter-storyboard',
            component: () => import('@/views/editor/StoryboardView.vue'),
          },
          {
            path: 'studio',
            name: 'chapter-studio',
            component: () => import('@/views/editor/StudioView.vue'),
          },
        ],
      },
    ],
  },

  // Settings
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
    meta: { requiresAuth: true },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) {
    next({ name: 'login' })
  } else {
    next()
  }
})

export default router
