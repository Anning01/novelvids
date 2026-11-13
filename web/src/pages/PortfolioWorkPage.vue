<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElDialog } from 'element-plus'
import { ArrowLeft, Check, ChevronDown, Clapperboard, Copy, Download, Pencil, Play, Shield, Star } from 'lucide-vue-next'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { money } from '@/features/billing/recordDisplay'
import FinishedCover from '@/features/finished-episodes/FinishedCover.vue'
import { finishedApi, runtime, versionName, type FinishedVersion } from '@/features/finished-episodes/api'
import { useAuthStore } from '@/features/auth/authStore'
import { productionCostLabel, productionTime, workApi, workDate, workLength, workResolution, workStatus, type WorkAction, type WorkDetail, type WorkEpisode, type WorkProfile } from '@/features/portfolio/api'
import { authHeaders } from '@/api'
import { tr } from '@/i18n'
import { appConfirm } from '@/shared/confirmDialog'
import { downloadFile } from '@/shared/downloadFile'
import '@/features/resource-library/dialog.css'
import '@/features/portfolio/portfolio.css'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const publicView = computed(() => route.name === 'public-work')
const id = computed(() => Number(route.params.projectId))
const work = ref<WorkDetail>()
const episodeId = ref<number>()
const versions = ref<FinishedVersion[]>([])
const versionId = ref<number>()
const loading = ref(false)
const playing = ref(false)
const saving = ref(false)
const downloading = ref(false)
const loadError = ref('')
const actionError = ref('')
const profileError = ref('')
const playerError = ref('')
const notice = ref('')
const source = ref('')
const player = ref<HTMLVideoElement>()
const editing = ref(false)
const profile = ref<WorkProfile>()
const tags = ref('')
const selected = ref<Record<number, number>>({})
const recommendationOrder = ref(0)
const tab = ref<'episodes' | 'intro'>('episodes')
const publicationOpen = ref(false)
let loadingRequest: AbortController | undefined
let versionRequest = 0
let playbackRequest = 0
let writeRequest = 0
let downloadRequest = 0

const episode = computed(() => work.value?.episodes.find(row => row.chapter_id === episodeId.value))
const current = computed(() => versions.value.find(row => row.id === versionId.value) ?? episode.value?.version)
const versionOptions = computed(() => versions.value.map(row => ({
  value: String(row.id), label: `${versionName(row)} · ${runtime(row.duration)}${episode.value?.published_id === row.id ? ` · ${tr('已公开')}` : ''}`,
})))
const coverOptions = computed(() => (work.value?.episodes ?? []).map(row => ({
  value: String(row.chapter_id), label: `${tr('第 {p0} 集', { p0: row.number })} · ${row.title}`,
})))
const publicUrl = computed(() => new URL(router.resolve({ name: 'public-work', params: { projectId: id.value } }).href, window.location.href).href)

function clearPlayback() {
  ++playbackRequest
  player.value?.pause()
  if (source.value.startsWith('blob:')) URL.revokeObjectURL(source.value)
  source.value = ''
  playing.value = false
}

