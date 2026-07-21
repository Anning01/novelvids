<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  Boxes,
  Check,
  ImagePlus,
  Library,
  LoaderCircle,
  Search,
  Sparkles,
  Upload,
  UserRound,
  Volume2,
  X,
} from 'lucide-vue-next'
import AppSelect from '@/components/AppSelect.vue'
import { api } from '@/api'
import { notice } from '@/shared/notice'
import { AssetTypeEnum, type AiModelConfig, type Asset, type DigitalHuman } from '@/types'

type AssetKind = 'character' | 'scene' | 'prop'
type CreateMode = 'ai' | 'library' | 'upload'
type LibraryItem = { key: string; name: string; detail: string; image: string; source: 'public' | 'project'; asset?: Asset; human?: DigitalHuman }

const props = defineProps<{ open: boolean; kind: AssetKind; novelId: number }>()
const emit = defineEmits<{ close: []; created: [asset: Asset] }>()

const config = computed(() => ({
  character: { label: '角色', icon: UserRound, type: AssetTypeEnum.PERSON, library: '角色库' },
  scene: { label: '场景', icon: ImagePlus, type: AssetTypeEnum.SCENE, library: '场景库' },
  prop: { label: '道具', icon: Boxes, type: AssetTypeEnum.ITEM, library: '道具库' },
})[props.kind])

const ratios = ['1:1', '3:2', '2:3', '3:4', '4:3', '4:5', '5:4', '16:9', '9:16', '21:9']
const resolutions = ['1K', '2K']
const genderOptions = [
  { value: '', label: '请选择' },
  { value: '男', label: '男' },
  { value: '女', label: '女' },
  { value: '其他（动物）', label: '其他（动物）' },
]
const ageOptions = [
  { value: '', label: '请选择' },
  { value: '儿童', label: '儿童' },
  { value: '少年', label: '少年' },
  { value: '青年', label: '青年' },
  { value: '中年', label: '中年' },
  { value: '老年', label: '老年' },
]

const mode = ref<CreateMode>('ai')
const name = ref('')
const description = ref('')
const prompt = ref('')
const gender = ref('')
const age = ref('')
const voice = ref('')
const ratio = ref('16:9')
const resolution = ref('1K')
const modelId = ref('')
const models = ref<AiModelConfig[]>([])
const libraryItems = ref<LibraryItem[]>([])
const selectedLibraryKey = ref('')
const libraryScope = ref<'all' | 'public' | 'project'>('all')
const search = ref('')
const uploadFile = ref<File | null>(null)
const uploadPreview = ref('')
const dragging = ref(false)
const saving = ref(false)
const loadingLibrary = ref(false)
const loadingMoreLibrary = ref(false)
const publicPage = ref(0)
const publicPages = ref(0)
const projectPage = ref(0)
const projectPages = ref(0)

const modelOptions = computed(() => models.value.map(item => ({ value: String(item.id), label: item.name || item.model || `生图模型 ${item.id}` })))
const filteredLibraryItems = computed(() => libraryItems.value.filter(item => {
  if (libraryScope.value !== 'all' && item.source !== libraryScope.value) return false
  const query = search.value.trim().toLowerCase()
  return !query || `${item.name} ${item.detail}`.toLowerCase().includes(query)
}))
const selectedLibrary = computed(() => libraryItems.value.find(item => item.key === selectedLibraryKey.value))
const publicHasMore = computed(() => props.kind === 'character' && publicPage.value < publicPages.value)
const projectHasMore = computed(() => projectPage.value < projectPages.value)
const libraryHasMore = computed(() => {
  if (libraryScope.value === 'public') return publicHasMore.value
  if (libraryScope.value === 'project') return projectHasMore.value
  return publicHasMore.value || projectHasMore.value
})
const canSubmit = computed(() => {
  if (mode.value === 'library') return Boolean(selectedLibrary.value)
  const characterReady = props.kind !== 'character' || Boolean(gender.value && age.value)
  if (mode.value === 'upload') return Boolean(name.value.trim() && uploadFile.value && characterReady)
  return Boolean(name.value.trim() && prompt.value.trim() && characterReady && modelId.value)
})

function reset() {
  mode.value = 'ai'
  name.value = ''
  description.value = ''
  prompt.value = ''
  gender.value = ''
  age.value = ''
  voice.value = ''
  ratio.value = '16:9'
  resolution.value = '1K'
  selectedLibraryKey.value = ''
  libraryScope.value = 'all'
  search.value = ''
  libraryItems.value = []
  publicPage.value = 0
  publicPages.value = 0
  projectPage.value = 0
  projectPages.value = 0
  uploadFile.value = null
  if (uploadPreview.value) URL.revokeObjectURL(uploadPreview.value)
  uploadPreview.value = ''
}

