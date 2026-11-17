<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { FlaskConical, Plus, Send, Square, X } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { tr } from '@/i18n'
import type { EpisodePacing } from '@/types'
import SkillMarkdownEditor from './SkillMarkdownEditor.vue'
import { skillsApi, runSkillTrial, type CreativeSkill, type CreativeSkillInput, type TextTask } from './skillsApi'

const props = defineProps<{ task: TextTask; source?: CreativeSkill; copy?: boolean; disabled?: boolean }>()
const emit = defineEmits<{ close: []; saved: [skill: CreativeSkill] }>()
const id = useId()
const dialog = ref<HTMLDialogElement>()
const discardArea = ref<HTMLElement>()
const editingId = props.source && !props.source.builtin && !props.copy ? props.source.id : null
const editor = ref<CreativeSkillInput>({ task: props.task,
  name: props.source ? `${props.source.name}${editingId ? '' : tr('（副本）')}` : '',
  description: props.source?.description ?? '', instructions: props.source?.instructions ?? '',
  references: props.source?.references.map(item => ({ ...item })) ?? [], is_active: props.source?.is_active ?? true })
const original = JSON.stringify(editor.value)
const dirty = computed(() => JSON.stringify(editor.value) !== original)
const discard = ref(false)
const saving = ref(false)
const error = ref('')
const modelError = ref('')
const models = ref<{ id: number; name: string; model: string }[]>([])
const loadingModels = ref(true)
const modelId = ref('')
const thinking = ref('default')
const effort = ref('default')
const input = ref('')
const pacing = ref<EpisodePacing['preset']>('smart')
const maxSeconds = ref<number | ''>('')
const secondsInput = ref<HTMLInputElement>()
const parameters = ref<HTMLDetailsElement>()
const parametersExpanded = ref(false)
const hasPacingParameters = computed(() => props.task === 'screenplay' ||
  [editor.value.instructions, ...editor.value.references.map(reference => reference.content)]
    .some(content => /\{\{\s*(?:episode_pacing(?:\.\w+)*|max_seconds)\s*\}\}/.test(content)))
const pacingOptions = computed(() => [
  { value: 'compact', label: tr('紧凑节奏') }, { value: 'fast', label: tr('快节奏') },
  { value: 'smart', label: tr('智能时长') }, { value: 'slow', label: tr('慢节奏') },
  { value: 'detailed', label: tr('极致细节') },
])
const output = ref('')
const thoughts = ref('')
const running = ref(false)
const trialStatus = ref('')
const trialError = ref('')
const elapsed = ref(0)
const tokenCount = ref<number | null>(null)
let controller: AbortController | undefined
let timer: ReturnType<typeof setInterval> | undefined
const modelOptions = computed(() => models.value.length ? models.value.map(item => ({ value: String(item.id), label: item.name })) : [{ value: '', label: tr('暂无可用模型') }])
const thinkingOptions = computed(() => [{ value: 'default', label: tr('跟随模型') }, { value: 'enabled', label: tr('开启思考') }, { value: 'disabled', label: tr('关闭思考') }])
const effortOptions = computed(() => [{ value: 'default', label: tr('跟随模型') }, { value: 'low', label: tr('低') }, { value: 'medium', label: tr('中') }, { value: 'high', label: tr('高') }, { value: 'xhigh', label: tr('极高') }])