async function selectEpisode(row: WorkEpisode, playImmediately = false, requestedVersion?: number) {
  const request = ++versionRequest
  clearPlayback()
  playerError.value = ''
  episodeId.value = row.chapter_id
  versions.value = [row.version]
  versionId.value = row.version.id
  if (!publicView.value) {
    try {
      const response = await finishedApi.versions(row.chapter_id)
      if (request !== versionRequest) return
      versions.value = response.data
      versionId.value = response.data.find(version => version.id === requestedVersion)?.id ?? row.version.id
    } catch {
      if (request !== versionRequest) return
    }
  }
  if (playImmediately) void play()
}
function selectVersion(value: string) {
  clearPlayback()
  playerError.value = ''
  versionId.value = Number(value)
}
function resetPublication(item: WorkDetail) {
  selected.value = Object.fromEntries(item.episodes.flatMap(row => {
    const version = item.status === 'public' ? row.published_id : row.version.id
    return version ? [[row.chapter_id, version]] : []
  }))
  recommendationOrder.value = item.featured_order
}
function apply(item: WorkDetail) {
  work.value = item
  resetPublication(item)
}
async function load() {
  loadingRequest?.abort()
  ++writeRequest
  ++versionRequest
  ++downloadRequest
  clearPlayback()
  const controller = new AbortController()
  loadingRequest = controller
  work.value = undefined
  editing.value = false
  publicationOpen.value = false
  tab.value = 'episodes'
  saving.value = false
  downloading.value = false
  loading.value = true
  loadError.value = ''
  actionError.value = ''
  notice.value = ''
  try {
    const response = await workApi.detail(id.value, publicView.value, controller.signal)
    if (controller.signal.aborted) return
    apply(response.data)
    const first = response.data.episodes.find(row => row.chapter_id === Number(route.query.chapter)) ?? response.data.episodes[0]
    if (first) void selectEpisode(first, false, Number(route.query.version))
    if (route.query.edit === '1') startEdit()
  } catch (reason) {
    if (!controller.signal.aborted) loadError.value = reason instanceof Error ? reason.message : tr('作品加载失败')
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

async function play() {
  if (!current.value || playing.value) return
  const request = ++playbackRequest
  const version = current.value.id
  const project = id.value
  playing.value = true
  playerError.value = ''
  try {
    const streamUrl = publicView.value
      ? workApi.publicMedia(project, version, 'video')
      : finishedApi.videoUrl(version, false, auth.token)
    if (request !== playbackRequest) return
    source.value = streamUrl
    await nextTick()
    if (request === playbackRequest) await player.value?.play().catch(() => {})
  } catch (reason) {
    if (request === playbackRequest) playerError.value = reason instanceof Error ? reason.message : tr('作品播放失败')
  } finally {
    if (request === playbackRequest) playing.value = false
  }
}
function nextEpisode() {
  if (!work.value) return
  const index = work.value.episodes.findIndex(row => row.chapter_id === episodeId.value)
  const next = work.value.episodes[index + 1]
  if (next) void selectEpisode(next, true)
}
function playbackFailed() {
  playerError.value = tr('作品播放失败')
  clearPlayback()
}
async function download() {
  if (!current.value || downloading.value) return
  const request = ++downloadRequest
  const version = current.value
  downloading.value = true
  playerError.value = ''
  try {
    await downloadFile(finishedApi.videoUrl(version.id, true), `episode-${episode.value?.number}-${versionName(version)}.mp4`, authHeaders())
  } catch (reason) {
    if (request === downloadRequest) playerError.value = reason instanceof Error ? reason.message : tr('作品下载失败')
  } finally {
    if (request === downloadRequest) downloading.value = false
  }
}

function startEdit() {
  const item = work.value
  if (!item?.can_edit) return
  profile.value = {
    title: item.title, description: item.description,
    tags: item.tags, cover_chapter_id: item.cover_chapter_id, revision: item.revision,
  }
  tags.value = item.tags.join('，')
  profileError.value = ''
  editing.value = true
}
function closeEdit() {
  editing.value = false
  if (route.query.edit) void router.replace({ query: { ...route.query, edit: undefined, archive: undefined } })
}

async function saveProfile() {
  if (!profile.value || saving.value) return
  const nextTags = [...new Set(tags.value.split(/[,，\n]/).map(tag => tag.trim()).filter(Boolean))]
  if (nextTags.length > 12 || nextTags.some(tag => tag.length > 40)) {
    profileError.value = tr('最多 12 个标签，每个标签不超过 40 字')
    return
  }
  const request = ++writeRequest
  saving.value = true
  profileError.value = ''
  try {
    const response = await workApi.save(id.value, { ...profile.value, tags: nextTags })
    if (request !== writeRequest) return
    apply(response.data)
    closeEdit()
    notice.value = tr('作品资料已保存')
  } catch (reason) {
    if (request === writeRequest) profileError.value = reason instanceof Error ? reason.message : tr('保存失败')
  } finally {
    if (request === writeRequest) saving.value = false
  }
}
function toggleEpisode(row: WorkEpisode, checked: boolean) {
  if (checked) selected.value[row.chapter_id] = row.published_id ?? row.version.id
  else delete selected.value[row.chapter_id]
}
function useCurrentVersion() {
  if (current.value && episode.value) selected.value[episode.value.chapter_id] = current.value.id
}
async function runAction(action: WorkAction, featured = false) {
  const item = work.value
  if (!item || saving.value) return
  const request = ++writeRequest
  saving.value = true
  actionError.value = ''
  notice.value = ''
  const exports = Object.values(selected.value)
  try {
    if (action === 'publish' || action === 'withdraw') {
      const publishing = action === 'publish'
      const confirmed = await appConfirm({
        title: tr(publishing ? '公开所选剧集' : '下架作品'),
        message: tr(publishing ? '公开后，任何获得链接的人都能观看所选剧集。' : '下架后，公开链接将无法访问，团队仍可查看作品。'),
        confirmLabel: tr(publishing ? '确认公开' : '确认下架'),
        tone: publishing ? 'neutral' : 'warning',
      })
      if (!confirmed || request !== writeRequest) return
    }
    const response = await workApi.action(id.value, {
      action, revision: item.revision, export_ids: action === 'publish' ? exports : undefined,
      featured, featured_order: recommendationOrder.value,
    })
    if (request !== writeRequest) return
    apply(response.data)
    notice.value = tr('作品状态已更新')
  } catch (reason) {
    if (request === writeRequest) actionError.value = reason instanceof Error ? reason.message : tr('作品操作失败')
  } finally {
    if (request === writeRequest) saving.value = false
  }
}
async function copyLink() {
  try {
    await navigator.clipboard.writeText(publicUrl.value)
    notice.value = tr('公开链接已复制')
  } catch {
    actionError.value = tr('无法复制链接，可打开公开页面后复制地址')
  }
}
watch([id, publicView, () => auth.activeTeamId], load, { immediate: true })
onBeforeUnmount(() => {
  loadingRequest?.abort()
  ++versionRequest
  ++writeRequest
  ++downloadRequest
  clearPlayback()
})
</script>

<template>
  <main class="portfolio-page work-detail" :class="{ 'is-public': publicView }">
    <RouterLink v-if="!publicView" :to="{ path: '/finished-library' }" class="work-back"><ArrowLeft :size="16" />{{ tr('返回作品库') }}</RouterLink>
    <p v-if="loading" class="work-state" role="status">{{ tr('正在加载作品…') }}</p>
    <div v-else-if="loadError" class="work-panel work-state work-error" role="alert">{{ loadError }} <AppButton size="sm" @click="load">{{ tr('重试') }}</AppButton></div>
    <template v-else-if="work">
      <header class="work-header">
        <div class="work-title"><h1>{{ work.title }}</h1><span v-if="!publicView" class="work-badge" :data-status="work.status">{{ workStatus(work.status) }}</span></div>
        <div v-if="!publicView" class="work-actions">
          <AppButton v-if="work.can_edit && !editing" variant="secondary" :disabled="saving" @click="startEdit"><Pencil :size="15" />{{ tr('编辑资料') }}</AppButton>
          <AppButton v-if="work.can_edit && !work.can_manage && work.status !== 'pending'" variant="primary" :disabled="saving || editing" @click="runAction('submit')"><Shield :size="15" />{{ tr('提交审核') }}</AppButton>
        </div>
      </header>
      <p v-if="notice" class="work-notice" role="status">{{ notice }}</p>
      <p v-if="actionError" class="work-error" role="alert">{{ actionError }}</p>
      <ElDialog
        class="resource-library-dialog work-edit-dialog"
        :model-value="editing"
        :title="tr(work.revision ? '编辑作品资料' : '归档作品')"
        width="540px"
        align-center
        append-to-body
        destroy-on-close
        :show-close="!saving"
        :close-on-click-modal="!saving"
        :close-on-press-escape="!saving"
        @update:model-value="closeEdit"
      >
        <form v-if="profile" class="work-edit" @submit.prevent="saveProfile">
          <label>{{ tr('作品名称') }}<input v-model.trim="profile.title" required maxlength="255" :disabled="saving" /></label>
          <div class="work-edit-type"><span>{{ tr('作品类型') }}</span><strong>{{ tr(work.category) }}</strong></div>
          <label class="work-edit-wide">{{ tr('作品简介') }}<textarea v-model.trim="profile.description" maxlength="5000" rows="2" :disabled="saving" /></label>
          <label :class="{ 'work-edit-wide': coverOptions.length < 2 }">{{ tr('标签（用逗号分隔）') }}<input v-model="tags" maxlength="510" :disabled="saving" /></label>
          <label v-if="coverOptions.length > 1">
            {{ tr('封面剧集') }}
            <AppSelect :model-value="String(profile.cover_chapter_id ?? '')" :options="coverOptions" :ariaLabel="tr('封面剧集')" :menu-z-index="3000" :disabled="saving" @update:model-value="profile.cover_chapter_id = Number($event)" />
          </label>
          <p v-if="profileError" class="work-edit-wide work-error" role="alert">{{ profileError }}</p>
          <div class="work-actions work-edit-wide work-edit-actions">
            <AppButton :disabled="saving" @click="closeEdit">{{ tr('取消') }}</AppButton>
            <AppButton type="submit" variant="primary" :loading="saving" :disabled="!profile.title.trim()">{{ tr(work.revision ? '保存资料' : '保存并归档') }}</AppButton>
          </div>
        </form>
      </ElDialog>

      <div class="work-detail-grid">
        <div class="work-main">
          <section class="work-preview" :aria-label="tr('作品预览')">
            <video v-if="source" ref="player" :src="source" controls playsinline :aria-label="tr('作品播放')" @ended="nextEpisode" @error="playbackFailed" />
            <template v-else-if="current">
              <img v-if="publicView" :src="workApi.publicMedia(id, current.id, 'cover')" :alt="tr('视频第一帧封面')" />
              <FinishedCover v-else :version-id="current.id" />
              <AppButton variant="dark" size="lg" icon-only :loading="playing" :aria-label="tr('播放作品')" @click="play"><Play :size="24" /></AppButton>
            </template>
          </section>
          <p v-if="playerError" class="work-error" role="alert">{{ playerError }}</p>
          <div v-if="!publicView && current" class="work-version work-actions">
            <AppSelect :model-value="String(current.id)" :options="versionOptions" :ariaLabel="tr('合成版本')" density="compact" @update:model-value="selectVersion" />
            <AppButton size="sm" :loading="downloading" @click="download"><Download :size="15" />{{ tr('下载成片') }}</AppButton>
          </div>
          <section class="work-panel work-episodes">
            <div class="work-tabs" role="group" :aria-label="tr('作品详情栏目')">
              <AppButton size="sm" :variant="tab === 'episodes' ? 'soft' : 'ghost'" :aria-pressed="tab === 'episodes'" @click="tab = 'episodes'">{{ tr('剧集列表') }} ({{ work.episode_count }})</AppButton>
              <AppButton size="sm" :variant="tab === 'intro' ? 'soft' : 'ghost'" :aria-pressed="tab === 'intro'" @click="tab = 'intro'">{{ tr('作品简介') }}</AppButton>
            </div>
            <div v-if="tab === 'episodes'" class="episode-list">
              <div v-for="row in work.episodes" :key="row.chapter_id" class="episode-row" :class="{ 'is-active': row.chapter_id === episodeId }">
                <button type="button" class="episode-choice" :aria-current="row.chapter_id === episodeId ? 'true' : undefined" @click="selectEpisode(row, true)">
                  <span class="episode-icon"><Play :size="16" aria-hidden="true" /></span>
                  <span><strong>{{ tr('第 {p0} 集', { p0: row.number }) }} · {{ row.title }}</strong><small>{{ runtime(row.version.duration) }}</small></span>
                </button>
                <span v-if="!publicView" class="work-muted">{{ tr(row.published_id ? '已公开' : '已完成') }}</span>
              </div>
            </div>
            <div v-else class="work-description">
              <p>{{ work.description || tr('暂无作品简介') }}</p>
              <div class="work-tags"><span v-for="tag in work.tags" :key="tag">{{ tag }}</span></div>
            </div>
          </section>
        </div>

        <aside class="work-sidebar">
          <section class="work-panel work-side-panel">
            <h2>{{ tr('作品信息') }}</h2>
            <dl v-if="!publicView" class="work-facts">
              <div><dt>{{ tr('制作人') }}</dt><dd>{{ work.producer || '—' }}</dd></div>
              <div :title="tr('从项目创建到最近一次成功合成的经过时间')"><dt>{{ tr('制作耗时') }}</dt><dd>{{ productionTime(work.production_seconds) }}</dd></div>
              <div v-if="work.recorded_cost != null"><dt>{{ productionCostLabel(work.cost_scope) }}</dt><dd>{{ work.pending_cost ? tr('待结算') : money(work.recorded_cost) }}</dd></div>
              <div><dt>{{ tr('归档时间') }}</dt><dd>{{ workDate(work.archived_at, true) }}</dd></div>
            </dl>
            <p class="work-muted">{{ tr('{p0} 集', { p0: work.episode_count }) }} · {{ workLength(work.duration) }} · {{ workResolution(work.resolution) }}<template v-if="work.category"> · {{ tr(work.category) }}</template></p>
            <div v-if="work.tags.length" class="work-tags"><span v-for="tag in work.tags" :key="tag">{{ tag }}</span></div>
            <RouterLink v-if="!publicView" :to="`/novel/${work.project_id}`" class="work-source">{{ tr('打开原项目') }}</RouterLink>
          </section>
          <section v-if="!publicView && (work.can_manage || work.status === 'public')" class="work-panel work-side-panel work-publication">
            <AppButton
              class="work-disclosure"
              :aria-expanded="publicationOpen"
              :aria-controls="publicationOpen ? 'work-publication-options' : undefined"
              @click="publicationOpen = !publicationOpen"
            >
              {{ tr('公开展示设置') }}
              <span v-if="work.featured" class="work-badge is-featured">{{ tr('首页推荐') }}</span>
              <ChevronDown :size="16" aria-hidden="true" />
            </AppButton>
            <div v-if="publicationOpen" id="work-publication-options" class="work-publication-options">
              <template v-if="work.can_manage">
                <fieldset class="work-public-episodes" :disabled="saving || editing">
                  <legend>{{ tr('选择公开剧集') }}</legend>
                  <label v-for="row in work.episodes" :key="row.chapter_id">
                    <input type="checkbox" :checked="!!selected[row.chapter_id]" @change="toggleEpisode(row, ($event.target as HTMLInputElement).checked)" />
                    <span>{{ tr('第 {p0} 集', { p0: row.number }) }}</span>
                    <small v-if="selected[row.chapter_id]">{{ selected[row.chapter_id] === row.version.id ? versionName(row.version) : tr('已选历史版本') }}</small>
                  </label>
                </fieldset>
                <AppButton v-if="current && episode && selected[episode.chapter_id] !== current.id" size="sm" :disabled="saving || editing" @click="useCurrentVersion">{{ tr('将当前播放版本设为公开版本') }}</AppButton>
                <div class="work-actions">
                  <AppButton v-if="work.status !== 'public'" size="sm" variant="primary" :disabled="saving || editing || !Object.keys(selected).length" @click="runAction('publish')"><Check :size="15" />{{ tr('通过并公开') }}</AppButton>
                  <AppButton v-if="work.status === 'pending'" size="sm" :disabled="saving || editing" @click="runAction('approve')">{{ tr('通过并保留团队可见') }}</AppButton>
                  <AppButton v-if="work.status === 'private' || work.status === 'withdrawn'" size="sm" :disabled="saving || editing" @click="runAction('submit')">{{ tr('提交审核') }}</AppButton>
                  <AppButton v-if="work.status === 'public'" size="sm" variant="secondary" :disabled="saving || editing || !Object.keys(selected).length" @click="runAction('publish')">{{ tr('更新公开剧集') }}</AppButton>
                  <AppButton v-if="work.status === 'public'" size="sm" variant="danger" :disabled="saving || editing" @click="runAction('withdraw')">{{ tr('下架作品') }}</AppButton>
                </div>
                <div v-if="work.status === 'public'" class="work-recommendation">
                  <label>{{ tr('推荐顺序') }} <input v-model.number="recommendationOrder" type="number" min="0" max="9999" :disabled="saving || editing" /></label>
                  <div class="work-actions">
                    <AppButton size="sm" variant="secondary" :disabled="saving || editing || !Number.isInteger(recommendationOrder) || recommendationOrder < 0 || recommendationOrder > 9999" @click="runAction('recommend', true)"><Star :size="15" />{{ tr(work.featured ? '保存推荐顺序' : '设为首页推荐') }}</AppButton>
                    <AppButton v-if="work.featured" size="sm" :disabled="saving || editing" @click="runAction('recommend', false)">{{ tr('取消推荐') }}</AppButton>
                  </div>
                </div>
              </template>
              <div v-if="work.status === 'public'" class="work-actions">
                <a :href="publicUrl" target="_blank" rel="noopener noreferrer" class="work-link"><Clapperboard :size="15" />{{ tr('打开公开页面') }}</a>
                <AppButton size="sm" @click="copyLink"><Copy :size="15" />{{ tr('复制公开链接') }}</AppButton>
              </div>
            </div>
          </section>
        </aside>
      </div>
    </template>
  </main>
</template>
