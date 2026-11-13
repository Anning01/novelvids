<script setup lang="ts">
import { tr, dateLocale } from '@/i18n'

import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  Clapperboard,
  FileText,
  Film,
  Monitor,
  PencilLine,
  Sparkles,
  UploadCloud,
  X,
} from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppSegmentedSwitch from '@/components/AppSegmentedSwitch.vue'
import AppSelect from '@/components/AppSelect.vue'
import CreationConfigBar from '@/components/CreationConfigBar.vue'
import CreationEntryShell from '@/components/CreationEntryShell.vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import type { StoryboardStrategy } from '@/types'

interface VisualStyle {
  value: string
  label: string
  image?: string
  separator?: boolean
}

const aspectRatios = ['16:9', '4:3', '3:4', '9:16', '21:9']
const resolutions = ['480p', '720p', '1080p', '4k']
// 本地缩略图与回退列表；后端 /api/config/visual-styles 是风格唯一事实来源
const localVisualStyles: VisualStyle[] = [
  { value: 'realistic-general', get label() { return tr('写实通用') }, image: '/style-thumbnails/realistic-general.png' },
  { value: 'realistic-urban', get label() { return tr('写实都市') }, image: '/style-thumbnails/realistic-urban.png' },
  { value: 'realistic-cinematic', get label() { return tr('写实电影感') }, image: '/style-thumbnails/realistic-cinematic.png' },
  { value: 'anime-japanese', get label() { return tr('2D日漫') }, image: '/style-thumbnails/anime-japanese.png' },
  { value: 'manhwa-urban', get label() { return tr('2D韩漫都市') }, image: '/style-thumbnails/manhwa-urban.png' },
  { value: 'chinese-3d', get label() { return tr('3D国风') }, image: '/style-thumbnails/chinese-3d.png' },
  { value: 'xianxia-3d', get label() { return tr('3D仙侠') }, image: '/style-thumbnails/xianxia-3d.png' },
  { value: 'manhwa-2d', get label() { return tr('2D韩漫') }, image: '/style-thumbnails/manhwa-2d.png' },
  { value: 'otome-2d', get label() { return tr('2D乙女') }, image: '/style-thumbnails/otome-2d.png' },
  { value: 'chinese-animation-2d', get label() { return tr('2D国漫') }, image: '/style-thumbnails/chinese-animation-2d.png' },
  { value: 'cg', get label() { return tr('CG风格') }, image: '/style-thumbnails/cg.png' },
  { value: 'cartoon-3d', get label() { return tr('3D卡通') }, image: '/style-thumbnails/cartoon-3d.png' },
  { value: 'cyberpunk-cg', get label() { return tr('CG赛博朋克') }, image: '/style-thumbnails/cyberpunk-cg.png' },
  { value: 'gongbi', get label() { return tr('工笔画') }, image: '/style-thumbnails/gongbi.png' },
  { value: 'custom', get label() { return tr('自定义风格') }, separator: true },
]