function appendLibraryItems(items: LibraryItem[]) {
  const existing = new Set(libraryItems.value.map(item => item.key))
  libraryItems.value.push(...items.filter(item => !existing.has(item.key)))
}

async function loadPublicPage(page: number) {
  if (props.kind !== 'character') return
  const response = await api.digitalHumans(page)
  publicPage.value = response.data.pagination.page
  publicPages.value = response.data.pagination.pages
  appendLibraryItems(response.data.items.map(item => ({
    key: `public-${item.id}`,
    name: item.occupation || '公共数字人',
    detail: `${item.country} · ${item.gender} · ${item.age} 岁`,
    image: item.image_url,
    source: 'public' as const,
    human: item,
  })))
}

async function loadProjectPage(page: number) {
  const response = await api.assetLibrary(config.value.type, page, 24)
  projectPage.value = response.data.pagination.page
  projectPages.value = response.data.pagination.pages
  appendLibraryItems(response.data.items
    .filter(item => item.novel_id !== props.novelId && item.main_image)
    .map(item => ({
      key: `project-${item.id}`,
      name: item.canonical_name,
      detail: item.description || '其他项目资产',
      image: item.main_image || '',
      source: 'project' as const,
      asset: item,
    })))
}

async function loadSources() {
  loadingLibrary.value = true
  try {
    const configPromise = api.configs()
    await Promise.all([
      props.kind === 'character' ? loadPublicPage(1) : Promise.resolve(),
      loadProjectPage(1),
    ])
    const configResponse = await configPromise
    models.value = configResponse.data.items.filter(item => item.task_type === 2)
    modelId.value = String(models.value.find(item => item.is_active)?.id || models.value[0]?.id || '')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loadingLibrary.value = false
  }
}

async function loadMoreLibrary() {
  if (loadingLibrary.value || loadingMoreLibrary.value || !libraryHasMore.value) return
  loadingMoreLibrary.value = true
  try {
    const requests: Promise<void>[] = []
    if (libraryScope.value !== 'project' && publicHasMore.value) requests.push(loadPublicPage(publicPage.value + 1))
    if (libraryScope.value !== 'public' && projectHasMore.value) requests.push(loadProjectPage(projectPage.value + 1))
    await Promise.all(requests)
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loadingMoreLibrary.value = false
  }
}

function onLibraryScroll(event: Event) {
  const target = event.currentTarget as HTMLElement
  if (target.scrollHeight - target.scrollTop - target.clientHeight < 140) void loadMoreLibrary()
}

function acceptFile(file?: File) {
  if (!file) return
  if (!['image/jpeg', 'image/png'].includes(file.type)) {
    notice.info('仅支持 JPG、PNG 格式')
    return
  }
  if (file.size > 20 * 1024 * 1024) {
    notice.info('图片不能超过 20MB')
    return
  }
  uploadFile.value = file
  if (uploadPreview.value) URL.revokeObjectURL(uploadPreview.value)
  uploadPreview.value = URL.createObjectURL(file)
  if (!name.value) name.value = file.name.replace(/\.[^.]+$/, '')
}

function onDrop(event: DragEvent) {
  dragging.value = false
  acceptFile(event.dataTransfer?.files[0])
}

async function submit() {
  if (!canSubmit.value || saving.value) return
  saving.value = true
  try {
    let assetName = name.value.trim()
    let assetDescription = description.value.trim()
    let mainImage: string | undefined
    let imageSource = 1
    const metadata: Record<string, unknown> = {
      creation_mode: mode.value,
      aspect_ratio: ratio.value,
      resolution: resolution.value,
      model_config_id: Number(modelId.value) || undefined,
    }

    if (props.kind === 'character') Object.assign(metadata, { gender: gender.value, age_group: age.value, voice: voice.value })

    if (mode.value === 'upload' && uploadFile.value) {
      const uploaded = await api.upload(uploadFile.value)
      mainImage = `/media/${uploaded.filename}`
      imageSource = 2
    }

    if (mode.value === 'library' && selectedLibrary.value) {
      const selected = selectedLibrary.value
      assetName = selected.name
      assetDescription = selected.asset?.description || selected.detail
      mainImage = selected.image
      imageSource = 2
      metadata.library_source = selected.source
      metadata.source_asset_id = selected.asset?.id || selected.human?.asset_id
      if (selected.human) Object.assign(metadata, { gender: selected.human.gender, age: selected.human.age, country: selected.human.country, occupation: selected.human.occupation })
    }

    const response = await api.createAsset({
      novel_id: props.novelId,
      asset_type: config.value.type,
      canonical_name: assetName,
      description: assetDescription,
      base_traits: prompt.value.trim(),
      main_image: mainImage,
      image_source: imageSource,
      metadata,
      is_global: false,
    })

    if (mode.value === 'ai') {
      await api.generateAsset(response.data.id)
      notice.success(`${config.value.label}已创建，正在生成参考图`)
    } else {
      notice.success(`${config.value.label}已添加`)
    }
    emit('created', response.data)
    emit('close')
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    saving.value = false
  }
}

