<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight,
  Bot,
  Clapperboard,
  FileText,
  Film,
  Layers3,
  Monitor,
  PencilLine,
  SlidersHorizontal,
  Sparkles,
  UploadCloud,
  UserRound,
  X,
} from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import CreationConfigBar from '@/components/CreationConfigBar.vue'
import CreationEntryShell from '@/components/CreationEntryShell.vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import type { StoryboardStrategy } from '@/types'

type CreationMode = 'agent' | 'manual'

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
  { value: 'realistic-general', label: '写实通用', image: '/style-thumbnails/realistic-general.png' },
  { value: 'realistic-urban', label: '写实都市', image: '/style-thumbnails/realistic-urban.png' },
  { value: 'realistic-cinematic', label: '写实电影感', image: '/style-thumbnails/realistic-cinematic.png' },
  { value: 'anime-japanese', label: '2D日漫', image: '/style-thumbnails/anime-japanese.png' },
  { value: 'manhwa-urban', label: '2D韩漫都市', image: '/style-thumbnails/manhwa-urban.png' },
  { value: 'chinese-3d', label: '3D国风', image: '/style-thumbnails/chinese-3d.png' },
  { value: 'xianxia-3d', label: '3D仙侠', image: '/style-thumbnails/xianxia-3d.png' },
  { value: 'manhwa-2d', label: '2D韩漫', image: '/style-thumbnails/manhwa-2d.png' },
  { value: 'otome-2d', label: '2D乙女', image: '/style-thumbnails/otome-2d.png' },
  { value: 'chinese-animation-2d', label: '2D国漫', image: '/style-thumbnails/chinese-animation-2d.png' },
  { value: 'cg', label: 'CG风格', image: '/style-thumbnails/cg.png' },
  { value: 'cartoon-3d', label: '3D卡通', image: '/style-thumbnails/cartoon-3d.png' },
  { value: 'cyberpunk-cg', label: 'CG赛博朋克', image: '/style-thumbnails/cyberpunk-cg.png' },
  { value: 'gongbi', label: '工笔画', image: '/style-thumbnails/gongbi.png' },
  { value: 'custom', label: '自定义风格', separator: true },
]

const visualStyles = ref<VisualStyle[]>(localVisualStyles)
const storyboardStrategies = ref<StoryboardStrategy[]>([])
const fileInput = ref<HTMLInputElement | null>(null)
const router = useRouter()
const selectedFile = ref<File | null>(null)
const dragging = ref(false)
const mode = ref<CreationMode>('agent')
const aspectRatio = ref('9:16')
const resolution = ref('720p')
const styleId = ref('realistic-general')
const storyboardStrategy = ref('cinematic')
const customPrompt = ref('')
const creating = ref(false)

const selectedStyle = computed(() => visualStyles.value.find(item => item.value === styleId.value) ?? visualStyles.value[0])
const selectedStoryboardStrategy = computed(() => storyboardStrategies.value.find(
  item => item.key === storyboardStrategy.value,
))
const storyboardStrategyOptions = computed(() => storyboardStrategies.value.map(item => ({
  value: item.key,
  label: item.name,
})))
const isAgentMode = computed(() => mode.value === 'agent')
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
      label: item.label,
      image: thumbnails.get(item.key),
    }))
    merged.push({ value: 'custom', label: '自定义风格', separator: true })
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
    notice.error('仅支持 doc、docx、txt、pdf 和 md 格式')
    return false
  }
  if (file.size > 20 * 1024 * 1024) {
    notice.error('剧本文件不能超过 20 MB')
    return false
  }
  return true
}

function setFile(file?: File) {
  if (!file || !validateFile(file)) return
  selectedFile.value = file
}

function handleFileChange(event: Event) {
  setFile((event.target as HTMLInputElement).files?.[0])
}

function handleDrop(event: DragEvent) {
  dragging.value = false
  setFile(event.dataTransfer?.files?.[0])
}

function removeFile(event: MouseEvent) {
  event.stopPropagation()
  selectedFile.value = null
  if (fileInput.value) fileInput.value.value = ''
}

