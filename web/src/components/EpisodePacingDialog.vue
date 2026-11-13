<script setup lang="ts">
import { computed, ref, useId } from 'vue'
import { Clock3, ChevronDown, Minus, Plus, X } from 'lucide-vue-next'
import { tr } from '@/i18n'
import type { EpisodePacing } from '@/types'

const props = defineProps<{
  pacing?: EpisodePacing | null
  episode: string
  disabled?: boolean
  save: (pacing: EpisodePacing) => Promise<void>
}>()
const presets = [
  ['compact', '紧凑节奏', '压缩过渡和重复反应'],
  ['fast', '快节奏', '让主要动作和对白推动剧情'],
  ['smart', '智能时长', '按本集内容估算'],
  ['slow', '慢节奏', '给关键情绪留白'],
  ['detailed', '极致细节', '展开有叙事作用的细节'],
] as const
const panel = ref<HTMLDialogElement>()
const trigger = ref<HTMLButtonElement>()
const durationId = useId()
const preset = ref<EpisodePacing['preset']>('smart')
const seconds = ref<number | ''>('')
const saving = ref(false)
const closing = ref(false)
const error = ref('')
const limit = computed(() => seconds.value === '' ? null : Number(seconds.value))
const invalid = computed(() => limit.value !== null && (!Number.isSafeInteger(limit.value) || limit.value < 1))
const label = computed(() => tr(presets.find(([key]) => key === (props.pacing?.preset ?? 'smart'))![1]))
const dirty = computed(() => preset.value !== (props.pacing?.preset ?? 'smart') ||
  limit.value !== (props.pacing?.max_seconds ?? null))

function open() {
  preset.value = props.pacing?.preset ?? 'smart'
  seconds.value = props.pacing?.max_seconds ?? ''
  error.value = ''
  panel.value?.showModal()
  panel.value?.querySelector<HTMLInputElement>('input:checked')?.focus()
}

function close() {
  if (closing.value) return
  if (matchMedia('(prefers-reduced-motion: reduce)').matches) {
    panel.value?.close()
    return
  }
  closing.value = true
}

function finishClose() {
  if (closing.value) panel.value?.close()
}

function resetFocus() {
  closing.value = false
  trigger.value?.focus()
}

