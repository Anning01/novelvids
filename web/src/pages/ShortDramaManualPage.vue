<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  BookOpenText,
  Boxes,
  Check,
  Clapperboard,
  Film,
  ImagePlus,
  Layers3,
  LoaderCircle,
  Pencil,
  Plus,
  RefreshCw,
  Settings2,
  Trash2,
  UsersRound,
  Video,
} from 'lucide-vue-next'
import AssetCreateDialog from '@/components/AssetCreateDialog.vue'
import AssetBatchGenerateDialog from '@/components/AssetBatchGenerateDialog.vue'
import { api, sleep } from '@/api'
import { notice } from '@/shared/notice'
import { readShortDramaSettings } from '@/shared/shortDramaProject'
import { AssetTypeEnum, TaskStatusEnum, type Asset } from '@/types'

type AssetTab = 'character' | 'scene' | 'prop'

interface ManualProjectMeta {
  projectId?: number
  name: string
  aspectRatio: string
  resolution: string
  style: string
  creationMode: 'agent' | 'manual'
}

const fallbackProject: ManualProjectMeta = {
  name: '新项目',
  aspectRatio: '9:16',
  resolution: '720p',
  style: '写实通用',
  creationMode: 'manual',
}

function readProjectMeta(): ManualProjectMeta {
  try {
    const stored = sessionStorage.getItem('short-drama-manual-project')
    return stored ? { ...fallbackProject, ...JSON.parse(stored) } : fallbackProject
  } catch {
    return fallbackProject
  }
}

const route = useRoute()
const router = useRouter()
const projectId = computed(() => Number(route.params.projectId))
const project = ref(readProjectMeta())
const assets = ref<Asset[]>([])
const activeTab = ref<AssetTab>('character')
const editingName = ref(false)
const nameDraft = ref('')
const loading = ref(true)
const showAssetDialog = ref(false)
const editingAsset = ref<Asset | null>(null)
const showBatchDialog = ref(false)
const batchGenerating = ref(false)
const generatingAssetIds = ref(new Set<number>())
const failedAssetIds = ref(new Set<number>())
let pageAlive = true

const terminalTaskStatuses = new Set([
  TaskStatusEnum.COMPLETED,
  TaskStatusEnum.FAILED,
  TaskStatusEnum.CANCELLED,
])

const tabs = [
  { value: 'character' as const, label: '角色', icon: UsersRound, type: AssetTypeEnum.PERSON },
  { value: 'scene' as const, label: '场景', icon: ImagePlus, type: AssetTypeEnum.SCENE },
  { value: 'prop' as const, label: '道具', icon: Boxes, type: AssetTypeEnum.ITEM },
]

const phases = computed(() => [
  ...(project.value.creationMode === 'agent' ? [{ label: '剧本', icon: BookOpenText }] : []),
  { label: '设定', icon: Settings2, active: true },
  { label: '分镜', icon: Clapperboard },
  { label: '视频', icon: Video, disabled: true },
])

const activeTabConfig = computed(() => tabs.find(item => item.value === activeTab.value) ?? tabs[0])
const visibleAssets = computed(() => assets.value.filter(item => item.asset_type === activeTabConfig.value.type))
const completedCount = computed(() => visibleAssets.value.filter(item => item.main_image).length)
const generatingCount = computed(() => visibleAssets.value.filter(item => generatingAssetIds.value.has(item.id)).length)
const failedCount = computed(() => visibleAssets.value.filter(item => failedAssetIds.value.has(item.id)).length)

