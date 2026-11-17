<script setup lang="ts">
import { computed, onBeforeUnmount, ref, useId, watch } from 'vue'
import { Download, FilePlus, Pencil, Trash2, Upload } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import { tr } from '@/i18n'
import { saveBlob } from '@/shared/downloadFile'
import SkillFileTree from './SkillFileTree.vue'
import SkillMarkdownEditor from './SkillMarkdownEditor.vue'
import { browserSkillFile, imageMime, skillFileBlob, skillFileSize, skillFileTree, uniqueSkillPaths, validSkillPath } from './skillFiles'
import type { SkillFile, SkillPackageLimits, TextTask } from './skillsApi'

const props = defineProps<{ modelValue: SkillFile[]; limits: SkillPackageLimits; task: TextTask; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [files: SkillFile[]] }>()
const id = useId()
const selected = ref('SKILL.md')
const action = ref<'create' | 'rename' | null>(null)
const path = ref('')
const error = ref('')
const uploading = ref(false)
const removeConfirm = ref(false)
const upload = ref<HTMLInputElement>()
const imageUrl = ref('')
const imageFailed = ref(false)
const tree = computed(() => skillFileTree(props.modelValue))
const current = computed(() => props.modelValue.find(file => file.path === selected.value))
watch(() => props.modelValue, files => { if (!files.some(file => file.path === selected.value || file.path.startsWith(selected.value + '/'))) selected.value = files[0]?.path ?? '' })
watch(current, file => {
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = file && imageMime(file.path) ? URL.createObjectURL(skillFileBlob(file)) : ''
  imageFailed.value = false
  removeConfirm.value = false
}, { immediate: true })
onBeforeUnmount(() => { if (imageUrl.value) URL.revokeObjectURL(imageUrl.value) })

function selectFile(value: string) { selected.value = value; action.value = null; error.value = '' }
function setContent(content: string) {
  const file = current.value
  if (!file || props.disabled) return
  emit('update:modelValue', props.modelValue.map(item => item.path === file.path ? { ...item, content } : item))
}
function startAction(value: 'create' | 'rename') {
  action.value = value; path.value = value === 'rename' ? selected.value : !current.value && selected.value ? selected.value + '/' : ''; error.value = ''
}
function applyAction() {
  if (!validSkillPath(path.value)) { error.value = tr('请输入技能目录内的相对路径，如 references/example.md'); return }
  const duplicate = props.modelValue.some(file => file.path.normalize('NFC').toLowerCase() === path.value.normalize('NFC').toLowerCase() && !(action.value === 'rename' && file.path === selected.value))
  if (duplicate) { error.value = tr('已存在同名文件，请换一个名称'); return }
  const paths = action.value === 'create' ? [...props.modelValue.map(file => file.path), path.value]
    : props.modelValue.map(file => file.path === selected.value ? path.value : file.path)
  if (!uniqueSkillPaths(paths)) { error.value = tr('文件与文件夹路径冲突，请修改路径'); return }
  if (action.value === 'create') {
    if (props.modelValue.length >= props.limits.max_files) { error.value = tr('文件数量已达到上限'); return }
    emit('update:modelValue', [...props.modelValue, { path: path.value, content: '', encoding: 'utf-8' }])
  } else emit('update:modelValue', props.modelValue.map(file => file.path === selected.value ? { ...file, path: path.value } : file))
  selected.value = path.value; action.value = null
}
async function uploadFiles(event: Event) {
  const input = event.target as HTMLInputElement
  const files = [...(input.files ?? [])]
  input.value = ''
  if (!files.length) return
  uploading.value = true; error.value = ''
  try {
    if (props.modelValue.length + files.length > props.limits.max_files ||
      props.modelValue.reduce((total, file) => total + skillFileSize(file), 0) + files.reduce((total, file) => total + file.size, 0) > props.limits.max_package_bytes) throw new Error(tr('技能包超过文件数量或总大小上限'))
    const prefix = !current.value && selected.value ? selected.value + '/' : selected.value.includes('/') ? selected.value.slice(0, selected.value.lastIndexOf('/') + 1) : ''
    const additions = await Promise.all(files.map(file => browserSkillFile(file, prefix + file.name, props.limits)))
    const merged = [...props.modelValue, ...additions]
    if (merged.length > props.limits.max_files || merged.reduce((total, file) => total + skillFileSize(file), 0) > props.limits.max_package_bytes) throw new Error(tr('技能包超过文件数量或总大小上限'))
    if (!uniqueSkillPaths(merged.map(file => file.path))) throw new Error(tr('文件路径重复或与文件夹冲突'))
    emit('update:modelValue', merged)
    selected.value = additions[0]!.path
  } catch (caught) { error.value = (caught as Error).message }
  finally { uploading.value = false }
}
function removeFile() {
  if (!removeConfirm.value || !current.value || current.value.path === 'SKILL.md' || props.disabled) return
  emit('update:modelValue', props.modelValue.filter(file => file.path !== selected.value))
  selected.value = 'SKILL.md'
}
</script>

