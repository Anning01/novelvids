<script setup lang="ts">
import { computed } from 'vue'
import { Volume2 } from 'lucide-vue-next'
import { tr } from '@/i18n'
import AppButton from './AppButton.vue'
import type { Asset, Scene } from '@/types'

const props = defineProps<{ scene: Scene; assets: Asset[]; voiceBusy?: boolean }>()
defineEmits<{ voice: [asset: Asset] }>()
const labels = { dialogue: () => tr('对白'), offscreen: () => tr('画外音'), os: () => tr('内心 OS'), narration: () => tr('旁白') }
interface Voice { asset_id: string; mode: keyof typeof labels; text: string; start: number; end: number }
const voices = computed(() => {
  const bundle = props.scene.metadata?.work_package as { voices?: Voice[] } | undefined
  const localIds = props.scene.metadata?.voice_asset_ids as Record<string, number> | undefined
  return (bundle?.voices || []).map(track => {
    const asset = props.assets.find(item => item.id === localIds?.[track.asset_id] || (item.metadata?.work_package as {id?: string} | undefined)?.id === track.asset_id)
    return { ...track, asset, label: labels[track.mode]?.() }
  }).sort((a, b) => a.start - b.start)
})
const otherLines = computed(() => ['dialogue', 'narration'].flatMap(key => {
  const lines = props.scene.prompt_params?.[key]
  return Array.isArray(lines) ? lines.filter((line): line is string => typeof line === 'string') : []
}))
</script>

<template>
  <section v-if="voices.length || otherLines.length" class="shot-voices">
    <h3>{{ tr('人声时间轴') }}</h3>
    <ol v-if="voices.length">
      <li v-for="(v, i) in voices" :key="i">
        <header><strong>{{ v.asset?.canonical_name || v.asset_id }}</strong><span>{{ v.label }}</span><small>{{ v.start }}–{{ v.end }}s</small>
          <AppButton v-if="v.asset && v.mode === 'offscreen'" variant="ghost" size="xs" icon-only :disabled="voiceBusy" :aria-label="tr('为{p0}更换音色', {p0:v.asset.canonical_name})" @click="$emit('voice', v.asset)"><Volume2 :size="14" /></AppButton>
        </header>
        <p>{{ v.text }}</p>
      </li>
    </ol>
    <ol v-else><li v-for="(line, i) in otherLines" :key="i">{{ line }}</li></ol>
  </section>
</template>

<style scoped>
.shot-voices { color: var(--app-text); }
.shot-voices h3 { margin: 0 0 8px; font-size: 13px; }
.shot-voices ol { display: grid; gap: 9px; margin: 0; padding: 0; list-style: none; font-size: 12px; }
.shot-voices header { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.shot-voices header span { color: var(--app-accent); }
.shot-voices small { color: var(--app-text-secondary); font-variant-numeric: tabular-nums; }
.shot-voices p { margin: 3px 0 0; line-height: 1.55; }
</style>