async function loadModels() {
  loadingModels.value = true; modelError.value = ''
  try {
    models.value = (await skillsApi.models()).data
    modelId.value = models.value[0] ? String(models.value[0].id) : ''
  } catch (caught) { modelError.value = (caught as Error).message }
  finally { loadingModels.value = false }
}
onMounted(async () => { await nextTick(); dialog.value?.showModal(); void loadModels() })
onBeforeUnmount(() => { controller?.abort(); clearInterval(timer); dialog.value?.close() })
async function requestClose(event?: Event) {
  event?.preventDefault()
  if (saving.value) return
  if (dirty.value || running.value) {
    discard.value = true
    await nextTick()
    discardArea.value?.scrollIntoView({ block: 'nearest' })
    discardArea.value?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true })
    return
  }
  closeEditor()
}
function resumeEditing() {
  discard.value = false
  dialog.value?.querySelector<HTMLInputElement>('input[name="skill-name"]')?.focus()
}
function closeEditor() {
  controller?.abort()
  dialog.value?.close()
}
async function save() {
  if (saving.value || running.value || props.disabled) return
  if (!editor.value.instructions.trim()) { error.value = tr('请填写创作方法'); return }
  saving.value = true; error.value = ''
  try {
    const { data } = editingId
      ? await skillsApi.update(editingId, editor.value, props.source?.version ?? 1)
      : await skillsApi.create(editor.value)
    emit('saved', data)
    dialog.value?.close()
  } catch (caught) { error.value = (caught as Error).message }
  finally { saving.value = false }
}
async function send() {
  if (running.value || !input.value.trim() || !modelId.value || !editor.value.instructions.trim()) return
  if (hasPacingParameters.value && secondsInput.value && !secondsInput.value.checkValidity()) {
    if (parameters.value) parameters.value.open = true
    await nextTick()
    secondsInput.value.reportValidity()
    return
  }
  controller = new AbortController()
  running.value = true; trialError.value = ''; output.value = ''; thoughts.value = ''; tokenCount.value = null; elapsed.value = 0
  trialStatus.value = tr('等待模型')
  const start = Date.now()
  timer = setInterval(() => { elapsed.value = Math.floor((Date.now() - start) / 1000) }, 1000)
  try {
    await runSkillTrial({ skill: { ...editor.value, references: editor.value.references.map(item => ({ ...item })) },
      model_config_id: Number(modelId.value), input: input.value,
      ...(hasPacingParameters.value ? { episode_pacing: { preset: pacing.value, max_seconds: maxSeconds.value === '' ? null : maxSeconds.value } } : {}),
      thinking: thinking.value === 'default' ? null : thinking.value,
      reasoning_effort: effort.value === 'default' ? null : effort.value }, controller.signal, event => {
      if (event.type === 'output') output.value += event.delta ?? ''
      if (event.type === 'thinking') thoughts.value += event.delta ?? ''
      if (event.type === 'status') trialStatus.value = event.status === 'waiting' ? tr('等待模型') : tr('正在生成')
      if (event.type === 'error') { trialError.value = event.message ?? tr('试运行失败，请重试'); trialStatus.value = tr('试运行失败') }
      if (event.type === 'done') {
        trialStatus.value = tr('试运行完成')
        tokenCount.value = (event.usage?.input_tokens ?? 0) + (event.usage?.output_tokens ?? 0)
        try { output.value = JSON.stringify(JSON.parse(output.value), null, 2) } catch { /* Keep partial text available for inspection. */ }
      }
    })
  } catch (caught) {
    if (controller.signal.aborted) trialStatus.value = tr('已停止')
    else { trialError.value = (caught as Error).message; trialStatus.value = tr('试运行失败') }
  } finally { running.value = false; clearInterval(timer) }
}
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="skill-editor-dialog" :aria-labelledby="`${id}-title`" closedby="none" @cancel="requestClose" @close="emit('close')">
      <form class="skill-editor" :aria-label="tr('编辑技能')" @submit.prevent="save">
        <header class="skill-editor-header">
          <div><h2 :id="`${id}-title`">{{ editingId ? tr('编辑技能') : tr('创建我的技能') }}</h2><p>{{ tr('编辑 Markdown，输入素材，直接试运行。') }}</p></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('关闭')" :disabled="saving" @click="requestClose()"><X :size="18" /></AppButton>
        </header>
        <div class="skill-lab-columns">
          <section class="skill-source" :aria-label="tr('技能内容')">
            <fieldset class="skill-metadata" :disabled="saving || running || disabled">
              <label :for="`${id}-name`">{{ tr('技能名称') }}<input :id="`${id}-name`" v-model="editor.name" name="skill-name" autofocus required maxlength="100" /></label>
              <label :for="`${id}-description`">{{ tr('说明（可选）') }}<input :id="`${id}-description`" v-model="editor.description" name="skill-description" maxlength="1000" /></label>
            </fieldset>
            <div class="skill-instructions"><SkillMarkdownEditor v-model="editor.instructions" :task="task" :disabled="saving || running || disabled" /></div>
            <details class="skill-references">
              <summary>{{ tr('参考资料') }} <span>{{ editor.references.length }}/10</span></summary>
              <fieldset :disabled="saving || running || disabled">
                <div v-for="(reference, index) in editor.references" :key="index" class="skill-reference">
                  <label :for="`${id}-reference-${index}`">{{ tr('参考资料名称') }}<input :id="`${id}-reference-${index}`" v-model="reference.name" required maxlength="100" /></label>
                  <label :for="`${id}-content-${index}`">{{ tr('参考资料内容') }}<textarea :id="`${id}-content-${index}`" v-model="reference.content" required maxlength="32000" rows="3" /></label>
                  <AppButton type="button" variant="ghost" size="sm" @click="editor.references.splice(index, 1)">{{ tr('移除参考资料') }}</AppButton>
                </div>
                <AppButton type="button" variant="ghost" size="sm" :disabled="editor.references.length >= 10" @click="editor.references.push({ name: '', content: '' })"><Plus :size="14" />{{ tr('添加参考资料') }}</AppButton>
              </fieldset>
            </details>
          </section>
          <section class="skill-result" :aria-labelledby="`${id}-result`">
            <header><h3 :id="`${id}-result`">{{ tr('模型输出') }}</h3><span role="status">{{ trialStatus }}<template v-if="trialStatus"> · {{ elapsed }}s<template v-if="tokenCount !== null"> · {{ tokenCount }} tokens</template></template></span></header>
            <div class="result-scroll" :aria-busy="running">
              <details v-if="thoughts" class="model-thoughts"><summary>{{ tr('思考过程') }}</summary><pre>{{ thoughts }}</pre></details>
              <pre v-if="output" class="model-output" tabindex="0">{{ output }}</pre>
              <div v-else class="result-empty"><FlaskConical v-if="!parametersExpanded" :size="28" aria-hidden="true" /><strong>{{ tr('试试这项技能') }}</strong><p v-if="!parametersExpanded">{{ tr('在下方输入一段素材，查看当前技能的实际输出。') }}</p></div>
              <p v-if="trialError" class="skill-error" role="alert">{{ trialError }}</p>
            </div>
          <details v-if="hasPacingParameters" ref="parameters" class="trial-parameters" @toggle="parametersExpanded = ($event.target as HTMLDetailsElement).open">
            <summary>{{ tr('占位符参数（仅试运行）') }}</summary>
            <p :id="`${id}-parameters-hint`">{{ tr('正式生成时从本集设置填入，保存技能时保留占位符。') }}</p>
            <div class="trial-parameter-fields">
              <label>{{ tr('本集节奏') }}<AppSelect v-model="pacing" :options="pacingOptions" :ariaLabel="tr('本集节奏')" :disabled="running" /><code v-pre>{{episode_pacing}}</code></label>
              <label :for="`${id}-seconds`">{{ tr('本集参考时长（秒）') }}
                <!-- Trial parameters must not block the separate skill-save action. -->
                <input :id="`${id}-seconds`" ref="secondsInput" v-model.number="maxSeconds" form="" name="trial-max-seconds" type="number" inputmode="numeric" min="1" :max="Number.MAX_SAFE_INTEGER" step="1" :placeholder="tr('留空按剧情自然展开')" :disabled="running" :aria-describedby="`${id}-parameters-hint`" />
                <code v-pre>{{max_seconds}}</code>
              </label>
            </div>
          </details>
            <p class="trial-note">{{ tr('试运行使用当前内容，不保存到项目；模型调用按正常用量计费。') }}</p>
          </section>
        </div>
        <footer class="skill-lab-footer">
          <label :for="`${id}-input`" class="input-label">{{ tr('测试输入') }}</label>
          <textarea :id="`${id}-input`" v-model="input" class="trial-input" :placeholder="tr('粘贴小说片段、剧本或你的测试要求…')" :disabled="running" maxlength="64000" rows="3" @keydown.ctrl.enter.prevent="send" @keydown.meta.enter.prevent="send" />
          <p v-if="modelError" class="skill-error" role="alert">{{ modelError }} <AppButton type="button" variant="ghost" size="sm" @click="loadModels">{{ tr('重试') }}</AppButton></p>
          <p v-if="error" class="skill-error" role="alert">{{ error }}</p>
          <div class="skill-lab-actions">
            <div class="trial-options">
              <label>{{ tr('模型') }}<AppSelect v-model="modelId" :options="modelOptions" :ariaLabel="tr('试运行模型')" :disabled="running || loadingModels || !models.length" searchable /></label>
              <label>{{ tr('思考模式') }}<AppSelect v-model="thinking" :options="thinkingOptions" :ariaLabel="tr('思考模式')" :disabled="running" /></label>
              <label>{{ tr('强度') }}<AppSelect v-model="effort" :options="effortOptions" :ariaLabel="tr('推理强度')" :disabled="running" /></label>
            </div>
            <div class="save-options">
              <AppButton v-if="running" type="button" variant="secondary" @click="controller?.abort()"><Square :size="14" />{{ tr('停止') }}</AppButton>
              <AppButton v-else type="button" variant="secondary" :disabled="!modelId || !input.trim() || !editor.instructions.trim() || saving || disabled" @click="send"><Send :size="15" />{{ tr('发送') }}</AppButton>
              <AppButton type="submit" variant="primary" :loading="saving" :disabled="running || disabled">{{ tr('保存技能') }}</AppButton>
            </div>
          </div>
          <div ref="discardArea" class="discard-area" :class="{ visible: discard }" :aria-hidden="!discard">
            <p :id="`${id}-discard`">{{ tr('关闭将丢弃未保存的修改，并停止试运行。') }}</p>
            <AppButton type="button" variant="ghost" size="sm" :tabindex="discard ? 0 : -1" :aria-describedby="`${id}-discard`" @click="resumeEditing">{{ tr('继续编辑') }}</AppButton>
            <AppButton type="button" variant="secondary" size="sm" :tabindex="discard ? 0 : -1" :aria-describedby="`${id}-discard`" @click="closeEditor">{{ tr('放弃并关闭') }}</AppButton>
          </div>
        </footer>
      </form>
    </dialog>
  </Teleport>