async function submit() {
  if (invalid.value || !dirty.value || saving.value || closing.value) return
  saving.value = true
  error.value = ''
  try {
    await props.save({ preset: preset.value, max_seconds: limit.value })
    close()
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : tr('保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <button ref="trigger" class="pacing-trigger" type="button" :disabled="disabled" aria-haspopup="dialog" @click="open">
    <Clock3 :size="16" aria-hidden="true" />
    <span>{{ label }}<template v-if="pacing?.max_seconds"> · {{ tr('最多 {p0} 秒', { p0: pacing.max_seconds }) }}</template></span>
    <ChevronDown :size="14" aria-hidden="true" />
  </button>
  <Teleport to="body">
  <dialog ref="panel" :class="{ closing }" :aria-label="tr('本集时长与节奏')"
    @cancel.prevent="!saving && close()" @close="resetFocus" @animationend.self="finishClose">
    <form @submit.prevent="submit">
      <header>
        <div><h2>{{ tr('本集时长与节奏') }}</h2><small>{{ episode }}</small></div>
        <button type="button" class="icon-button" :aria-label="tr('关闭')" :disabled="saving" @click="close"><X :size="18" /></button>
      </header>
      <fieldset :disabled="saving || closing">
        <legend>{{ tr('节奏') }}</legend>
        <label v-for="[key, title, detail] in presets" :key="key" class="pace-option">
          <input v-model="preset" type="radio" name="episode-pace" :value="key">
          <strong>{{ tr(title) }}</strong><small>{{ tr(detail) }}</small>
        </label>
      </fieldset>
      <div class="limit">
        <div class="limit-row">
          <label :for="durationId"><strong>{{ tr('时长上限') }}</strong> <small>{{ tr('可选') }}</small></label>
          <div class="stepper">
            <button type="button" class="icon-button" :aria-label="tr('减少 5 秒')" :disabled="saving || closing || invalid || !limit || limit <= 1"
              @click="seconds = Math.max(1, Number(seconds) - 5)"><Minus :size="16" /></button>
            <input :id="durationId" v-model="seconds" type="number" min="1" step="1" inputmode="numeric" :placeholder="tr('自动')"
              :aria-describedby="`${durationId}-hint`" :aria-invalid="invalid" :disabled="saving || closing">
            <button type="button" class="icon-button" :aria-label="tr('增加 5 秒')" :disabled="saving || closing || invalid || !limit"
              @click="seconds = Number(seconds) + 5"><Plus :size="16" /></button>
            <small>{{ tr('秒') }}</small>
          </div>
        </div>
        <small :id="`${durationId}-hint`" aria-live="polite" :class="{ error: invalid }">{{ invalid ? tr('请输入大于 0 的整数秒。') : limit
          ? tr('剧本和分镜总时长上限为 {p0} 秒。', { p0: limit })
          : tr('留空，按所选节奏估算本集时长。') }}</small>
      </div>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <footer>
        <AppButton type="button" variant="secondary" :disabled="saving || closing" @click="close">{{ tr('取消') }}</AppButton>
        <AppButton type="submit" variant="primary" :loading="saving" :disabled="!dirty || invalid || closing">{{ tr('保存设置') }}</AppButton>
      </footer>
    </form>
  </dialog>
  </Teleport>
</template>

<style scoped>
.pacing-trigger,.icon-button{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:34px;padding:5px 10px;border:1px solid var(--app-border);border-radius:9px;background:var(--app-surface);color:var(--app-text);cursor:pointer;transition:background .16s,border-color .16s}
.pacing-trigger{background:var(--app-accent-soft);color:var(--app-accent)}
.pacing-trigger:hover:not(:disabled),.icon-button:hover:not(:disabled){border-color:var(--app-accent)}
button:disabled{opacity:.5;cursor:default}
button:focus-visible,input:focus-visible{outline:2px solid var(--app-accent);outline-offset:2px}
dialog{width:min(490px,calc(100% - 24px));max-height:calc(100% - 24px);padding:0;border:1px solid var(--app-border);border-radius:16px;background:var(--app-surface);color:var(--app-text);box-shadow:var(--app-shadow)}
dialog[open]{animation:slide-in .22s cubic-bezier(.2,.8,.2,1)}
dialog[open]::backdrop{background:#15152488;animation:fade-in .18s ease-out}
dialog[open].closing{animation:slide-out .15s ease-in both}
dialog[open].closing::backdrop{animation:fade-out .15s ease-in both}
@keyframes slide-in{from{opacity:0;transform:translateY(12px) scale(.985)}to{opacity:1;transform:none}}
@keyframes slide-out{to{opacity:0;transform:translateY(8px) scale(.985)}}
@keyframes fade-out{to{opacity:0}}
@keyframes fade-in{from{opacity:0}to{opacity:1}}
form{padding:22px}
header,footer,.limit-row,.stepper{display:flex;align-items:center;gap:8px}
header{justify-content:space-between;margin-bottom:16px}
h2{margin:0;font-size:20px}
small{color:var(--app-text-secondary);font-size:13px}
fieldset{margin:0 0 14px;padding:0;border:0;min-width:0}
legend{font-weight:650;margin-bottom:5px}
.pace-option{display:grid;grid-template-columns:auto auto 1fr;align-items:center;gap:8px;min-height:44px;padding:7px 9px;border:1px solid transparent;border-radius:8px;cursor:pointer;transition:background .16s,border-color .16s}
.pace-option:hover{background:var(--app-surface-hover)}
.pace-option:has(input:checked){background:var(--app-accent-soft);border-color:color-mix(in srgb,var(--app-accent) 35%,var(--app-border))}
.pace-option strong{white-space:nowrap}
.pace-option small{margin-left:auto;text-align:right}
input{accent-color:var(--app-accent)}
.limit{padding:12px;border:1px solid var(--app-border);border-radius:11px;background:var(--app-surface-muted)}
.limit-row{justify-content:space-between;flex-wrap:wrap;margin-bottom:6px}
.limit input{width:75px;min-height:34px;padding:6px;border:1px solid var(--app-border);border-radius:7px;text-align:center;background:var(--app-surface);color:inherit;appearance:textfield}
.limit input::-webkit-inner-spin-button,.limit input::-webkit-outer-spin-button{appearance:none}
.error{color:var(--app-danger,#b33645)}
footer{justify-content:flex-end;margin-top:16px}
@media(prefers-reduced-motion:reduce){dialog,dialog::backdrop,.pacing-trigger,.pace-option,.icon-button{animation:none!important;transition:none}}
</style>