watch(() => props.open, value => {
  if (!value) return
  reset()
  void loadSources()
})
watch(() => props.kind, () => { if (props.open) { reset(); void loadSources() } })
onMounted(() => { if (props.open) void loadSources() })
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="asset-dialog-backdrop" @click.self="emit('close')">
      <form class="asset-dialog" @submit.prevent="submit">
        <header class="asset-dialog__header">
          <span class="asset-dialog__icon"><component :is="config.icon" :size="20" /></span>
          <div><span>PROJECT ASSET</span><h2>新增{{ config.label }}</h2></div>
          <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="关闭" @click="emit('close')"><X :size="18" /></AppButton>
        </header>

        <div class="asset-dialog__body">
          <div class="asset-form-grid" :class="{ 'is-character': kind === 'character' }">
            <label class="asset-field"><span><i>*</i>名称</span><input v-model="name" maxlength="100" placeholder="请输入" /></label>
            <label v-if="kind === 'character'" class="asset-field"><span><i>*</i>性别</span><AppSelect v-model="gender" :options="genderOptions" ariaLabel="选择性别" menu-label="性别" /></label>
            <label v-if="kind === 'character'" class="asset-field"><span><i>*</i>年龄</span><AppSelect v-model="age" :options="ageOptions" ariaLabel="选择年龄阶段" menu-label="年龄" /></label>
            <label v-if="kind === 'character'" class="asset-field"><span>音色选择</span><AppButton type="button" variant="secondary" block @click="notice.info('音频库将在下一步开放选择')"><Volume2 :size="15" />{{ voice || '选择音色' }}</AppButton></label>
          </div>

          <fieldset class="asset-mode">
            <legend><i>*</i>形象生成方式</legend>
            <div>
              <AppButton type="button" variant="ghost" :active="mode === 'ai'" @click="mode = 'ai'"><Sparkles :size="15" />AI 生成</AppButton>
              <AppButton type="button" variant="ghost" :active="mode === 'library'" @click="mode = 'library'"><Library :size="15" />从{{ config.library }}选择</AppButton>
              <AppButton type="button" variant="ghost" :active="mode === 'upload'" @click="mode = 'upload'"><Upload :size="15" />本地上传</AppButton>
            </div>
          </fieldset>

          <template v-if="mode === 'ai'">
            <label class="asset-field"><span><i>*</i>提示词</span><textarea v-model="prompt" rows="5" :placeholder="`描述${config.label}的外观、材质、光影和视角要求`" /></label>
          </template>

          <section v-else-if="mode === 'library'" class="asset-library">
            <header>
              <label><Search :size="16" /><input v-model="search" type="search" :placeholder="`搜索${config.library}`" /></label>
              <nav v-if="kind === 'character'">
                <AppButton v-for="item in [{ value: 'all', label: '全部' }, { value: 'public', label: '公共数字人' }, { value: 'project', label: '项目人物' }]" :key="item.value" type="button" variant="soft" size="sm" :active="libraryScope === item.value" @click="libraryScope = item.value as 'all' | 'public' | 'project'">{{ item.label }}</AppButton>
              </nav>
            </header>
            <div class="asset-library__grid" @scroll.passive="onLibraryScroll">
              <div v-if="loadingLibrary" class="asset-library__state">正在加载资产库…</div>
              <AppButton v-for="item in filteredLibraryItems" v-else :key="item.key" type="button" class="asset-library__card" :active="selectedLibraryKey === item.key" @click="selectedLibraryKey = item.key">
                <img :src="item.image" alt="" loading="lazy" />
                <span><strong>{{ item.name }}</strong><small>{{ item.detail }}</small></span>
                <Check v-if="selectedLibraryKey === item.key" :size="16" />
              </AppButton>
              <div v-if="!loadingLibrary && !filteredLibraryItems.length" class="asset-library__state">暂无可用{{ config.label }}资产</div>
              <div v-if="!loadingLibrary && filteredLibraryItems.length" class="asset-library__paging" role="status" aria-live="polite">
                <template v-if="loadingMoreLibrary"><LoaderCircle :size="15" />正在加载下一页…</template>
                <template v-else-if="libraryHasMore">继续下滑加载更多</template>
                <template v-else>已加载全部</template>
              </div>
            </div>
          </section>

          <label v-else class="asset-upload" :class="{ 'is-dragging': dragging, 'has-file': uploadPreview }" @dragenter.prevent="dragging = true" @dragover.prevent @dragleave.prevent="dragging = false" @drop.prevent="onDrop">
            <input type="file" accept="image/jpeg,image/png" @change="acceptFile(($event.target as HTMLInputElement).files?.[0])" />
            <img v-if="uploadPreview" :src="uploadPreview" alt="上传预览" />
            <template v-else><Upload :size="26" /><strong>点击或拖拽图片到此处上传</strong><span>仅支持 JPG、PNG，最大 20MB</span></template>
          </label>

          <label class="asset-field"><span>{{ config.label }}描述</span><textarea v-model="description" rows="3" placeholder="请输入" /></label>
        </div>

        <footer class="asset-dialog__footer">
          <div v-if="mode === 'ai'" class="asset-generation-options">
            <AppSelect v-model="modelId" :options="modelOptions" ariaLabel="选择生图模型"><template #leading><Sparkles :size="14" /></template></AppSelect>
            <AppSelect v-model="resolution" :options="resolutions" ariaLabel="选择生成分辨率" />
            <AppSelect v-model="ratio" :options="ratios" ariaLabel="选择生成比例" />
          </div>
          <span v-else />
          <div><AppButton type="button" variant="secondary" @click="emit('close')">取消</AppButton><AppButton type="submit" variant="primary" :disabled="!canSubmit" :loading="saving"><Sparkles v-if="!saving && mode === 'ai'" :size="15" />{{ mode === 'ai' ? '开始生成' : '确认添加' }}</AppButton></div>
        </footer>
      </form>
    </div>
  </Teleport>