</template>

<style scoped>
.skill-editor-dialog { box-sizing: border-box; inline-size: min(1440px, calc(100% - 48px)); max-inline-size: none; max-block-size: calc(100dvh - 48px); padding: 0; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); color: var(--app-text); overflow: hidden; }
.skill-editor-dialog:modal { overscroll-behavior: contain; }
.skill-editor-dialog::backdrop { background: rgb(15 17 25 / 55%); overflow: hidden; overscroll-behavior: contain; }
.skill-editor { display: flex; flex-direction: column; block-size: min(900px, calc(100dvh - 50px)); }
.skill-editor-header { display: flex; flex: none; justify-content: space-between; align-items: flex-start; padding: 18px 24px; border-block-end: 1px solid var(--app-border); }
h2 { font-size: 19px; margin: 0; } h3 { font-size: 14px; margin: 0; }
p { color: var(--app-text-secondary); font-size: 12px; line-height: 1.6; margin: 4px 0 0; }
.skill-lab-columns { display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr); flex: 1; min-block-size: 0; }
.skill-source { display: flex; flex-direction: column; min-block-size: 0; overflow: hidden; border-inline-end: 1px solid var(--app-border); }
fieldset { border: 0; margin: 0; padding: 0; min-inline-size: 0; }
.skill-metadata { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; padding: 16px 20px; border-block-end: 1px solid var(--app-border); }
label { display: grid; gap: 6px; min-inline-size: 0; color: var(--app-text-secondary); font-size: 12px; }
input, textarea { box-sizing: border-box; inline-size: 100%; padding: 9px 11px; font: inherit; color: var(--app-text); caret-color: var(--app-accent); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 8px; }
input:hover, textarea:hover { border-color: var(--app-border-strong); }
input:focus-visible, textarea:focus-visible, summary:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
input:disabled, textarea:disabled { opacity: .6; }
.skill-instructions { flex: 1; min-block-size: 0; }
.skill-references { flex: none; border-block-start: 1px solid var(--app-border); padding: 12px 20px; max-block-size: 35%; overflow: auto; }
summary { font-size: 12px; cursor: pointer; color: var(--app-text-secondary); } summary span { margin-inline-start: 6px; font-variant-numeric: tabular-nums; }
.skill-reference { display: grid; gap: 10px; margin-block: 12px; } .skill-reference button { justify-self: start; }
.skill-result { display: flex; flex-direction: column; min-block-size: 0; background: var(--app-canvas); }
.skill-result > header { padding: 20px; display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.skill-result header span { color: var(--app-text-secondary); font-size: 11px; font-variant-numeric: tabular-nums; }
.result-scroll { flex: 1; min-block-size: 0; overflow: auto; padding: 0 20px 20px; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: var(--app-border-strong) transparent; }
.model-output, .model-thoughts pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 13px/1.8 ui-monospace, monospace; margin: 16px 0 0; }
.model-thoughts pre { color: var(--app-text-secondary); font-family: inherit; }
.result-empty { min-block-size: 0; block-size: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 12px; text-align: center; color: var(--app-text-secondary); }
.result-empty strong { color: var(--app-text); font-size: 15px; } .result-empty p { max-inline-size: 30ch; }
.trial-note { padding: 10px 20px; border-block-start: 1px solid var(--app-border); }
.skill-lab-footer { flex: none; padding: 14px 20px 0; border-block-start: 1px solid var(--app-border); }
.input-label { margin-block-end: 8px; } .trial-input { resize: vertical; min-block-size: 72px; max-block-size: 180px; font-size: 13px; line-height: 1.6; }
.trial-parameters { flex: none; padding: 10px 20px; border-block-start: 1px solid var(--app-border); max-block-size: 50%; overflow: auto; }
.trial-parameter-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; max-inline-size: 520px; margin-block-start: 10px; }
.trial-parameter-fields code { font-size: 11px; color: var(--app-text-secondary); }
.trial-parameter-fields input:user-invalid { border-color: var(--app-danger, #b33645); }
.skill-lab-actions { display: flex; justify-content: space-between; align-items: end; gap: 16px; margin-block-start: 12px; }
.trial-options, .save-options { display: flex; align-items: end; gap: 10px; flex-wrap: wrap; }
.trial-options > label:first-child { min-inline-size: 180px; max-inline-size: 300px; }
.save-options { flex: none; }
.skill-error { color: var(--app-danger, #b33645); }
.discard-area { visibility: hidden; display: flex; justify-content: end; gap: 8px; align-items: center; min-block-size: 44px; }
.discard-area.visible { visibility: visible; }
.discard-area p { margin: 0 auto 0 0; }
@media (max-width: 800px) {
  .skill-editor-dialog { inline-size: calc(100% - 16px); max-block-size: calc(100dvh - 16px); }
  .skill-editor { block-size: calc(100dvh - 18px); overflow-y: auto; }
  .skill-lab-columns { grid-template-columns: minmax(0, 1fr); flex: none; }
  .skill-source { block-size: 480px; border-inline-end: 0; border-block-end: 1px solid var(--app-border); }
  .skill-result { block-size: 360px; }
  .skill-editor-header { padding: 16px; } .skill-metadata { padding: 14px 16px; }
  .skill-lab-footer { padding-inline: 16px; } .skill-lab-actions { align-items: stretch; flex-direction: column; }
  .save-options { justify-content: end; } .discard-area { flex-wrap: wrap; padding-block: 8px; }
}
@media (pointer: coarse) { input, textarea { font-size: 16px; } .skill-editor :deep(button) { min-block-size: 44px; } }
</style>
