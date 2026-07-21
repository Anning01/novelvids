<script setup lang="ts">
import { ArrowRight, Clapperboard } from 'lucide-vue-next'
</script>

<template>
  <main class="route-placeholder-page">
    <div class="route-placeholder-content">
      <span class="route-placeholder-icon"><Clapperboard :size="24" /></span>
      <p class="route-placeholder-kicker">猫影短剧</p>
      <h1>欢迎回来</h1>
      <p>从一个项目开始，把小说内容逐步制作成短剧。</p>
      <RouterLink to="/create/short-drama" class="route-placeholder-action">
        开始创作
        <ArrowRight :size="16" />
      </RouterLink>
    </div>
  </main>
</template>
