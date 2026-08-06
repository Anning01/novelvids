<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  icon: Component
  previewLabel?: string
  previewUrl?: string
  title: string
  typeLabel: string
}>()
</script>

<template>
  <div
    class="workbench-asset-default-image"
    role="img"
    :aria-label="previewUrl ? `${title}${previewLabel || '参考图片'}预览` : `${title}默认图片`"
  >
    <template v-if="previewUrl">
      <img class="workbench-asset-default-image__preview-backdrop" :src="previewUrl" alt="" aria-hidden="true">
      <img class="workbench-asset-default-image__preview" :src="previewUrl" :alt="`${title}${previewLabel || '参考图片'}`">
    </template>
    <svg v-else viewBox="0 0 800 450" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      <defs>
        <linearGradient id="asset-default-surface" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#26221f" />
          <stop offset="0.52" stop-color="#1a1817" />
          <stop offset="1" stop-color="#121110" />
        </linearGradient>
        <radialGradient id="asset-default-glow" cx="0.22" cy="0.18" r="0.82">
          <stop offset="0" stop-color="#8f7ccb" stop-opacity="0.26" />
          <stop offset="0.5" stop-color="#655578" stop-opacity="0.08" />
          <stop offset="1" stop-color="#171513" stop-opacity="0" />
        </radialGradient>
        <linearGradient id="asset-default-ridge" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#554a5f" stop-opacity="0.68" />
          <stop offset="1" stop-color="#242020" stop-opacity="0.2" />
        </linearGradient>
      </defs>
      <rect width="800" height="450" fill="url(#asset-default-surface)" />
      <rect width="800" height="450" fill="url(#asset-default-glow)" />
      <circle cx="638" cy="112" r="54" fill="#d7c9b9" fill-opacity="0.09" />
      <path d="M-40 405 164 201l118 116 105-83 132 121 104-86 217 180H-40Z" fill="url(#asset-default-ridge)" />
      <path d="m-20 424 238-154 105 73 99-52 143 84 92-46 183 117H-20Z" fill="#151313" fill-opacity="0.78" />
      <path d="M0 354c133-54 248-50 361 10 111 59 251 61 439-5" fill="none" stroke="#cbbbe4" stroke-opacity="0.1" stroke-width="2" />
      <path d="M0 374c139-46 263-38 373 24 112 62 254 59 427-16" fill="none" stroke="#d6cbc0" stroke-opacity="0.07" />
    </svg>
    <div class="workbench-asset-default-image__identity">
      <span>
        <component :is="icon" :size="22" aria-hidden="true" />
      </span>
      <div>
        <strong>{{ title }}</strong>
        <small>{{ typeLabel }}资产 · {{ previewUrl ? (previewLabel || '已选参考图片') : '等待生成图片' }}</small>
      </div>
    </div>
  </div>
</template>