<template>
  <div class="skill-package-manager">
    <aside class="package-sidebar" :aria-label="tr('技能文件')">
      <header><strong>{{ tr('文件') }}</strong><span>{{ modelValue.length }}</span></header>
      <div class="file-add-actions">
        <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('新建文件')" :title="tr('新建文件')" :disabled="disabled || uploading" @click="startAction('create')"><FilePlus :size="15" /></AppButton>
        <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('上传文件')" :title="tr('上传文件')" :loading="uploading" :disabled="disabled" @click="upload?.click()"><Upload :size="15" /></AppButton>
        <input ref="upload" type="file" multiple hidden :aria-label="tr('上传文件')" @change="uploadFiles" />
      </div>
      <div class="file-tree-scroll"><SkillFileTree :nodes="tree" :selected="selected" @select="selectFile" /></div>
    </aside>
    <section class="package-file-content" :aria-label="tr('文件内容')">
      <header class="file-header">
        <strong :title="selected">{{ selected }}</strong>
        <div v-if="current" class="file-actions">
          <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('重命名文件')" :title="tr('重命名文件')" :disabled="disabled || current.path === 'SKILL.md'" @click="startAction('rename')"><Pencil :size="14" /></AppButton>
          <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('下载文件')" :title="tr('下载文件')" @click="saveBlob(skillFileBlob(current), current.path.split('/').pop()!)"><Download :size="14" /></AppButton>
          <AppButton type="button" variant="ghost" size="sm" icon-only :aria-label="tr('移除文件')" :title="tr('移除文件')" :disabled="disabled || current.path === 'SKILL.md'" @click="removeConfirm = true"><Trash2 :size="14" /></AppButton>
        </div>
      </header>
      <div v-if="action" class="file-path-form">
        <label :for="`${id}-path`">{{ action === 'create' ? tr('新文件路径') : tr('新文件名或路径') }}</label>
        <div><input :id="`${id}-path`" v-model="path" :placeholder="tr('例如 references/example.md')" maxlength="240" @keydown.enter.prevent="!$event.isComposing && $event.keyCode !== 229 && applyAction()" /><AppButton type="button" variant="secondary" size="sm" @click="applyAction">{{ tr('确定') }}</AppButton><AppButton type="button" variant="ghost" size="sm" @click="action = null">{{ tr('取消') }}</AppButton></div>
      </div>
      <div v-if="removeConfirm" class="file-remove-confirm"><span>{{ tr('从当前草稿移除此文件？保存技能后生效。') }}</span><AppButton type="button" variant="secondary" size="sm" @click="removeFile">{{ tr('确认移除') }}</AppButton><AppButton type="button" variant="ghost" size="sm" @click="removeConfirm = false">{{ tr('取消') }}</AppButton></div>
      <p v-if="error" class="package-error" role="alert">{{ error }}</p>
      <div v-if="current" class="file-editor">
        <SkillMarkdownEditor v-if="current.encoding === 'utf-8'" :key="current.path" :model-value="current.content" :label="current.path" :task="task" :markdown="current.path.toLowerCase().endsWith('.md')" :disabled="disabled" @update:model-value="setContent" />
        <div v-else class="binary-preview">
          <img v-if="imageUrl && !imageFailed" :src="imageUrl" :alt="current.path" @error="imageFailed = true" />
          <p v-if="imageFailed" role="status">{{ tr('图片预览失败，可下载原文件查看。') }}</p>
          <p>{{ tr('二进制文件，随技能包完整保存。') }} {{ Math.ceil(skillFileSize(current) / 1024) }} KB</p>
          <AppButton type="button" variant="secondary" size="sm" @click="saveBlob(skillFileBlob(current), current.path.split('/').pop()!)">{{ tr('下载文件') }}</AppButton>
        </div>
      </div>
      <p v-else class="folder-hint">{{ tr('选择文件进行编辑，或在此目录上传文件。') }}</p>
    </section>
  </div>