const visualStyles = ref<VisualStyle[]>(localVisualStyles)
const storyboardStrategies = ref<StoryboardStrategy[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const router = useRouter()
const selectedFile = ref<File | null>(null)
const sourceMode = ref<'file' | 'text'>('file')
const storyText = ref('')
const sourceKind = ref<'novel' | 'screenplay'>('novel')
const storyTitle = ref('')
const createProgress = ref('')
const createError = ref('')
const importedProjectId = ref<number | null>(null)
const dragging = ref(false)
const aspectRatio = ref('16:9')
const resolution = ref('720p')
const styleId = ref('realistic-general')
const storyboardStrategy = ref('cinematic')
const customPrompt = ref('')
const creating = ref(false)
const elapsedSeconds = ref(0)
watch(creating, (pending, _previous, onCleanup) => {
  if (!pending) return
  elapsedSeconds.value = 0
  const startedAt = Date.now()
  const timer = window.setInterval(() => {
    elapsedSeconds.value = Math.floor((Date.now() - startedAt) / 1000)
  }, 1000)
  onCleanup(() => window.clearInterval(timer))
})

const selectedStyle = computed(() => visualStyles.value.find(item => item.value === styleId.value) ?? visualStyles.value[0])
const selectedStoryboardStrategy = computed(() => storyboardStrategies.value.find(
  item => item.key === storyboardStrategy.value,
))
const storyboardStrategyOptions = computed(() => storyboardStrategies.value.map(item => ({
  value: item.key,
  get label() { return tr(item.name) },
})))
const recoveryLabel = computed(() => sourceKind.value === 'novel' ? tr('继续识别章节') : tr('继续进入项目'))
const formattedFileSize = computed(() => {
  if (!selectedFile.value) return ''
  const megabytes = selectedFile.value.size / 1024 / 1024
  return megabytes >= 1 ? `${megabytes.toFixed(1)} MB` : `${Math.max(1, Math.round(selectedFile.value.size / 1024))} KB`
})

async function loadVisualStyles() {
  try {
    const response = await api.visualStyles()
    const thumbnails = new Map(localVisualStyles.map(item => [item.value, item.image]))
    const merged: VisualStyle[] = response.data.map(item => ({
      value: item.key,
      get label() { return tr(item.label) },
      image: thumbnails.get(item.key),
    }))
    merged.push({ value: 'custom', get label() { return tr('自定义风格') }, separator: true })
    visualStyles.value = merged
    // 若当前选中风格已被后端移除，回退到第一项
    if (!merged.some(item => item.value === styleId.value)) styleId.value = merged[0].value
  } catch {
    // 拉取失败时静默使用本地列表
  }
}

async function loadStoryboardStrategies() {
  try {
    const response = await api.storyboardStrategies()
    storyboardStrategies.value = response.data
    if (!response.data.some(item => item.key === storyboardStrategy.value)) {
      storyboardStrategy.value = response.data.find(item => item.is_default)?.key
        ?? response.data[0]?.key
        ?? storyboardStrategy.value
    }
  } catch {
    // 策略由后端统一提供；请求失败时保留默认 key，创建接口仍可安全回退。
  }
}

onMounted(() => {
  void Promise.all([loadVisualStyles(), loadStoryboardStrategies()])
})

function chooseFile() {
  fileInput.value?.click()
}

function validateFile(file: File) {
  const extension = file.name.split('.').pop()?.toLowerCase()
  if (!extension || !['doc', 'docx', 'txt', 'pdf', 'md'].includes(extension)) {
    notice.error(tr('仅支持 doc、docx、txt、pdf 和 md 格式'))
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    notice.error(tr('剧本文件不能超过 20 MB'))
    return false
  }
  return true
}

function setFile(file?: File) {
  if (creating.value || !file || !validateFile(file)) return
  selectedFile.value = file
}

function handleFileChange(event: Event) {
  setFile((event.target as HTMLInputElement).files?.[0])
}

function handleDrop(event: DragEvent) {
  dragging.value = false
  setFile(event.dataTransfer?.files?.[0])
}

function removeFile(event: Event) {
  event.stopPropagation()
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function createProject() {
  if (creating.value) return
  if (importedProjectId.value) { await resumeImport(); return }
  createError.value = ''
  if (sourceMode.value === 'file' ? !selectedFile.value : !storyText.value.trim()) {
    notice.info(sourceMode.value === 'file' ? tr('请先上传剧本文件') : tr('请先粘贴小说或剧本正文'))
    return
  }
  if (styleId.value === 'custom' && !customPrompt.value.trim()) {
    notice.info(tr('请填写自定义画面风格'))
    return
  }
  const projectName = storyTitle.value.trim()
    || (sourceMode.value === 'file' ? selectedFile.value?.name.replace(/\.[^.]+$/, '') : '')
    || tr('未命名短剧')
  creating.value = true
  try {
    createProgress.value = sourceMode.value === 'file' ? tr('正在上传并读取书稿…') : tr('正在保存内容…')
    const uploaded = sourceMode.value === 'file' ? await api.upload(selectedFile.value!) : null
    const sourceName = uploaded?.filename || `${projectName}.txt`
    const createPayload: Parameters<typeof api.createNovel>[0] = {
      name: projectName,
      author: 'Agent 创建',
      content: '',
      aspect_ratio: aspectRatio.value,
      resolution: resolution.value,
      style_key: styleId.value === 'custom' ? null : styleId.value,
      custom_style_prompt: styleId.value === 'custom' ? customPrompt.value.trim() : null,
      storyboard_strategy: storyboardStrategy.value,
      storyboard_setting: selectedStoryboardStrategy.value?.description ?? '',
    }
    createPayload.source_kind = sourceKind.value
    createPayload.description = `源剧本：${sourceName}`
    if (uploaded?.key) {
      // OSS 直传：只回传 key，由服务端经内网读取并解析正文，不再把整份书稿传给浏览器。
      createPayload.source_key = uploaded.key
      createPayload.source_filename = selectedFile.value!.name
    } else if (uploaded) {
      const textContent = uploaded.text_content?.trim() || ''
      if (!textContent) throw new Error(tr('未能从文件中读取正文，请转换为 TXT、MD、DOCX 或文本型 PDF 后重试'))
      if (sourceKind.value === 'novel' && uploaded.chapter_validation && !uploaded.chapter_validation.valid) {
        throw new Error(uploaded.chapter_validation.message)
      }
      createPayload.content = textContent
    } else {
      createPayload.content = storyText.value.trim()
    }
    createProgress.value = tr('正在创建项目…')
    const response = await api.createNovel(createPayload)
    importedProjectId.value = response.data.id
    let chapterCount = response.data.total_chapters || 0
    if (sourceKind.value === 'novel') {
      createProgress.value = tr('正在识别章节，请稍候…')
      const splitResult = await api.splitNovel(response.data.id)
      chapterCount = splitResult.data.total_chapters || 0
    }
    sessionStorage.setItem('short-drama-agent-project', JSON.stringify({
      projectId: response.data.id,
      name: response.data.name,
      aspectRatio: aspectRatio.value,
      resolution: resolution.value,
      style: selectedStyle.value.label,
      styleKey: styleId.value,
      storyboardStrategy: storyboardStrategy.value,
      fileName: sourceName,
      sourcePath: uploaded?.file_path,
    }))
    notice.success(sourceKind.value === 'screenplay' ? tr('剧本已导入，可直接提取资产和生成分镜') : chapterCount ? tr('已识别 {p0} 章，正在进入工作区', { p0: chapterCount }) : tr('内容已保存，正在进入工作区'))
    await router.push({ name: 'short-drama-agent', params: { projectId: response.data.id } })
  } catch (error) {
    createError.value = error instanceof Error ? error.message : tr('创建失败，请重试')
    notice.error(createError.value)
  } finally {
    creating.value = false
  }
}

async function resumeImport() {
  const projectId = importedProjectId.value
  if (!projectId || creating.value) return
  creating.value = true
  createError.value = ''
  createProgress.value = tr('正在恢复已保存项目…')
  try {
    // A lost response may hide a successful split. Inspect the same project
    // before retrying so neither the book nor its chapters are duplicated.
    if (sourceKind.value === 'novel') {
      const chapters = await api.chaptersPage(projectId, 1, 1)
      if (!chapters.data.pagination.total) {
        createProgress.value = tr('正在继续识别章节…')
        await api.splitNovel(projectId)
      }
    }
    await router.push({ name: 'short-drama-agent', params: { projectId } })
  } catch (error) {
    createError.value = error instanceof Error ? error.message : tr('暂时无法继续识别，请重试')
  } finally { creating.value = false }
}
</script>

<template>
  <CreationEntryShell
    eyebrow="AI SHORT DRAMA"
    :description="tr('把小说或剧本带入工作区，逐集制作短剧')"
    width="wide"
  >
    <template #title>{{ tr('翻开剧本，创作') }}<span class="creation-entry-accent">{{ tr('精品短剧') }}</span></template>
      <form class="short-drama-form" :aria-busy="creating" @submit.prevent="createProject">
          <nav class="story-source-tabs" :aria-label="tr('正文导入方式')">
            <AppButton variant="ghost" size="sm" type="button" :active="sourceMode === 'file'" :disabled="creating || Boolean(importedProjectId)" @click="sourceMode = 'file'"><UploadCloud :size="15" />{{ tr('上传文件') }}</AppButton>
            <AppButton variant="ghost" size="sm" type="button" :active="sourceMode === 'text'" :disabled="creating || Boolean(importedProjectId)" @click="sourceMode = 'text'"><PencilLine :size="15" />{{ tr('粘贴正文') }}</AppButton>
          </nav>
          <Transition name="mode-panel" mode="out-in">
            <AppButton
              v-if="sourceMode === 'file'"
              :disabled="creating || Boolean(importedProjectId)"
              key="agent-upload"
              type="button"
              variant="ghost"
              block
              class="script-dropzone"
              :class="{ 'is-dragging': dragging, 'has-file': selectedFile }"
              @click="chooseFile"
              @dragenter.prevent="dragging = true"
              @dragover.prevent="dragging = true"
              @dragleave.prevent="dragging = false"
              @drop.prevent="handleDrop"
            >
              <input ref="fileInput" type="file" accept=".doc,.docx,.txt,.pdf,.md" @change="handleFileChange" />
              <template v-if="selectedFile">
                <span class="dropzone-icon has-file"><FileText :size="25" /></span>
                <strong>{{ selectedFile.name }}</strong>
                <small>{{ formattedFileSize }} {{ tr('· 点击重新选择文件') }}</small>
                <span class="remove-file" role="button" :aria-label="tr('移除剧本')" tabindex="0" @click="removeFile" @keydown.enter.prevent="removeFile" @keydown.space.prevent="removeFile"><X :size="15" /></span>
              </template>
              <template v-else>
                <span class="dropzone-icon"><UploadCloud :size="27" /></span>
                <strong>{{ sourceKind === 'screenplay' ? tr('点击或拖拽剧本至此') : tr('点击或拖拽小说原文至此') }}</strong>
                <small>{{ tr('支持 doc、docx、txt、pdf 和 md 格式，文件大小不超过 20 MB') }}</small>
              </template>
            </AppButton>

            <div v-else key="text-input" class="story-text-input">
              <label for="story-content">{{ sourceKind === 'screenplay' ? tr('剧本正文') : tr('小说原文') }}</label><textarea id="story-content" v-model="storyText" :disabled="creating || Boolean(importedProjectId)" rows="9" maxlength="2000000" :placeholder="sourceKind === 'screenplay' ? tr('粘贴现成剧本，可用“第一集”“第二集”划分分集，导入后直接提取资产和生成分镜。') : tr('将正文粘贴到这里，保留“第一章”“第二章”等章节标题，便于逐章创作。')" />
              <small>{{ storyText.length.toLocaleString(dateLocale) }} {{ tr('字') }}</small>
            </div>
          </Transition>

        <CreationConfigBar :modes-label="tr('内容类型')">
          <template #modes>
            <AppSegmentedSwitch v-model="sourceKind" class="source-kind-switch"
              :items="[{value:'novel',label:tr('小说原文')},{value:'screenplay',label:tr('现成剧本')}]"
              :label="tr('内容类型')" :disabled="creating || Boolean(importedProjectId)" />
          </template>

          <AppSelect
            v-model="storyboardStrategy"
            class="strategy-select"
            :ariaLabel="tr('分镜策略')"
            :menu-label="tr('分镜策略')"
            :menu-width="220"
            :options="storyboardStrategyOptions"
            :disabled="creating || Boolean(importedProjectId) || !storyboardStrategyOptions.length"
          >
            <template #leading><Clapperboard :size="15" /></template>
          </AppSelect>
          <AppSelect :disabled="creating || Boolean(importedProjectId)" v-model="aspectRatio" class="format-select" :ariaLabel="tr('画面比例')" :options="aspectRatios">
            <template #leading><Film :size="15" /></template>
          </AppSelect>
          <AppSelect :disabled="creating || Boolean(importedProjectId)" v-model="resolution" class="format-select" :ariaLabel="tr('分辨率')" :options="resolutions">
            <template #leading><Monitor :size="15" /></template>
          </AppSelect>
          <AppSelect
            v-model="styleId"
            :disabled="creating || Boolean(importedProjectId)"
            class="style-select"
            :ariaLabel="tr('视觉风格')"
            :menu-label="tr('风格')"
            :menu-width="230"
            :max-menu-height="404"
            align="end"
            :options="visualStyles"
          >
            <template #leading="{ option }">
              <img v-if="option.image" class="select-thumbnail" :src="option.image" alt="" />
              <span v-else class="custom-style-icon"><Sparkles :size="16" /></span>
            </template>
            <template #option-leading="{ option }">
              <img v-if="option.image" class="select-thumbnail" :src="option.image" alt="" />
              <span v-else class="custom-style-icon"><Sparkles :size="16" /></span>
            </template>
          </AppSelect>
        </CreationConfigBar>

        <label class="project-name-field" for="story-title">
          <span>{{ tr('项目名称') }}</span>
          <input id="story-title" v-model="storyTitle" :disabled="creating || Boolean(importedProjectId)" maxlength="80" :placeholder="tr('给这个故事起个名字')" />
        </label>

        <div v-if="styleId === 'custom'" class="custom-prompt-panel">
          <label for="custom-style-prompt">{{ tr('自定义画面风格') }}</label>
          <textarea
            id="custom-style-prompt"
            v-model="customPrompt"
            :disabled="creating || Boolean(importedProjectId)"
            maxlength="2000"
            rows="4"
            :placeholder="tr('描述画面质感、色彩、人物造型、灯光和镜头语言，例如：东方电影感，低饱和青绿色调，自然光，细腻皮肤质感……')"
          />
          <small>{{ customPrompt.length }} / 2000</small>
        </div>

        <p v-if="createError" class="story-import-error" role="alert">{{ createError }}。{{ importedProjectId ? tr('项目已保存，可以继续。') : tr('正文和选择已保留，可以调整后重试。') }}</p>
        <p v-if="creating" class="story-import-progress" role="status">{{ createProgress }} · {{ tr('已用 {p0} 秒', { p0: elapsedSeconds }) }}</p>
        <AppButton class="create-short-drama" variant="primary" size="lg" block type="submit" :loading="creating">
          <span>
            <Sparkles v-if="!creating" :size="18" />
            {{ creating ? createProgress || tr('正在创建项目…') : importedProjectId ? recoveryLabel : tr('创建短剧项目') }}
          </span>
          <ArrowRight class="create-arrow" :size="18" />
        </AppButton>
      </form>
  </CreationEntryShell>
</template>

<style scoped>
.story-source-tabs { display: flex; flex-wrap: wrap; gap: 8px; padding-bottom: 12px; }
.story-import-progress { color: var(--app-text-secondary); font-size: 12px; line-height: 1.7; }
.story-text-input { display: grid; gap: 8px; padding: 18px 20px; border: 1px solid var(--app-border); border-radius: 16px; background: var(--app-surface); }
.story-text-input label { color: var(--app-text-secondary); font-size: 12px; font-weight: 600; }
.story-text-input textarea { width: 100%; min-width: 0; min-height: 220px; padding: 0; border: 0; outline: 0; color: var(--app-text); background: transparent; font: inherit; font-size: 13px; line-height: 1.8; resize: vertical; }
.story-text-input small { color: var(--app-text-muted); font-size: 11px; line-height: 1.7; }
.project-name-field { display: flex; min-height: 44px; align-items: center; gap: 12px; margin-top: 10px; padding: 0 14px; border: 1px solid var(--app-border); border-radius: 12px; background: var(--app-surface); box-shadow: var(--app-shadow); }
.project-name-field span { flex: 0 0 auto; color: var(--app-text-secondary); font-size: 11px; font-weight: 650; }
.project-name-field input { min-width: 0; flex: 1; border: 0; outline: 0; color: var(--app-text); background: transparent; font: inherit; font-size: 12px; }
.project-name-field input::placeholder { color: var(--app-text-muted); }
.project-name-field:focus-within,.story-text-input:focus-within { border-color: var(--app-accent); box-shadow: 0 0 0 2px var(--app-accent-soft); }
.project-name-field input:disabled { opacity: .6; }
.story-import-error { padding: 12px; border: 1px solid var(--app-border); border-radius: 10px; color: var(--creation-danger); font-size: 13px; line-height: 1.7; }

.short-drama-form {
  display: grid;
}

.script-dropzone {
  position: relative;
  display: grid;
  min-height: 220px;
  place-items: center;
  align-content: center;
  gap: 9px;
  padding: 26px;
  border: 1px dashed var(--app-border-strong);
  border-radius: 16px;
  color: var(--app-text-secondary);
  background: var(--app-surface);
  cursor: pointer;
  transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease;
}

.script-dropzone:hover,
.script-dropzone.is-dragging {
  border-color: var(--app-accent);
  background: var(--app-accent-soft);
  box-shadow: var(--app-shadow);
}

.script-dropzone.has-file {
  border-style: solid;
}

.script-dropzone input {
  display: none;
}

.script-dropzone strong {
  max-width: 80%;
  overflow: hidden;
  color: var(--app-text);
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-dropzone small {
  color: var(--app-text-secondary);
  font-size: 11px;
}

.dropzone-icon {
  display: grid;
  width: 50px;
  height: 50px;
  margin-bottom: 3px;
  place-items: center;
  border: 1px solid var(--app-border);
  border-radius: 14px;
  color: var(--app-accent);
  background: var(--app-surface-muted);
  box-shadow: var(--app-shadow);
}

.dropzone-icon.has-file {
  color: var(--creation-success);
  background: color-mix(in srgb, var(--creation-success) 10%, var(--app-surface));
}

.remove-file {
  position: absolute;
  top: 14px;
  right: 14px;
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  border-radius: 8px;
  color: var(--app-text-secondary);
}

.remove-file:hover {
  color: var(--creation-danger);
  background: color-mix(in srgb, var(--creation-danger) 10%, var(--app-surface));
}

.custom-prompt-panel {
  position: relative;
  display: grid;
  gap: 8px;
  margin-top: 12px;
  padding: 14px;
  border: 1px solid var(--app-border);
  border-radius: 12px;
  background: var(--app-surface);
}

.custom-prompt-panel label {
  color: var(--app-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.custom-prompt-panel textarea {
  width: 100%;
  border: 0;
  outline: 0;
  color: var(--app-text);
  background: transparent;
  font-size: 13px;
  line-height: 1.7;
  resize: vertical;
}

.custom-prompt-panel textarea::placeholder {
  color: var(--app-text-muted);
}

.custom-prompt-panel small {
  justify-self: end;
  color: var(--app-text-muted);
  font-size: 10px;
}

.create-short-drama {
  position: relative;
  display: inline-flex;
  width: 100%;
  min-height: 52px;
  align-items: center;
  justify-content: center;
  margin-top: 14px;
  padding: 0 52px;
  border: 1px solid #5354ed;
  border-radius: 13px;
  color: #fff;
  background: #5b5cf6;
  box-shadow: 0 14px 30px rgb(91 92 246 / 22%);
  cursor: pointer;
  font-size: 14px;
  font-weight: 700;
  transition: transform .15s ease, background-color .15s ease, box-shadow .15s ease;
}

.create-short-drama > span {
  display: inline-flex;
  align-items: center;
  gap: 9px;
}

.create-arrow {
  position: absolute;
  right: 20px;
}

.create-short-drama:hover {
  background: #4c4de8;
  box-shadow: 0 16px 34px rgb(91 92 246 / 28%);
  transform: translateY(-1px);
}

.create-short-drama:disabled {
  cursor: wait;
  opacity: .68;
  transform: none;
}

.create-short-drama:active {
  transform: translateY(0);
}

.mode-panel-enter-active,
.mode-panel-leave-active {
  transition: opacity .16s ease, transform .16s ease;
}

.mode-panel-enter-from,
.mode-panel-leave-to {
  opacity: 0;
  transform: translateY(5px);
}

@media (max-width: 620px) {
  .script-dropzone { min-height: 190px; padding: 18px 14px; }
  .project-name-field { align-items: flex-start; flex-direction: column; gap: 4px; padding: 10px 12px; }
  .project-name-field input { width: 100%; }
  .script-dropzone small { max-width: 270px; line-height: 1.6; }
  .strategy-select, .style-select { width: 100%; }
  .create-short-drama { width: 100%; }
}
</style>
