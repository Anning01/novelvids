<script lang="ts">
export interface CoverPalette {
  id: string
  background: string
  border: string
  accent: string
  secondary: string
  tagBg: string
  lineColor: string
}

export const COVER_PALETTES: CoverPalette[] = [
  {
    id: 'violet',
    background: 'linear-gradient(135deg, #1b0e31 0%, #2f1754 52%, #4a2386 100%)',
    border: 'rgba(167, 139, 250, 0.32)',
    accent: '#f5f3ff',
    secondary: 'rgba(237, 233, 254, 0.78)',
    tagBg: 'rgba(167, 139, 250, 0.22)',
    lineColor: '#a78bfa',
  },
  {
    id: 'indigo',
    background: 'linear-gradient(135deg, #0a1324 0%, #152758 52%, #1e40af 100%)',
    border: 'rgba(147, 197, 253, 0.32)',
    accent: '#eff6ff',
    secondary: 'rgba(219, 234, 254, 0.78)',
    tagBg: 'rgba(96, 165, 250, 0.22)',
    lineColor: '#60a5fa',
  },
  {
    id: 'emerald',
    background: 'linear-gradient(135deg, #031e15 0%, #064e3b 52%, #047857 100%)',
    border: 'rgba(110, 231, 183, 0.32)',
    accent: '#ecfdf5',
    secondary: 'rgba(209, 250, 229, 0.78)',
    tagBg: 'rgba(52, 211, 153, 0.22)',
    lineColor: '#34d198',
  },
  {
    id: 'rose',
    background: 'linear-gradient(135deg, #260817 0%, #4c0519 52%, #9f1239 100%)',
    border: 'rgba(253, 164, 175, 0.32)',
    accent: '#fff1f2',
    secondary: 'rgba(255, 228, 230, 0.78)',
    tagBg: 'rgba(251, 113, 133, 0.22)',
    lineColor: '#fb7185',
  },
  {
    id: 'amber',
    background: 'linear-gradient(135deg, #1f1103 0%, #451a03 52%, #92400e 100%)',
    border: 'rgba(252, 211, 77, 0.32)',
    accent: '#fffbeb',
    secondary: 'rgba(254, 243, 199, 0.78)',
    tagBg: 'rgba(245, 158, 11, 0.22)',
    lineColor: '#f59e0b',
  },
  {
    id: 'cyan',
    background: 'linear-gradient(135deg, #062026 0%, #0e4e5e 52%, #0e7490 100%)',
    border: 'rgba(103, 232, 249, 0.32)',
    accent: '#ecfeff',
    secondary: 'rgba(207, 250, 254, 0.78)',
    tagBg: 'rgba(34, 211, 238, 0.22)',
    lineColor: '#22d3ee',
  },
  {
    id: 'crimson',
    background: 'linear-gradient(135deg, #190507 0%, #3f0713 52%, #881337 100%)',
    border: 'rgba(252, 165, 165, 0.32)',
    accent: '#fef2f2',
    secondary: 'rgba(254, 226, 226, 0.78)',
    tagBg: 'rgba(239, 68, 68, 0.22)',
    lineColor: '#ef4444',
  },
  {
    id: 'slate',
    background: 'linear-gradient(135deg, #0f172a 0%, #1e293b 52%, #334155 100%)',
    border: 'rgba(203, 213, 225, 0.32)',
    accent: '#f8fafc',
    secondary: 'rgba(226, 232, 240, 0.78)',
    tagBg: 'rgba(148, 163, 184, 0.22)',
    lineColor: '#94a3b8',
  },
]

export function getCoverPalette(seed?: number | string | null): CoverPalette {
  if (seed === undefined || seed === null || seed === '') {
    return COVER_PALETTES[0]!
  }
  let hash = 0
  const str = String(seed)
  for (let i = 0; i < str.length; i++) {
    hash = (hash * 31 + str.charCodeAt(i)) >>> 0
  }
  return COVER_PALETTES[hash % COVER_PALETTES.length]!
}

export function formatCoverTitle(title?: string | null, alt?: string | null): {
  cleanTitle: string
  leadChar: string
  displayTitle: string
  subText: string
} {
  const raw = (title || alt || '').trim()
  if (!raw) {
    return { cleanTitle: '', leadChar: '剧', displayTitle: '短剧创作', subText: '' }
  }

  let cleaned = raw
    .replace(/^(\[.*?\]|【.*?】|\(.*?\)|\（.*?\）)\s*/, '')
    .trim()

  if (!cleaned) cleaned = raw

  const bookMatch = /^《(.*?)》\s*(.*)$/.exec(cleaned)
  if (bookMatch) {
    const bookTitle = bookMatch[1]!
    const extra = bookMatch[2]!
    return {
      cleanTitle: cleaned,
      leadChar: bookTitle.slice(0, 1),
      displayTitle: bookTitle.length <= 8 ? bookTitle : `${bookTitle.slice(0, 7)}…`,
      subText: extra.length <= 8 ? extra : `${extra.slice(0, 7)}…`,
    }
  }

  const clauses = cleaned.split(/[,，.。;；!！?？\s]+/).filter(Boolean)
  const firstClause = clauses[0] || cleaned
  const leadChar = cleaned.slice(0, 1)

  let displayTitle = firstClause.length <= 8 ? firstClause : `${firstClause.slice(0, 7)}…`
  if (cleaned.length <= 6) {
    displayTitle = cleaned
  }

  let subText = ''
  if (clauses.length > 1 && clauses[1]) {
    subText = clauses[1].length <= 8 ? clauses[1] : `${clauses[1].slice(0, 7)}…`
  } else if (cleaned.length > displayTitle.length) {
    const remaining = cleaned.slice(displayTitle.replace('…', '').length).replace(/^[,，\s]+/, '')
    if (remaining) {
      subText = remaining.length <= 8 ? remaining : `${remaining.slice(0, 7)}…`
    }
  }

  return { cleanTitle: cleaned, leadChar, displayTitle, subText }
}
</script>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Clapperboard, Image } from 'lucide-vue-next'
import { mediaUrl } from '@/api'
import { fallbackImage } from '@/shared/mediaFallback'
import { tr } from '@/i18n'

