<script setup lang="ts">
import { ArrowRight, Clapperboard } from 'lucide-vue-next'
import AppIconTile from '@/components/AppIconTile.vue'
</script>

<template>
  <main class="route-placeholder-page">
    <div class="route-placeholder-content">
      <AppIconTile class="route-placeholder-icon" size="xl"><Clapperboard :size="24" /></AppIconTile>
      <p class="route-placeholder-kicker">灵思短剧</p>
      <h1>欢迎回来</h1>
      <p>从一个项目开始，把小说内容逐步制作成短剧。</p>
      <RouterLink to="/create/short-drama" class="route-placeholder-action">
        开始创作
        <ArrowRight :size="16" />
      </RouterLink>
    </div>
  </main>
</template>
