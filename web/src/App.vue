<script setup lang="ts">
import { Clapperboard, FolderKanban, Images, Settings, Sparkles } from 'lucide-vue-next'
import { useRoute } from 'vue-router'
import { computed } from 'vue'
import { notice } from '@/shared/notice'
import AppConfirmDialog from '@/components/AppConfirmDialog.vue'
import AppThemeToggle from '@/components/AppThemeToggle.vue'
import { useAppThemeController } from '@/shared/appTheme'
import { isWorkflowThemeSurface } from '@/shared/themeScope'

const route = useRoute()
const { resolvedTheme } = useAppThemeController()
const isFullscreen = computed(() => route.meta.fullscreen === true)
const isWorkflowSurface = computed(() => isWorkflowThemeSurface({
  name: route.name,
  path: route.path,
  view: route.query.view,
}))
const confirmDialogDark = computed(() => isWorkflowSurface.value || resolvedTheme.value === 'dark')
const creationItems = [
  { path: '/create/short-drama', label: '短剧制作', icon: Clapperboard, active: () => route.path.startsWith('/create/short-drama') },
]
const personalItems = [
  { path: '/projects', label: '项目', icon: FolderKanban, active: () => route.path === '/projects' || route.path.startsWith('/novel') },
  { path: '/assets', label: '资产', icon: Images, active: () => route.path.startsWith('/assets') },
  { path: '/settings', label: '设置', icon: Settings, active: () => route.path.startsWith('/settings') },
]
</script>
<template>
  <div class="app-shell" :class="{ 'is-workflow-surface': isWorkflowSurface }">
    <aside v-if="!isFullscreen" class="app-sidebar">
      <RouterLink to="/" class="app-brand" aria-label="猫影首页">
        <img src="/logo.png" alt="" />
        <span>
          <strong>灵思</strong>
          <small>NOVEL STUDIO</small>
        </span>
      </RouterLink>
      <nav aria-label="主导航">
        <RouterLink to="/" class="app-nav-item app-home-item" :class="{ 'is-active': route.path === '/' }">
          <Sparkles :size="18" />
          <span>首页</span>
        </RouterLink>

        <section class="app-nav-group" aria-labelledby="creation-nav-title">
          <h2 id="creation-nav-title">创作</h2>
          <RouterLink v-for="item in creationItems" :key="item.path" :to="item.path" class="app-nav-item" :class="{ 'is-active': item.active() }">
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>

        <section class="app-nav-group" aria-labelledby="personal-nav-title">
          <h2 id="personal-nav-title">我的</h2>
          <RouterLink v-for="item in personalItems" :key="item.path" :to="item.path" class="app-nav-item" :class="{ 'is-active': item.active() }">
            <component :is="item.icon" :size="18" />
            <span>{{ item.label }}</span>
          </RouterLink>
        </section>
      </nav>
      <AppThemeToggle v-if="!isWorkflowSurface" placement="sidebar" />
    </aside>
    <section class="app-content" :class="{ 'is-fullscreen': isFullscreen }"><RouterView /></section>
    <AppThemeToggle v-if="isFullscreen && !isWorkflowSurface" />
    <AppConfirmDialog :dark="confirmDialogDark" />
    <div class="notice-stack" aria-live="polite"><div v-for="item in notice.state.notices" :key="item.id" class="notice" :class="`is-${item.tone}`">{{ item.message }}</div></div>
  </div>
</template>
