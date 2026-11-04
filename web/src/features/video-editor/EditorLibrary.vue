<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { Film, Music2, Type, Sticker, Upload, Search, Plus, FolderOpen, ArrowRight, X, Sparkles } from 'lucide-vue-next'
import TeamResourcePanel from '@/features/resource-library/TeamResourcePanel.vue'
import VideoThumbnail from '@/components/VideoThumbnail.vue'
import { mediaUrl } from '@/api'
import { tr } from '@/i18n'
import type { ClipKind, EditorMedia } from './types'
const props = defineProps<{ media: EditorMedia[]; selectedKey?: string; busy: boolean; progress: number; readOnly: boolean; recognizing?: boolean }>()
const emit = defineEmits<{ select: [item: EditorMedia]; add: [item: EditorMedia]; upload: [kind: Exclude<ClipKind, 'subtitle'>]; subtitle: []; srt: []; recognize: []; library: []; libraryAdd: [item: EditorMedia]; publish: [item: EditorMedia] }>()
const audition = ref<EditorMedia | null>(null), auditionError = ref(''), auditionPlayer = ref<HTMLAudioElement | null>(null)
const tab = ref<ClipKind>('video'), sourceTab = ref('chapter'), search = ref(''), open = ref(false)
const tabs = computed(() => [{ id: 'video' as const, label: tr('媒体'), icon: Film }, { id: 'audio' as const, label: 'BGM', icon: Music2 }, { id: 'subtitle' as const, label: tr('字幕'), icon: Type }, { id: 'sticker' as const, label: tr('贴纸'), icon: Sticker }])
const items = computed(() => props.media.filter(item => item.kind === tab.value && (tab.value !== 'video' || (sourceTab.value === 'chapter' ? item.sequence !== undefined : item.sequence === undefined)) && item.name.toLowerCase().includes(search.value.toLowerCase())))
const heading = computed(() => ({ video: tr('媒体素材'), audio: tr('背景音乐'), subtitle: tr('字幕'), sticker: tr('贴纸') })[tab.value])
function choose(kind: ClipKind) { open.value = tab.value !== kind || !open.value; tab.value = kind; search.value = '' }
function add(item: EditorMedia) { emit('add', item); if (innerWidth < 700) open.value = false }
async function selected(item: EditorMedia) {
  if (item.kind === 'audio') {
    audition.value = item; auditionError.value = ''
    await nextTick()
    if (audition.value?.key !== item.key) return
    try { await auditionPlayer.value?.play() }
    catch { if (audition.value?.key === item.key) auditionError.value = tr('音频播放失败，请检查素材或浏览器播放权限') }
    return
  }
  audition.value = null
  emit('select', item)
  if (innerWidth < 700) open.value = false
}
function format(seconds = 0) { return `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}` }
</script>
<template>
  <section class="editor-library" :class="{ 'is-open': open }" :aria-label="tr('素材库')">
    <nav class="editor-library-nav" :aria-label="tr('素材类型')"><button v-for="item in tabs" :key="item.id" :aria-pressed="tab === item.id" @click="choose(item.id)"><component :is="item.icon" :size="19" /><span>{{ item.label }}</span></button></nav>
    <div class="editor-library-body">
      <div class="editor-library-content">
      <header class="editor-panel-heading"><h2>{{ heading }}</h2><button class="editor-icon-btn mobile-library-close" :aria-label="tr('关闭素材库')" @click="open = false"><X :size="15" /></button></header>
      <template v-if="tab === 'subtitle'">
        <p class="editor-panel-note">{{ tr('在右侧编辑内容与样式，在时间线调整时间。') }}</p>
        <button class="editor-btn secondary full-width" :disabled="readOnly" @click="emit('subtitle')"><Plus :size="15" />{{ tr('添加字幕') }}</button>
        <button class="editor-btn secondary full-width" :disabled="readOnly" @click="emit('srt')"><Upload :size="14" />{{ tr('导入 SRT') }}</button>
        <button class="editor-btn secondary full-width editor-ai-btn" :disabled="readOnly || recognizing" @click="emit('recognize')"><Sparkles :size="14" />{{ recognizing ? tr('识别中...') : tr('AI 识别') }}</button>
        <p class="editor-panel-note">{{ tr('字幕会独立保存到时间线，不改写原视频。') }}</p>
      </template>
      <template v-else>
        <div class="editor-source-tabs"><button v-if="tab === 'video'" :aria-pressed="sourceTab === 'chapter'" @click="sourceTab = 'chapter'">{{ tr('本集分镜') }}</button><button :aria-pressed="sourceTab === 'imported'" @click="sourceTab = 'imported'">{{ tr(tab === 'video' ? '导入素材' : '本项目') }}</button><button :aria-pressed="sourceTab === 'team'" @click="sourceTab = 'team'">{{ tr('团队资源库') }}</button></div><TeamResourcePanel v-if="sourceTab === 'team'" :kind="tab" :read-only="readOnly" @select="selected" @add="item => emit('libraryAdd', item)"/><template v-else>
        <label class="editor-search"><Search :size="14" /><input v-model="search" :aria-label="tr('搜索素材')" :placeholder="tr('搜索素材')" /></label>
        <button class="editor-btn secondary full-width" :disabled="readOnly || busy" @click="emit('upload', tab)"><Upload :size="14" />{{ busy ? tr('上传中 {p0}%', { p0: progress }) : tr('导入素材') }}</button>
        <div v-if="items.length" :class="tab === 'video' || tab === 'sticker' ? 'editor-media-grid' : 'editor-audio-list'">
          <article v-for="item in items" :key="item.key" class="editor-media-item" :class="{ selected: item.key === selectedKey }">
            <button class="editor-media-thumb" :aria-label="tr('选择素材 {p0}', { p0: item.name })" @click="selected(item)">
              <VideoThumbnail v-if="item.kind === 'video' && item.url && !item.missing" :src="mediaUrl(item.url)" :poster="mediaUrl(item.poster)" />
              <img v-else-if="item.kind === 'sticker' && item.url" :src="mediaUrl(item.url)" alt="" />
              <component :is="item.kind === 'audio' ? Music2 : Film" v-else :size="23" />
              <span v-if="item.kind !== 'sticker'" class="editor-media-duration">{{ item.missing ? tr('待生成') : format(item.duration) }}</span>
            </button>
            <div class="editor-media-label"><span :title="item.name">{{ item.name }}</span><button class="editor-icon-btn" :disabled="readOnly || item.missing" :aria-label="tr('添加素材 {p0}', { p0: item.name })" @click="add(item)"><Plus :size="14" /></button></div>
            <button v-if="item.source.kind === 'asset'" class="editor-link" :disabled="readOnly" @click="emit('publish', item)">{{ tr('存入团队资源库') }}</button><small>{{ item.missing ? tr('分镜位置保留') : item.kind === 'video' ? `${item.width || '—'}×${item.height || '—'}` : item.kind === 'audio' ? format(item.duration) : tr('静态贴纸') }}</small>
          </article>
        </div>
        <div v-else class="editor-empty"><FolderOpen :size="27" /><span>{{ search ? tr('没有找到素材') : tr('暂无素材，请先导入') }}</span></div>
        <button v-if="tab === 'video'" class="editor-link" :disabled="readOnly" @click="emit('library')">{{ tr('从资源库选择视频') }}<ArrowRight :size="13" /></button>
      </template></template>
      </div>
      <footer v-if="audition" class="editor-library-audition" :aria-label="tr('音频预览')">
        <div><Music2 :size="14"/><strong :title="audition.name">{{ audition.name }}</strong><button class="editor-icon-btn" :aria-label="tr('关闭试听')" @click="audition=null"><X :size="14"/></button></div>
        <audio ref="auditionPlayer" :key="audition.key" :src="mediaUrl(audition.url)" controls autoplay :aria-label="tr('试听 {p0}',{p0:audition.name})" @error="auditionError=tr('音频读取失败，请检查素材')"/>
        <p v-if="auditionError" role="alert">{{ auditionError }}</p>
      </footer>
    </div>
  </section>
</template>