async function createProject() {
  if (isAgentMode.value && !selectedFile.value) {
    notice.info('请先上传剧本文件')
    return
  }
  if (styleId.value === 'custom' && !customPrompt.value.trim()) {
    notice.info('请填写自定义风格 Prompt')
    return
  }
  const modeLabel = mode.value === 'agent' ? 'Agent 模式' : '人工模式'
  if (isAgentMode.value && selectedFile.value) {
    const projectName = selectedFile.value.name.replace(/\.[^.]+$/, '') || '未命名短剧'
    creating.value = true
    try {
      const uploaded = await api.upload(selectedFile.value)
      const description = `${modeLabel} · 源剧本：${uploaded.filename}`
      const createPayload: Parameters<typeof api.createNovel>[0] = {
        name: projectName,
        author: 'Agent 创建',
        description,
        aspect_ratio: aspectRatio.value,
        resolution: resolution.value,
        style_key: styleId.value === 'custom' ? null : styleId.value,
        custom_style_prompt: styleId.value === 'custom' ? customPrompt.value.trim() : null,
        storyboard_strategy: storyboardStrategy.value,
        storyboard_setting: selectedStoryboardStrategy.value?.description ?? '',
      }
      if (uploaded.key) {
        // OSS 直传：只回传 key，由服务端经内网读取并解析正文，不再把整份书稿传给浏览器。
        createPayload.source_key = uploaded.key
        createPayload.source_filename = selectedFile.value.name
      } else {
        const textContent = uploaded.text_content?.trim() || ''
        if (!textContent) throw new Error('未能从文件中读取正文，请转换为 TXT、MD、DOCX 或文本型 PDF 后重试')
        if (uploaded.chapter_validation && !uploaded.chapter_validation.valid) {
          throw new Error(uploaded.chapter_validation.message)
        }
        createPayload.content = textContent
      }
      const response = await api.createNovel(createPayload)
      let chapterCount = 0
      try {
        const splitResult = await api.splitNovel(response.data.id)
        chapterCount = splitResult.data.total_chapters || 0
      } catch (error) {
        await api.deleteNovel(response.data.id).catch(() => undefined)
        throw error
      }
      sessionStorage.setItem('short-drama-agent-project', JSON.stringify({
        projectId: response.data.id,
        name: response.data.name,
        aspectRatio: aspectRatio.value,
        resolution: resolution.value,
        style: selectedStyle.value.label,
        styleKey: styleId.value,
        storyboardStrategy: storyboardStrategy.value,
        fileName: selectedFile.value.name,
        sourcePath: uploaded.file_path,
      }))
      notice.success(chapterCount ? `书稿已成功拆分为 ${chapterCount} 章，正在进入 Agent 工作区` : '书稿已上传并完成章节拆分，正在进入 Agent 工作区')
      await router.push({ name: 'short-drama-agent', params: { projectId: response.data.id } })
    } catch (error) {
      notice.error((error as Error).message)
    } finally {
      creating.value = false
    }
    return
  }
  creating.value = true
  try {
    const response = await api.createNovel({
      name: '新项目',
      author: '人工创建',
      description: modeLabel,
      content: '',
      aspect_ratio: aspectRatio.value,
      resolution: resolution.value,
      style_key: styleId.value === 'custom' ? null : styleId.value,
      custom_style_prompt: styleId.value === 'custom' ? customPrompt.value.trim() : null,
      storyboard_strategy: storyboardStrategy.value,
      storyboard_setting: selectedStoryboardStrategy.value?.description ?? '',
    })
    sessionStorage.setItem('short-drama-manual-project', JSON.stringify({
      projectId: response.data.id,
      name: response.data.name,
      aspectRatio: aspectRatio.value,
      resolution: resolution.value,
      style: selectedStyle.value.label,
      styleKey: styleId.value,
      storyboardStrategy: storyboardStrategy.value,
    }))
    notice.success('人工短剧项目已创建，正在进入设定工作区')
    await router.push({ name: 'short-drama-manual', params: { projectId: response.data.id } })
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    creating.value = false
  }
}
</script>