</template>

<style scoped>
.skill-package-manager { display: grid; grid-template-columns: minmax(130px, 29%) minmax(0, 1fr); min-block-size: 0; block-size: 100%; color: var(--app-text); }
.package-sidebar { display: flex; flex-direction: column; min-block-size: 0; min-inline-size: 0; padding: 12px 8px; border-inline-end: 1px solid var(--app-border); background: var(--app-canvas); }
.package-sidebar > header { display: flex; align-items: center; gap: 8px; padding: 0 8px; font-size: 12px; } .package-sidebar header span { color: var(--app-text-secondary); font-variant-numeric: tabular-nums; }
.file-add-actions { display: flex; gap: 4px; margin-block: 8px; } .file-tree-scroll { flex: 1; min-block-size: 0; overflow: auto; scrollbar-width: thin; scrollbar-color: var(--app-border-strong) transparent; }
.package-file-content { display: flex; flex-direction: column; min-inline-size: 0; min-block-size: 0; overflow: hidden; }
.file-header { display: flex; align-items: center; gap: 8px; justify-content: space-between; padding: 6px 10px; border-block-end: 1px solid var(--app-border); }
.file-header strong { font-size: 12px; font-weight: 500; min-inline-size: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-actions { display: flex; flex: none; gap: 2px; } .file-editor { flex: 1; min-block-size: 0; }
.file-path-form, .file-remove-confirm { flex: none; padding: 10px; border-block-end: 1px solid var(--app-border); font-size: 12px; } .file-path-form > div, .file-remove-confirm { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
.file-path-form input { flex: 1; min-inline-size: 80px; margin-block-start: 6px; padding: 8px; color: var(--app-text); background: var(--app-surface); border: 1px solid var(--app-border); border-radius: 6px; font: inherit; caret-color: var(--app-accent); }
input:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.binary-preview { box-sizing: border-box; block-size: 100%; overflow: auto; padding: 20px; text-align: center; } .binary-preview img { max-inline-size: 100%; max-block-size: 65%; object-fit: contain; } .binary-preview p { color: var(--app-text-secondary); font-size: 12px; }
.package-error { margin: 0; padding: 8px 10px; color: var(--app-danger, #b33645); font-size: 12px; overflow-wrap: anywhere; }
.folder-hint { color: var(--app-text-secondary); padding: 20px; font-size: 13px; line-height: 1.7; }
.skill-package-manager :deep(.app-button--secondary) { background: var(--app-surface-muted); color: var(--app-text-secondary); box-shadow: inset 0 0 0 1px var(--app-border); }
@media (max-width: 600px) { .skill-package-manager { grid-template-columns: 112px minmax(0, 1fr); } .package-sidebar { padding-inline: 4px; } .file-header { flex-wrap: wrap; gap: 0; } .file-header strong { inline-size: 100%; } }
@media (pointer: coarse) { .file-path-form input { font-size: 16px; min-block-size: 44px; } }
</style>
