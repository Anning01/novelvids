<script setup lang="ts">
import { BookOpen, ChevronLeft, ChevronRight, MonitorPlay, Settings, Sparkles } from 'lucide-vue-next'
import { ref } from 'vue'
import { useRoute } from 'vue-router'
import { notice } from '@/shared/notice'
const route = useRoute(); const collapsed = ref(false)
const items = [
  { path: '/', label: '项目管理', icon: BookOpen, active: () => route.path === '/' || route.path.startsWith('/novel') },
  { path: '/videos', label: '视频库', icon: MonitorPlay, active: () => route.path.startsWith('/videos') },
  { path: '/config', label: '模型配置', icon: Settings, active: () => route.path.startsWith('/config') },
]
</script>
<template>
  <div class="app-shell">
    <aside class="app-sidebar" :class="{ 'is-collapsed': collapsed }">
      <div class="app-brand"><span><Sparkles :size="18" /></span><div v-if="!collapsed"><strong>猫影</strong><small>NOVEL STUDIO</small></div></div>
      <nav><p v-if="!collapsed">创作空间</p><RouterLink v-for="item in items" :key="item.path" :to="item.path" class="app-nav-item" :class="{ 'is-active': item.active() }"><component :is="item.icon" :size="18" /><span v-if="!collapsed">{{ item.label }}</span></RouterLink></nav>
      <button class="sidebar-toggle" type="button" :aria-label="collapsed ? '展开侧边栏' : '收起侧边栏'" @click="collapsed = !collapsed"><ChevronRight v-if="collapsed" :size="16" /><ChevronLeft v-else :size="16" /></button>
    </aside>
    <section class="app-content"><RouterView /></section>
    <div class="notice-stack" aria-live="polite"><div v-for="item in notice.state.notices" :key="item.id" class="notice" :class="`is-${item.tone}`">{{ item.message }}</div></div>
  </div>
</template>