<template>
  <CreationEntryShell
    eyebrow="AI SHORT DRAMA"
    :description="isAgentMode ? '上传完整故事，让 Agent 自动完成内容理解与制作规划。' : '从空白项目开始，手动掌控角色、场景、分镜和镜头细节。'"
  >
    <template #title>翻开剧本，创作<span class="creation-entry-accent">精品短剧</span></template>
      <form class="short-drama-form" @submit.prevent="createProject">
        <Transition name="mode-panel" mode="out-in">
          <AppButton
            v-if="isAgentMode"
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
              <small>{{ formattedFileSize }} · 点击重新选择文件</small>
              <span class="remove-file" role="button" aria-label="移除剧本" tabindex="0" @click="removeFile"><X :size="15" /></span>
            </template>
            <template v-else>
              <span class="dropzone-icon"><UploadCloud :size="27" /></span>
              <strong>点击或拖拽剧本至此</strong>
              <small>支持 doc、docx、txt、pdf 和 md 格式，文件大小不超过 20 MB</small>
            </template>
          </AppButton>

          <section v-else key="manual-start" class="manual-mode-card" aria-labelledby="manual-mode-title">
            <span class="manual-mode-icon"><PencilLine :size="25" /></span>
            <div class="manual-mode-copy">
              <p>MANUAL WORKSPACE</p>
              <h2 id="manual-mode-title">从空白项目开始</h2>
              <span>不上传剧本，进入工作台后手动建立创作内容与生产流程。</span>
            </div>
            <div class="manual-mode-features" aria-label="人工模式能力">
              <span><Layers3 :size="15" />自由搭建</span>
              <span><PencilLine :size="15" />逐步编辑</span>
              <span><SlidersHorizontal :size="15" />精细控制</span>
            </div>
          </section>
        </Transition>

        <CreationConfigBar modes-label="创作模式">
          <template #modes>
            <AppButton type="button" variant="soft" size="sm" :active="mode === 'agent'" @click="mode = 'agent'">
              <Bot :size="15" />Agent 模式
            </AppButton>
            <AppButton type="button" variant="soft" size="sm" :active="mode === 'manual'" @click="mode = 'manual'">
              <UserRound :size="15" />人工模式
            </AppButton>
          </template>

          <AppSelect
            v-model="storyboardStrategy"
            class="strategy-select"
            ariaLabel="分镜策略"
            menu-label="分镜策略"
            :menu-width="220"
            :options="storyboardStrategyOptions"
            :disabled="!storyboardStrategyOptions.length"
          >
            <template #leading><Clapperboard :size="15" /></template>
          </AppSelect>
          <AppSelect v-model="aspectRatio" class="format-select" ariaLabel="画面比例" :options="aspectRatios">
            <template #leading><Film :size="15" /></template>
          </AppSelect>
          <AppSelect v-model="resolution" class="format-select" ariaLabel="分辨率" :options="resolutions">
            <template #leading><Monitor :size="15" /></template>
          </AppSelect>
          <AppSelect
            v-model="styleId"
            class="style-select"
            ariaLabel="视觉风格"
            menu-label="风格"
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

        <div v-if="styleId === 'custom'" class="custom-prompt-panel">
          <label for="custom-style-prompt">自定义风格 Prompt</label>
          <textarea
            id="custom-style-prompt"
            v-model="customPrompt"
            maxlength="2000"
            rows="4"
            placeholder="描述画面质感、色彩、人物造型、灯光和镜头语言，例如：东方电影感，低饱和青绿色调，自然光，细腻皮肤质感……"
          />
          <small>{{ customPrompt.length }} / 2000</small>
        </div>

        <AppButton class="create-short-drama" variant="primary" size="lg" block type="submit" :loading="creating">
          <span>
            <Sparkles v-if="!creating && isAgentMode" :size="18" />
            <PencilLine v-else-if="!creating" :size="18" />
            {{ creating ? '正在创建项目…' : isAgentMode ? '创建 Agent 短剧项目' : '创建人工短剧项目' }}
          </span>
          <ArrowRight class="create-arrow" :size="18" />
        </AppButton>
      </form>
  </CreationEntryShell>
</template>

<style scoped>
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
  border: 1px dashed #d8dbea;
  border-radius: 16px;
  color: #565c6d;
  background: #fbfbfe;
  cursor: pointer;
  transition: border-color .15s ease, background-color .15s ease, box-shadow .15s ease;
}

