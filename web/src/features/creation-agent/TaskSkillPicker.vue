<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId } from 'vue'
import { Plus, X } from 'lucide-vue-next'
import { tr } from '@/i18n'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { skillsApi, type CreativeSkill, type CreativeSkillInput, type TextTask } from './skillsApi'

const props = defineProps<{ task: TextTask; modelValue?: number; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: number]; 'editing-change': [value: boolean] }>()
const id = useId()
const skills = ref<CreativeSkill[]>([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const status = ref('')
const defaultId = ref(0)
const editor = ref<CreativeSkillInput | null>(null)
const editingId = ref<number | null>(null)
const editingVersion = ref(1)
const dialog = ref<HTMLDialogElement>()
const selected = computed(() => skills.value.find(skill => skill.id === props.modelValue))
const title = computed(() => tr({ story: '故事分析技能', screenplay: '剧本改编技能', assets: '资产提取技能', storyboard: '分镜生成技能' }[props.task]))
const options = computed(() => loading.value
  ? [{ value: '', label: tr('正在读取技能…') }]
  : skills.value.filter(skill => skill.is_active).map(skill => ({
    value: String(skill.id),
    label: `${skill.builtin ? tr('内置技能') : skill.name}${skill.id === defaultId.value ? ` · ${tr('默认')}` : ''}`,
  })))

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await skillsApi.list(props.task)
    skills.value = data.items
    defaultId.value = data.default_skill_id
    if (props.modelValue === undefined) emit('update:modelValue', data.default_skill_id)
  } catch (caught) { error.value = (caught as Error).message }
  finally { loading.value = false }
}
onMounted(load)
onBeforeUnmount(() => emit('editing-change', false))

async function edit(copy = false) {
  const source = selected.value
  editingId.value = source && !source.builtin && !copy ? source.id : null
  editingVersion.value = source?.version ?? 1
  editor.value = {
    task: props.task, name: source ? `${source.name}${editingId.value ? '' : tr('（副本）')}` : '',
    description: source?.description ?? '', instructions: source?.instructions ?? '',
    references: source?.references.map(item => ({ ...item })) ?? [], is_active: true,
  }
  error.value = ''
  status.value = ''
  emit('editing-change', true)
  await nextTick()
  dialog.value?.showModal()
}

function closeEditor() {
  if (!saving.value) dialog.value?.close()
}

function finishClose() {
  editor.value = null
  error.value = ''
  emit('editing-change', false)
}

async function save() {
  if (!editor.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    const { data } = editingId.value
      ? await skillsApi.update(editingId.value, editor.value, editingVersion.value)
      : await skillsApi.create(editor.value)
    skills.value = [...skills.value.filter(skill => skill.id !== data.id), data]
    emit('update:modelValue', data.id)
    status.value = tr('技能已保存，下一次生成时生效')
    saving.value = false
    closeEditor()
  } catch (caught) { error.value = (caught as Error).message }
  finally { saving.value = false }
}

async function setDefault() {
  if (!selected.value || saving.value) return
  saving.value = true
  error.value = ''
  try {
    await skillsApi.setDefault(props.task, selected.value.id)
    defaultId.value = selected.value.id
    status.value = tr('已设为我的默认技能')
  } catch (caught) { error.value = (caught as Error).message }
  finally { saving.value = false }
}
</script>