const props = withDefaults(defineProps<{
  source?: string | null
  original?: string | null
  aspectRatio?: string | null
  alt?: string
  title?: string | null
  seed?: number | string | null
  maxWidth?: number
  maxHeight?: number
  defaultCover?: boolean
  fit?: 'cover' | 'contain'
}>(), {
  maxWidth: 160,
  maxHeight: 120,
  alt: '',
  title: '',
  defaultCover: true,
  fit: 'cover',
})

const failed = ref(false)
watch(() => props.source, () => { failed.value = false })

const dimensions = computed(() => {
  const match = /^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/.exec(props.aspectRatio || '')
  const ratio = match && Number(match[1]) > 0 && Number(match[2]) > 0 ? Number(match[1]) / Number(match[2]) : 2 / 3
  const width = Math.min(props.maxWidth, props.maxHeight * ratio)
  return { width: `${width}px`, height: `${width / ratio}px`, aspectRatio: String(ratio) }
})

const coverSeed = computed(() => props.seed ?? props.title ?? props.alt)
const palette = computed(() => getCoverPalette(coverSeed.value))
const formatted = computed(() => formatCoverTitle(props.title, props.alt))

const hasImage = computed(() => Boolean(props.source && !failed.value))

function onError(event: Event) {
  if (!failed.value) {
    if (props.original && props.original !== props.source) {
      fallbackImage(event, mediaUrl(props.original))
      return
    }
    failed.value = true
  }
}
</script>

<template>
  <div class="project-cover" :style="dimensions">
    <img
      v-if="hasImage"
      :src="mediaUrl(source!)"
      :alt="alt || title || ''"
      :style="{ objectFit: fit }"
      loading="lazy"
      decoding="async"
      @error="onError"
    >
    <div
      v-else-if="defaultCover"
      class="project-cover__generated"
      :style="{
        background: palette.background,
        borderColor: palette.border,
        color: palette.accent,
      }"
      :aria-label="formatted.cleanTitle || alt || tr('未命名项目')"
    >
      <div class="project-cover__watermark" :aria-hidden="true">{{ formatted.leadChar }}</div>
      <div class="project-cover__header" :style="{ color: palette.lineColor }">
        <Clapperboard :size="10" aria-hidden="true" />
        <span>{{ tr('猫影') }}</span>
      </div>
      <div class="project-cover__body">
        <strong class="project-cover__title" :title="formatted.cleanTitle">{{ formatted.displayTitle }}</strong>
        <span v-if="formatted.subText" class="project-cover__sub" :style="{ color: palette.secondary }" :title="formatted.cleanTitle">{{ formatted.subText }}</span>
      </div>
      <div class="project-cover__footer-line" :style="{ backgroundColor: palette.lineColor }" aria-hidden="true" />
    </div>
    <Image v-else :size="24" :aria-label="tr('暂无封面')" />
  </div>
</template>

<style scoped>
.project-cover {
  container-type: inline-size;
  display: grid;
  flex-shrink: 0;
  max-width: 100%;
  place-items: center;
  overflow: hidden;
  border-radius: 10px;
  background: var(--app-surface-muted);
  color: var(--app-text-muted);
  position: relative;
  user-select: none;
}
.project-cover img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.project-cover__generated {
  position: relative;
  width: 100%;
  height: 100%;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 8px 10px;
  overflow: hidden;
  border-radius: inherit;
  border: 1px solid transparent;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), inset 0 0 24px rgba(0, 0, 0, 0.38);
}
.project-cover__watermark {
  position: absolute;
  right: -6px;
  bottom: -10px;
  font-size: 58px;
  font-weight: 900;
  line-height: 1;
  color: #ffffff;
  opacity: 0.08;
  pointer-events: none;
  font-family: serif, var(--font-family, sans-serif);
  transform: rotate(-8deg);
}
.project-cover__header {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 9.5px;
  font-weight: 600;
  letter-spacing: 0.08em;
}
.project-cover__body {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  margin: 4px 0;
}
.project-cover__title {
  font-size: 13.5px;
  font-weight: 700;
  line-height: 1.25;
  letter-spacing: 0.02em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.55);
}
.project-cover__sub {
  font-size: 9.5px;
  line-height: 1.25;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.project-cover__footer-line {
  position: relative;
  z-index: 1;
  height: 2px;
  width: 22px;
  border-radius: 9999px;
  opacity: 0.7;
}

@container (max-width: 90px) {
  .project-cover__generated {
    padding: 6px 7px;
  }
  .project-cover__title {
    font-size: 11.5px;
  }
  .project-cover__sub {
    font-size: 8.5px;
  }
  .project-cover__watermark {
    font-size: 42px;
    right: -4px;
    bottom: -6px;
  }
}
</style>