</template>

<style scoped>
.asset-dialog-backdrop { position: fixed; inset: 0; z-index: 120; display: grid; place-items: center; padding: 24px; background: rgb(35 38 52 / 48%); backdrop-filter: blur(8px); }
.asset-dialog { display: flex; width: min(760px,100%); max-height: min(880px,calc(100vh - 48px)); flex-direction: column; overflow: hidden; border-radius: 24px; background: #fff; box-shadow: 0 32px 100px rgb(25 28 45 / 28%); }
.asset-dialog__header { display: grid; grid-template-columns: 44px 1fr 36px; align-items: center; gap: 12px; padding: 20px 22px 16px; background: linear-gradient(135deg,#fbfbff,#f4f5ff); }
.asset-dialog__icon { display: grid; width: 44px; height: 44px; place-items: center; border-radius: 14px; color: #5b5df0; background: #fff; box-shadow: 0 8px 22px rgb(73 75 159 / 10%); }
.asset-dialog__header > div > span { color: #7779ef; font-size: 9px; font-weight: 800; letter-spacing: .14em; }
.asset-dialog__header h2 { margin: 2px 0 0; color: #292d3a; font-size: 19px; }
.asset-dialog__body { display: grid; gap: 17px; overflow-y: auto; padding: 18px 22px 20px; }
.asset-form-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
.asset-form-grid.is-character { grid-template-columns: 1fr 1fr; }
.asset-field { display: grid; gap: 7px; color: #535968; font-size: 12px; font-weight: 650; }
.asset-field > span i,.asset-mode legend i { margin-right: 3px; color: #ec5e73; font-style: normal; }
.asset-field input,.asset-field textarea { width: 100%; padding: 10px 12px; border: 0; border-radius: 11px; outline: 0; color: #343847; background: #f6f7fa; font: inherit; font-weight: 450; box-shadow: inset 0 0 0 1px transparent; transition: .16s ease; resize: vertical; }
.asset-field input { height: 40px; }
.asset-field input:focus,.asset-field textarea:focus { background: #fff; box-shadow: inset 0 0 0 1px #8587f7,0 0 0 3px rgb(91 93 240 / 9%); }
.asset-field :deep(.app-select__trigger) { min-height: 40px; border: 0; background: #f6f7fa; box-shadow: none; }
.asset-mode { min-width: 0; margin: 0; padding: 0; border: 0; }
.asset-mode legend { margin-bottom: 7px; color: #535968; font-size: 12px; font-weight: 650; }
.asset-mode > div { display: grid; grid-template-columns: repeat(3,1fr); gap: 5px; padding: 4px; border-radius: 13px; background: #f3f4f8; }
.asset-mode :deep(.app-button) { min-height: 38px; color: #646a7a; }
.asset-mode :deep(.app-button.is-active) { color: #5658eb; background: #fff; box-shadow: 0 5px 18px rgb(47 50 80 / 8%); }
.asset-upload { position: relative; display: grid; min-height: 250px; place-items: center; align-content: center; gap: 8px; overflow: hidden; border-radius: 17px; color: #9399a8; background: #fafbfe; box-shadow: inset 0 0 0 1.5px #dde1ef; cursor: pointer; transition: .18s ease; }
.asset-upload:hover,.asset-upload.is-dragging { color: #6567ef; background: #f7f7ff; box-shadow: inset 0 0 0 1.5px #a8a9fa; }
.asset-upload input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.asset-upload strong { color: #515766; font-size: 13px; }
.asset-upload span { font-size: 11px; }
.asset-upload img { width: 100%; height: 300px; object-fit: contain; background: #f2f3f7; }
.asset-library { overflow: hidden; border-radius: 16px; background: #f8f9fc; }
.asset-library > header { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 11px; }
.asset-library > header label { display: flex; min-height: 38px; flex: 1; align-items: center; gap: 8px; padding: 0 11px; border-radius: 10px; color: #9298a7; background: #fff; }
.asset-library > header input { min-width: 0; flex: 1; border: 0; outline: 0; background: transparent; font: inherit; }
.asset-library nav { display: flex; gap: 4px; }
.asset-library__grid { display: grid; max-height: 320px; grid-template-columns: repeat(3,1fr); gap: 10px; overflow-y: auto; padding: 0 11px 11px; }
.asset-library__card { position: relative; display: grid; height: auto; min-height: 0; grid-template-columns: 64px 1fr; gap: 9px; justify-content: stretch; overflow: hidden; padding: 7px; border-radius: 13px; text-align: left; background: #fff; box-shadow: 0 4px 14px rgb(38 42 62 / 5%); }
.asset-library__card.is-active { color: #4f51e6; box-shadow: 0 0 0 2px #7779f4,0 8px 20px rgb(73 75 190 / 12%); }
.asset-library__card img { width: 64px; height: 72px; border-radius: 9px; object-fit: cover; }
.asset-library__card > span { display: grid; min-width: 0; align-content: center; gap: 5px; }
.asset-library__card strong,.asset-library__card small { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-library__card small { color: #969baa; font-size: 10px; font-weight: 450; }
.asset-library__card > svg { position: absolute; top: 7px; right: 7px; padding: 3px; border-radius: 50%; color: #fff; background: #6466ef; }
.asset-library__state { grid-column: 1/-1; display: grid; min-height: 130px; place-items: center; color: #999ead; font-size: 12px; }
.asset-library__paging { display: flex; min-height: 34px; grid-column: 1/-1; align-items: center; justify-content: center; gap: 7px; color: #989dab; font-size: 10px; }
.asset-library__paging svg { animation: asset-library-spin .8s linear infinite; }
@keyframes asset-library-spin { to { transform: rotate(360deg); } }
.asset-dialog__footer { display: flex; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 22px 18px; background: #fbfbfd; box-shadow: 0 -10px 30px rgb(36 40 57 / 4%); }
.asset-dialog__footer > div,.asset-generation-options { display: flex; align-items: center; gap: 8px; }
.asset-generation-options :deep(.app-select:first-child) { width: 190px; }
.asset-generation-options :deep(.app-select) { width: 92px; }
@media (max-width: 720px) {
  .asset-dialog-backdrop { padding: 0; }
  .asset-dialog { width: 100%; max-height: 100vh; min-height: 100vh; border-radius: 0; }
  .asset-form-grid.is-character { grid-template-columns: 1fr; }
  .asset-mode > div,.asset-library__grid { grid-template-columns: 1fr; }
  .asset-library > header,.asset-dialog__footer { align-items: stretch; flex-direction: column; }
  .asset-generation-options { width: 100%; flex-wrap: wrap; }
  .asset-generation-options :deep(.app-select:first-child) { width: 100%; }
}
</style>