async function loadProject() {
  if (!Number.isFinite(projectId.value) || projectId.value <= 0) return
  try {
    const [projectResponse, assetResponse] = await Promise.all([
      api.novel(projectId.value),
      api.assets(projectId.value),
    ])
    const settings = readShortDramaSettings(projectResponse.data)
    project.value = {
      ...project.value,
      projectId: projectResponse.data.id,
      name: projectResponse.data.name,
      aspectRatio: settings.aspectRatio || project.value.aspectRatio,
      resolution: settings.resolution || project.value.resolution,
      style: settings.style || project.value.style,
      creationMode: projectResponse.data.author?.includes('Agent') ? 'agent' : 'manual',
    }
    assets.value = assetResponse.data.items
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

function startRename() {
  nameDraft.value = project.value.name
  editingName.value = true
}

async function saveName() {
  const nextName = nameDraft.value.trim()
  if (!nextName || nextName === project.value.name) {
    editingName.value = false
    return
  }
  try {
    const response = await api.updateNovel(projectId.value, { name: nextName })
    project.value.name = response.data.name
    editingName.value = false
    notice.success('项目名称已更新')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

function openAssetDialog(asset?: Asset) {
  editingAsset.value = asset || null
  showAssetDialog.value = true
}

function closeAssetDialog() {
  showAssetDialog.value = false
  editingAsset.value = null
}

function addCreatedAsset(asset: Asset) {
  assets.value.unshift(asset)
}

function saveEditedAsset(asset: Asset) {
  assets.value = assets.value.map(item => item.id === asset.id ? asset : item)
}

async function removeAsset(asset: Asset) {
  try {
    await api.deleteAsset(asset.id)
    assets.value = assets.value.filter(item => item.id !== asset.id)
    notice.success('资产已删除')
  } catch (error) {
    notice.error((error as Error).message)
  }
}

function setAssetGenerating(assetId: number, value: boolean) {
  const next = new Set(generatingAssetIds.value)
  value ? next.add(assetId) : next.delete(assetId)
  generatingAssetIds.value = next
}

function setAssetFailed(assetId: number, value: boolean) {
  const next = new Set(failedAssetIds.value)
  value ? next.add(assetId) : next.delete(assetId)
  failedAssetIds.value = next
}

async function generateAssetAndWait(asset: Asset) {
  setAssetGenerating(asset.id, true)
  setAssetFailed(asset.id, false)
  try {
    let task = (await api.generateAsset(asset.id)).data
    while (pageAlive && !terminalTaskStatuses.has(task.status)) {
      await sleep(2000)
      task = (await api.task(task.id)).data
    }
    if (!pageAlive) return false
    const completed = task.status === TaskStatusEnum.COMPLETED
    setAssetFailed(asset.id, !completed)
    return completed
  } catch {
    setAssetFailed(asset.id, true)
    return false
  } finally {
    setAssetGenerating(asset.id, false)
  }
}

async function batchGenerateAssets(options: { assetIds: number[]; modelConfigId: number; concurrency: number; resolution: string; ratio: string }) {
  if (batchGenerating.value) return
  const selected = new Set(options.assetIds)
  const targets = visibleAssets.value.filter(asset => selected.has(asset.id) && !asset.main_image && !generatingAssetIds.value.has(asset.id))
  if (!targets.length) return

  showBatchDialog.value = false
  batchGenerating.value = true
  try {
    const preparedAssets = await Promise.all(targets.map(async asset => {
      const metadata = {
        ...(asset.metadata || {}),
        model_config_id: options.modelConfigId,
        resolution: options.resolution,
        aspect_ratio: options.ratio,
      }
      const updated = (await api.updateAsset(asset.id, { metadata })).data
      assets.value = assets.value.map(item => item.id === updated.id ? updated : item)
      return updated
    }))
    const concurrency = Math.max(1, Math.min(4, options.concurrency || 1, preparedAssets.length))
    let cursor = 0
    let succeeded = 0
    let failed = 0
    const worker = async () => {
      while (pageAlive) {
        const asset = preparedAssets[cursor++]
        if (!asset) return
        const completed = await generateAssetAndWait(asset)
        completed ? succeeded++ : failed++
      }
    }
    await Promise.all(Array.from({ length: concurrency }, () => worker()))
    if (!pageAlive) return
    await loadProject()
    if (failed) notice.info(`批量生成完成：成功 ${succeeded} 个，失败 ${failed} 个`)
    else notice.success(`${succeeded} 个${activeTabConfig.value.label}参考图已生成`)
  } catch (error) {
    notice.error((error as Error).message)
  } finally {
    batchGenerating.value = false
  }
}

function goToStoryboard() {
  void router.push({
    path: `/create/short-drama/storyboard/${projectId.value}`,
    query: route.query.chapter ? { chapter: String(route.query.chapter) } : undefined,
  })
}

function selectPhase(label: string) {
  if (label === '剧本' && project.value.creationMode === 'agent') {
    void router.push({
      path: `/create/short-drama/agent/${projectId.value}`,
      query: route.query.chapter ? { chapter: String(route.query.chapter) } : undefined,
    })
  } else if (label === '分镜') {
    goToStoryboard()
  }
}

onMounted(loadProject)
onBeforeUnmount(() => { pageAlive = false })
</script>

<template>
  <main class="manual-page">
    <header class="manual-topbar">
      <div class="manual-project-nav">
        <AppButton type="button" variant="ghost" size="sm" icon-only aria-label="返回上一页" @click="router.back()"><ArrowLeft :size="18" /></AppButton>
        <div>
          <div class="project-name-line">
            <template v-if="editingName">
              <input v-model="nameDraft" maxlength="80" autofocus @keyup.enter="saveName" @keyup.esc="editingName = false" @blur="saveName" />
            </template>
            <template v-else>
              <strong>{{ project.name }}</strong>
              <AppButton type="button" variant="ghost" size="xs" icon-only aria-label="编辑项目名称" @click="startRename"><Pencil :size="13" /></AppButton>
            </template>
          </div>
          <span><Film :size="13" />{{ project.aspectRatio }}<i />{{ project.resolution }}<i />{{ project.style }}</span>
        </div>
      </div>

      <nav class="manual-phases" aria-label="人工短剧制作流程">
        <template v-for="(phase, index) in phases" :key="phase.label">
          <span v-if="index" class="phase-line" />
          <AppButton type="button" variant="soft" size="sm" :active="phase.active" :disabled="phase.disabled" :aria-current="phase.active ? 'step' : undefined" @click="selectPhase(phase.label)">
            <component :is="phase.icon" :size="16" />
            {{ phase.label }}
          </AppButton>
        </template>
      </nav>
    </header>

    <section class="manual-workspace">
      <header class="asset-toolbar">
        <nav aria-label="项目资产类型">
          <AppButton v-for="tab in tabs" :key="tab.value" type="button" variant="ghost" size="sm" :active="activeTab === tab.value" @click="activeTab = tab.value">
            <component :is="tab.icon" :size="17" />{{ tab.label }}
          </AppButton>
        </nav>
        <div class="asset-summary">
          <span>{{ activeTabConfig.label }}总计 <strong>{{ visibleAssets.length }}</strong></span>
          <i />
          <span><Check :size="13" />已完成 {{ completedCount }}</span>
          <span>生成中 {{ generatingCount }}</span>
          <span>失败 {{ failedCount }}</span>
          <AppButton type="button" variant="secondary" size="sm" icon-only aria-label="刷新" @click="loadProject"><RefreshCw :size="14" /></AppButton>
          <AppButton type="button" variant="primary" size="sm" @click="openAssetDialog()"><Plus :size="15" />添加{{ activeTabConfig.label }}</AppButton>
          <AppButton type="button" variant="soft" size="sm" :loading="batchGenerating" :disabled="batchGenerating" @click="visibleAssets.length ? showBatchDialog = true : notice.info(`请先添加${activeTabConfig.label}资产`)"><Layers3 v-if="!batchGenerating" :size="15" />{{ batchGenerating ? '批量生成中' : '批量生成' }}</AppButton>
        </div>
      </header>

      <div v-if="loading" class="workspace-state"><RefreshCw class="is-spinning" :size="28" /><span>正在加载项目…</span></div>
      <div v-else-if="!visibleAssets.length" class="workspace-state empty-state">
        <span class="empty-icon"><component :is="activeTabConfig.icon" :size="32" /></span>
        <strong>暂无{{ activeTabConfig.label }}</strong>
        <p>添加第一个{{ activeTabConfig.label }}，开始搭建你的短剧世界。</p>
        <AppButton type="button" variant="primary" size="sm" @click="openAssetDialog()"><Plus :size="15" />添加{{ activeTabConfig.label }}</AppButton>
      </div>
      <div v-else class="asset-grid">
        <article v-for="asset in visibleAssets" :key="asset.id" class="asset-card" role="button" tabindex="0" :aria-label="`编辑${activeTabConfig.label}：${asset.canonical_name}`" @click="openAssetDialog(asset)" @keydown.enter="openAssetDialog(asset)" @keydown.space.prevent="openAssetDialog(asset)">
          <div class="asset-visual">
            <img v-if="asset.main_image" :src="asset.main_image" :alt="asset.canonical_name" />
            <component v-else :is="activeTabConfig.icon" :size="30" />
            <span v-if="asset.main_image" class="ready-badge"><Check :size="12" />已完成</span>
            <span v-else-if="generatingAssetIds.has(asset.id)" class="generation-badge"><LoaderCircle :size="12" />生成中</span>
            <span v-else-if="failedAssetIds.has(asset.id)" class="generation-badge is-failed">生成失败</span>
          </div>
          <div class="asset-card-copy">
            <div><strong>{{ asset.canonical_name }}</strong><span class="asset-card-actions"><AppButton type="button" variant="ghost" size="xs" icon-only :aria-label="`编辑${asset.canonical_name}`" @click.stop="openAssetDialog(asset)"><Pencil :size="14" /></AppButton><AppButton type="button" variant="danger" size="xs" icon-only :aria-label="`删除${asset.canonical_name}`" @click.stop="removeAsset(asset)"><Trash2 :size="14" /></AppButton></span></div>
            <p>{{ asset.description || `尚未填写${activeTabConfig.label}描述` }}</p>
          </div>
        </article>
      </div>
    </section>

    <AppButton class="manual-next-step" type="button" variant="dark" size="lg" @click="goToStoryboard">
      <Clapperboard :size="17" />已确认，进入下一步
    </AppButton>

    <AssetCreateDialog
      :open="showAssetDialog"
      :kind="activeTab"
      :novel-id="projectId"
      :asset="editingAsset"
      @close="closeAssetDialog"
      @created="addCreatedAsset"
      @saved="saveEditedAsset"
    />

    <AssetBatchGenerateDialog
      :open="showBatchDialog"
      :label="activeTabConfig.label"
      :assets="visibleAssets"
      :generating-ids="generatingAssetIds"
      :failed-ids="failedAssetIds"
      :submitting="batchGenerating"
      @close="showBatchDialog = false"
      @generate="batchGenerateAssets"
    />
  </main>
</template>

<style scoped>
.manual-page { min-height: 100%; color: #303442; background: #f8f9fc; }
.manual-topbar { position: sticky; top: 0; z-index: 20; display: grid; grid-template-columns: minmax(270px,1fr) auto minmax(270px,1fr); align-items: center; min-height: 72px; padding: 8px 28px; border-bottom: 1px solid #e6e8f0; background: rgba(255,255,255,.96); backdrop-filter: blur(16px); }
.manual-project-nav { display: flex; align-items: center; gap: 13px; min-width: 0; }
.manual-project-nav > button { display: grid; place-items: center; width: 30px; height: 30px; color: #697080; border-radius: 9px; background: transparent; }
.manual-project-nav > button:hover { color: #5d5ff5; background: #f0f0ff; }
.project-name-line { display: flex; align-items: center; gap: 5px; min-height: 25px; }
.project-name-line strong { max-width: 360px; overflow: hidden; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; }
.project-name-line button { display: grid; place-items: center; color: #8a91a1; background: transparent; }
.project-name-line input { width: min(320px,45vw); height: 30px; padding: 0 9px; border: 1px solid #6b6df6; border-radius: 7px; outline: none; font: inherit; }
.manual-project-nav > div > span { display: flex; align-items: center; gap: 7px; margin-top: 2px; color: #9299a8; font-size: 11px; }
.manual-project-nav i { width: 1px; height: 10px; background: #dcdfe8; }
.manual-phases { grid-column: 2; display: flex; align-items: center; }
.manual-phases button { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; width: 74px; height: 54px; color: #a5abb8; border: 0; border-radius: 17px; background: #fafbfe; font-size: 11px; }
.manual-phases button.is-active { color: #5e60f5; background: #f0f0ff; box-shadow: 0 8px 22px rgba(92,94,246,.11); }
.manual-phases button:disabled { opacity: .55; }
.phase-line { width: 28px; height: 1px; background: #e1e3eb; }
.manual-workspace { padding: 28px 44px 120px; }
.asset-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 24px; min-height: 50px; }
.asset-toolbar nav { display: flex; align-items: center; gap: 26px; }
.asset-toolbar nav button { position: relative; display: flex; align-items: center; gap: 7px; height: 42px; color: #6f7686; background: transparent; font-size: 15px; font-weight: 700; }
.asset-toolbar nav button::after { position: absolute; right: 0; bottom: 0; left: 0; height: 2px; border-radius: 2px; background: #6668f6; content: ''; opacity: 0; transform: scaleX(.6); transition: .18s ease; }
.asset-toolbar nav button.is-active { color: #5d5ff5; }
.asset-toolbar nav button.is-active::after { opacity: 1; transform: scaleX(1); }
.asset-summary { display: flex; align-items: center; gap: 14px; color: #858c9b; font-size: 12px; }
.asset-summary span { display: flex; align-items: center; gap: 4px; white-space: nowrap; }
.asset-summary > i { width: 1px; height: 13px; background: #dfe1e8; }
.asset-summary strong { color: #303442; }
.icon-button,.text-action { display: inline-flex; align-items: center; gap: 6px; color: #424857; background: transparent; }
.icon-button { padding: 6px; border-radius: 7px; }
.icon-button:hover,.text-action:hover { color: #5d5ff5; background: #f1f1ff; }
.text-action { padding: 7px 9px; border-radius: 8px; font-size: 12px; }
.workspace-state { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: calc(100vh - 240px); color: #9aa1b1; }
.workspace-state span:not(.empty-icon) { margin-top: 12px; font-size: 13px; }
.empty-state .empty-icon { display: grid; place-items: center; width: 64px; height: 64px; color: #b7bcc8; border: 1px solid #e4e6ed; border-radius: 20px; background: #fff; box-shadow: 0 10px 26px rgba(49,54,76,.06); }
.empty-state strong { margin-top: 14px; color: #686f7f; font-size: 14px; }
.empty-state p { margin: 6px 0 18px; font-size: 12px; }
.empty-state > button { display: inline-flex; align-items: center; gap: 6px; height: 34px; padding: 0 14px; color: #fff; border-radius: 9px; background: #5e60f5; font-size: 12px; box-shadow: 0 8px 18px rgba(94,96,245,.2); }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill,minmax(260px,1fr)); gap: 16px; padding-top: 24px; }
.asset-card { overflow: hidden; border: 1px solid #e4e6ed; border-radius: 14px; outline: 0; background: #fff; cursor: pointer; transition: transform .18s ease,box-shadow .18s ease,border-color .18s ease; }
.asset-card:hover,.asset-card:focus-visible { border-color: #cfd0fb; box-shadow: 0 14px 34px rgba(54,57,98,.1); transform: translateY(-2px); }
.asset-visual { position: relative; display: grid; place-items: center; height: 190px; color: #aeb4c2; background: #f0f2f7; }
.asset-visual img { width: 100%; height: 100%; object-fit: cover; }
.ready-badge { position: absolute; top: 10px; right: 10px; display: flex; align-items: center; gap: 3px; padding: 4px 7px; color: #2f9b72; border-radius: 999px; background: rgba(255,255,255,.92); font-size: 10px; }
.generation-badge { position: absolute; top: 10px; right: 10px; display: flex; align-items: center; gap: 4px; padding: 4px 8px; border-radius: 999px; color: #6264ec; background: rgba(255,255,255,.94); box-shadow: 0 5px 14px rgba(43,46,80,.08); font-size: 10px; }
.generation-badge svg { animation: spin .8s linear infinite; }
.generation-badge.is-failed { color: #cf5f70; }
.asset-card-copy { padding: 13px 14px 14px; }
.asset-card-copy > div { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.asset-card-copy button { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; }
.asset-card-actions { display: flex; flex: 0 0 auto; align-items: center; gap: 4px; }
.asset-card-copy p { min-height: 34px; margin: 7px 0 0; color: #8a91a1; font-size: 11px; line-height: 1.55; }
.manual-next-step { position: fixed; bottom: 22px; left: 50%; z-index: 18; display: flex; align-items: center; gap: 8px; height: 44px; padding: 0 22px; color: #fff; border-radius: 15px; background: #23252c; box-shadow: 0 10px 28px rgba(21,23,31,.2); transform: translateX(-50%); }
.is-spinning { animation: spin .8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }
.manual-dialog-backdrop { position: fixed; inset: 0; z-index: 100; display: grid; place-items: center; padding: 20px; background: rgba(28,31,43,.32); backdrop-filter: blur(4px); }
.manual-dialog { width: min(460px,100%); padding: 22px; border: 1px solid #e1e3eb; border-radius: 18px; background: #fff; box-shadow: 0 24px 70px rgba(28,31,43,.22); }
.manual-dialog header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 20px; }
.manual-dialog header span { color: #6a6cf4; font-size: 9px; font-weight: 800; letter-spacing: .16em; }
.manual-dialog h2 { margin: 3px 0 0; font-size: 21px; }
.manual-dialog header button { display: grid; place-items: center; width: 34px; height: 34px; }
.manual-dialog label { display: grid; gap: 7px; margin-top: 14px; color: #555c6b; font-size: 12px; font-weight: 700; }
.manual-dialog input,.manual-dialog textarea { width: 100%; padding: 10px 11px; color: #303442; border: 1px solid #dfe2eb; border-radius: 9px; background: #fff; outline: none; font: inherit; font-weight: 400; resize: vertical; }
.manual-dialog input:focus,.manual-dialog textarea:focus { border-color: #7779f8; box-shadow: 0 0 0 3px rgba(94,96,245,.1); }
.manual-dialog footer { display: flex; justify-content: flex-end; gap: 9px; margin-top: 20px; }
.manual-dialog footer button { display: inline-flex; align-items: center; gap: 6px; }
@media (max-width: 900px) {
  .manual-topbar { grid-template-columns: 1fr; gap: 8px; padding: 10px 14px; }
  .manual-phases { grid-column: 1; justify-content: center; }
  .manual-phases button { width: 66px; height: 46px; }
  .manual-workspace { padding: 16px 16px 100px; }
  .asset-toolbar { align-items: flex-start; flex-direction: column; gap: 8px; }
  .asset-summary { width: 100%; overflow-x: auto; padding-bottom: 4px; }
  .asset-grid { grid-template-columns: 1fr; }
}
</style>