<template>
  <div class="task-skill-picker">
    <div class="skill-controls">
      <span :id="`${id}-label`" class="skill-label">{{ title }}</span>
      <AppSelect :model-value="modelValue === undefined ? '' : String(modelValue)" :options="options" :ariaLabel="title" density="compact"
        :disabled="disabled || loading || saving || !!editor || !skills.length"
        @update:model-value="emit('update:modelValue', Number($event))" />
      <AppButton type="button" variant="ghost" size="sm" aria-haspopup="dialog"
        :aria-describedby="`${id}-label`"
        :disabled="disabled || loading || saving || !selected" @click="edit()">
        {{ selected?.builtin ? tr('复制并编辑') : tr('编辑技能') }}
      </AppButton>
      <AppButton v-if="selected && !selected.builtin" type="button" variant="ghost" size="sm" aria-haspopup="dialog"
        :disabled="disabled || saving" @click="edit(true)">{{ tr('另存为新技能') }}</AppButton>
      <AppButton v-if="selected && selected.id !== defaultId" type="button" variant="ghost" size="sm"
        :disabled="disabled || saving || !!editor" @click="setDefault">{{ tr('设为默认') }}</AppButton>
    </div>
    <Teleport to="body">
      <dialog ref="dialog" class="skill-editor-dialog" :aria-labelledby="`${id}-title`"
        @cancel="saving && $event.preventDefault()" @close="finishClose">
        <form v-if="editor" :aria-label="title" class="skill-editor" @submit.prevent="save">
          <header class="skill-editor-header">
            <div>
              <h2 :id="`${id}-title`">{{ editingId ? tr('编辑技能') : tr('创建我的技能') }}</h2>
              <p>{{ title }}</p>
            </div>
            <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('关闭')" :disabled="saving" @click="closeEditor"><X :size="18" aria-hidden="true" /></AppButton>
          </header>
          <div class="skill-editor-body">
            <fieldset :disabled="disabled || saving">
              <div class="skill-metadata">
                <div class="skill-field">
                  <label :for="`${id}-name`">{{ tr('技能名称') }}</label>
                  <input :id="`${id}-name`" v-model.trim="editor.name" name="skill-name" autofocus required maxlength="100" />
                </div>
                <div class="skill-field">
                  <label :for="`${id}-description`">{{ tr('说明（可选）') }}</label>
                  <input :id="`${id}-description`" v-model.trim="editor.description" name="skill-description" maxlength="1000" />
                </div>
              </div>
              <div class="skill-field">
                <label :for="`${id}-instructions`">{{ tr('创作方法') }}</label>
                <p :id="`${id}-hint`">{{ tr('写下本次任务的创作方法与偏好，结果会自动保存到对应位置。') }}</p>
                <textarea :id="`${id}-instructions`" v-model.trim="editor.instructions" name="skill-instructions" rows="12" required maxlength="32000" :aria-describedby="`${id}-hint`" />
              </div>
              <div v-for="(reference, index) in editor.references" :key="index" class="skill-reference">
                <div class="skill-field">
                  <label :for="`${id}-reference-${index}`">{{ tr('参考资料名称') }}</label>
                  <input :id="`${id}-reference-${index}`" v-model.trim="reference.name" :name="`reference-name-${index}`" required maxlength="100" />
                </div>
                <div class="skill-field">
                  <label :for="`${id}-content-${index}`">{{ tr('参考资料内容') }}</label>
                  <textarea :id="`${id}-content-${index}`" v-model.trim="reference.content" :name="`reference-content-${index}`" rows="4" required maxlength="32000" />
                </div>
                <AppButton type="button" variant="ghost" size="sm" @click="editor.references.splice(index, 1)">{{ tr('移除参考资料') }}</AppButton>
              </div>
              <AppButton class="add-reference" type="button" variant="secondary" size="sm" :disabled="editor.references.length >= 10"
                @click="editor.references.push({ name: '', content: '' })"><Plus :size="15" aria-hidden="true" />{{ tr('添加参考资料') }}</AppButton>
            </fieldset>
            <p v-if="error" class="skill-error" role="alert">{{ error }}</p>
          </div>
          <footer class="skill-actions">
            <AppButton type="button" variant="secondary" :disabled="saving" @click="closeEditor">{{ tr('取消') }}</AppButton>
            <AppButton type="submit" variant="primary" :loading="saving" :disabled="disabled">{{ tr('保存技能') }}</AppButton>
          </footer>
        </form>
      </dialog>
    </Teleport>
    <p v-if="error && !editor" class="skill-error" role="alert">{{ error }} <AppButton type="button" variant="ghost" size="sm" :disabled="loading" @click="load">{{ tr('重试') }}</AppButton></p>
    <p v-if="status" role="status">{{ status }}</p>
  </div>
</template>