.script-dropzone:hover,
.script-dropzone.is-dragging {
  border-color: #8586f7;
  background: #f8f8ff;
  box-shadow: 0 12px 34px rgb(91 92 246 / 8%);
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
  color: #4a4f60;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-dropzone small {
  color: #a0a5b4;
  font-size: 11px;
}

.dropzone-icon {
  display: grid;
  width: 50px;
  height: 50px;
  margin-bottom: 3px;
  place-items: center;
  border: 1px solid #e6e7f2;
  border-radius: 14px;
  color: #7779ef;
  background: #fff;
  box-shadow: 0 8px 24px rgb(50 54 73 / 7%);
}

.dropzone-icon.has-file {
  color: #4d9a78;
  background: #f1faf6;
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
  color: #8b90a0;
}

.remove-file:hover {
  color: #dc645a;
  background: #fff0ef;
}

.manual-mode-card {
  display: grid;
  min-height: 220px;
  grid-template-columns: 58px minmax(0, 1fr);
  align-content: center;
  align-items: center;
  gap: 18px 20px;
  padding: 32px 38px;
  border: 1px solid #e1e3f5;
  border-radius: 16px;
  background: #fafaff;
  box-shadow: inset 0 0 0 1px rgb(255 255 255 / 80%);
}

.manual-mode-icon {
  display: grid;
  width: 58px;
  height: 58px;
  place-items: center;
  border: 1px solid #e4e5f4;
  border-radius: 17px;
  color: #6263f5;
  background: #fff;
  box-shadow: 0 10px 28px rgb(54 58 87 / 8%);
}

.manual-mode-copy p {
  margin: 0 0 7px;
  color: #7779ef;
  font-size: 9px;
  font-weight: 750;
  letter-spacing: .15em;
}

.manual-mode-copy h2 {
  margin: 0 0 7px;
  color: #353947;
  font-size: 20px;
  letter-spacing: -.02em;
}

.manual-mode-copy > span {
  color: #9297a7;
  font-size: 12px;
  line-height: 1.65;
}

.manual-mode-features {
  display: flex;
  grid-column: 2;
  flex-wrap: wrap;
  gap: 8px;
}

.manual-mode-features span {
  display: inline-flex;
  min-height: 30px;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid #e7e8f1;
  border-radius: 8px;
  color: #686e7e;
  background: #fff;
  font-size: 11px;
}

.manual-mode-features svg {
  color: #7274ed;
}

.format-select {
  width: 118px;
}

.strategy-select {
  width: 154px;
}

.style-select {
  width: 136px;
}

.select-thumbnail {
  width: 24px;
  height: 24px;
  flex: 0 0 auto;
  border-radius: 6px;
  object-fit: cover;
}

.custom-style-icon {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 6px;
  color: #6466ef;
  background: #eff0ff;
}

.custom-prompt-panel {
  position: relative;
  display: grid;
  gap: 8px;
  margin-top: 12px;
  padding: 14px;
  border: 1px solid #e4e6ed;
  border-radius: 12px;
  background: #fbfbfd;
}

.custom-prompt-panel label {
  color: #505566;
  font-size: 12px;
  font-weight: 600;
}

.custom-prompt-panel textarea {
  width: 100%;
  border: 0;
  outline: 0;
  color: #3e4352;
  background: transparent;
  font-size: 13px;
  line-height: 1.7;
  resize: vertical;
}

.custom-prompt-panel textarea::placeholder {
  color: #a2a7b5;
}

.custom-prompt-panel small {
  justify-self: end;
  color: #a2a7b5;
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
  .script-dropzone { min-height: 190px; padding: 20px 14px; }
  .script-dropzone small { max-width: 270px; line-height: 1.6; }
  .manual-mode-card {
    min-height: 210px;
    grid-template-columns: 1fr;
    justify-items: center;
    gap: 14px;
    padding: 24px 18px;
    text-align: center;
  }
  .manual-mode-features { grid-column: 1; justify-content: center; }
  .strategy-select, .style-select { width: 100%; }
  .create-short-drama { width: 100%; }
}
</style>
