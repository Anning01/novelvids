<script setup lang="ts">
import { ref, watch } from 'vue'
import { Check, Copy } from 'lucide-vue-next'
import { tr } from '@/i18n'
import { notice } from '@/shared/notice'

const props = defineProps<{ code: string; language: string }>()
const copied = ref(false)
watch(() => props.code, () => { copied.value = false })
async function copy() {
  try {
    await navigator.clipboard.writeText(props.code)
    copied.value = true
  } catch {
    notice.error(tr('请选中文字后复制'))
  }
}
</script>

<template>
  <div class="api-code">
    <div class="api-code-toolbar"><span>{{ language }}</span><button :aria-label="tr('复制代码')" @click="copy"><Check v-if="copied" :size="14" /><Copy v-else :size="14" />{{ copied ? tr('已复制') : tr('复制代码') }}</button></div>
    <pre tabindex="0" :aria-label="language"><code>{{ code }}</code></pre>
  </div>
</template>

<style scoped>
.api-code { min-width:0; overflow:hidden; border:1px solid var(--app-border); border-radius:11px; background:var(--app-surface-muted); }
.api-code-toolbar { display:flex; align-items:center; justify-content:space-between; gap:12px; min-height:42px; padding:0 15px; border-bottom:1px solid var(--app-border); color:var(--app-text-secondary); font-size:11px; }
.api-code-toolbar button { display:flex; align-items:center; gap:6px; min-height:32px; padding:0 7px; background:transparent; border:0; border-radius:5px; color:var(--app-text-secondary); font:inherit; cursor:pointer; }
.api-code-toolbar button:hover { color:var(--app-accent); background:var(--app-surface-hover); }
pre { margin:0; padding:20px; max-width:100%; overflow:auto; color:var(--app-text); font:12px/1.9 ui-monospace,SFMono-Regular,Consolas,monospace; tab-size:4; }
button:focus-visible,pre:focus-visible { outline:2px solid var(--app-accent); outline-offset:-2px; }
</style>