<style scoped>
.task-skill-picker { box-sizing: border-box; min-width: 0; width: 100%; color: var(--app-text); }
.skill-controls { display: flex; align-items: center; flex-wrap: wrap; gap: .5rem; }
.skill-label { font-size: 11px; color: var(--app-text-secondary); white-space: nowrap; }
.skill-controls > .app-select { min-inline-size: 0; max-inline-size: min(22rem, 100%); }
input, textarea { box-sizing: border-box; max-width: 100%; font: inherit; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 8px; padding: .5rem .625rem; caret-color: var(--app-accent); }
input:hover:not(:disabled), textarea:hover:not(:disabled) { border-color: var(--app-accent); }
input:focus-visible, textarea:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
input:disabled, textarea:disabled { opacity: .6; cursor: not-allowed; }
.skill-editor-dialog { box-sizing: border-box; inline-size: min(880px, calc(100% - 32px)); max-inline-size: none; max-block-size: calc(100dvh - 32px); padding: 0; border: 1px solid var(--app-border); border-radius: 16px; color: var(--app-text); background: var(--app-surface); box-shadow: var(--app-shadow); overflow: hidden; }
.skill-editor-dialog:modal { overscroll-behavior: contain; }
.skill-editor-dialog::backdrop { background: rgb(15 17 25 / 55%); overflow: hidden; overscroll-behavior: contain; }
.skill-editor { display: flex; flex-direction: column; max-block-size: min(860px, calc(100dvh - 34px)); margin: 0; }
.skill-editor-header { display: flex; flex: none; align-items: flex-start; justify-content: space-between; gap: 16px; padding: 20px 24px; border-block-end: 1px solid var(--app-border); }
.skill-editor-header h2 { margin: 0; font-size: 20px; line-height: 1.4; }
.skill-editor-header p { margin: 4px 0 0; font-size: 12px; }
.skill-editor-body { min-block-size: 0; overflow-y: auto; overscroll-behavior: contain; padding: 20px 24px; scrollbar-width: thin; scrollbar-color: var(--app-border-strong) transparent; }
fieldset { display: grid; gap: 20px; border: 0; padding: 0; margin: 0; min-inline-size: 0; }
.skill-metadata { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.skill-field { display: grid; gap: 8px; min-inline-size: 0; }
.skill-field label { font-size: 13px; font-weight: 600; }
.skill-field p { margin: 0; font-size: 12px; }
.skill-editor input, .skill-editor textarea { width: 100%; font-size: 13px; padding: 10px 12px; }
textarea { min-block-size: 18rem; resize: vertical; line-height: 1.7; }
p { color: var(--app-text-secondary); font-size: .875rem; line-height: 1.5; overflow-wrap: anywhere; }
.skill-reference { display: grid; gap: 12px; padding: 16px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface-muted); }
.skill-reference textarea { min-block-size: 7rem; }
.skill-reference > button, .add-reference { justify-self: start; }
.skill-actions { display: flex; flex: none; justify-content: flex-end; gap: 8px; padding: 16px 24px; border-block-start: 1px solid var(--app-border); }
.skill-editor :deep(.app-button--secondary) { color: var(--app-text-secondary); background: var(--app-surface-muted); box-shadow: inset 0 0 0 1px var(--app-border); }
.skill-editor :deep(.app-button--secondary:hover:not(:disabled)), .skill-editor :deep(.app-button--ghost:hover:not(:disabled)) { color: var(--app-text); background: var(--app-surface-hover); }
.skill-editor :deep(button:focus-visible) { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.skill-error { color: var(--app-danger, #b33645); }
@media (max-width: 600px) {
  .skill-editor-dialog { inline-size: calc(100% - 16px); max-block-size: calc(100dvh - 16px); }
  .skill-editor { max-block-size: calc(100dvh - 18px); }
  .skill-editor-header, .skill-editor-body { padding: 16px; }
  .skill-metadata { grid-template-columns: 1fr; }
  .skill-actions { padding: 12px 16px; }
  .skill-actions > button { flex: 1; }
}
@media (pointer: coarse) { input, .skill-controls :deep(button) { min-height: 48px; font-size: 1rem; } }
@media (pointer: coarse) { .skill-editor input, .skill-editor textarea { font-size: 1rem; } .skill-editor :deep(button) { min-height: 44px; } }
</style>
