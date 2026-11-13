<script setup lang="ts">
import { computed, useId } from 'vue'
import { tr } from '@/i18n'
import { stripChapterOrdinal } from '@/shared/chapterTitle'

const props = defineProps<{ text: string; episodeNumber?: number; episodeName?: string }>()
const readerId = useId()
type Line = { kind: 'note' | 'action' | 'dialogue' | 'title' | 'line'; label: string; text: string }
type Scene = { number: string; heading: string; location: string; setting: string; lines: Line[] }

const script = computed(() => {
  const intro: Line[] = []
  const scenes: Scene[] = []
  let lines = intro
  for (const raw of props.text.split(/\r?\n/)) {
    const text = raw.trim().replace(/^#{1,6}\s+/, '').replace(/^\*\*(.+)\*\*$/, '$1')
    if (!text) continue
    const scene = /^(\d+\s*[-–－]\s*\d+)[\s、.．]+(.+)$/.exec(text)
    if (scene) {
      const heading = scene[2]!
      const setting = heading.match(/\s+(?:内|外|内外|内\/外|外\/内)(?:\s+.*|$)/)?.[0] || ''
      const section: Scene = { number: scene[1]!, heading, location: heading.slice(0, heading.length - setting.length), setting, lines: [] }
      scenes.push(section)
      lines = section.lines
      continue
    }
    const episode = /^第\s*(\d+)\s*集\s*[·：:]?\s*(.*)$/.exec(text)
    if (!scenes.length && episode && Number(episode[1]) === props.episodeNumber &&
        episode[2] === stripChapterOrdinal(props.episodeName)) continue
    const meta = /^(出场|仅声音|关键道具)([：:])(.*)$/.exec(text)
    const speech = /^([^：:△【]{1,60})([：:])(.+)$/.exec(text)
    if (meta) lines.push({kind: 'note', label: meta[1]! + meta[2], text: meta[3]!})
    else if (text.startsWith('△')) lines.push({kind: 'action', label: '△', text: text.slice(1).trimStart()})
    else if (raw.trimStart().startsWith('#')) lines.push({kind: 'title', label: '', text})
    else if (speech) lines.push({kind: 'dialogue', label: speech[1]! + speech[2], text: speech[3]!})
    else lines.push({kind: 'line', label: '', text})
  }
  return { intro, scenes }
})

function goToScene(index: number) {
  const target = document.getElementById(`${readerId}-${index}`)
  target?.focus({preventScroll: true})
  target?.scrollIntoView({block: 'start'})
}
</script>

<template>
  <div class="screenplay-reader" :class="{ 'has-index': script.scenes.length > 1 }">
    <nav v-if="script.scenes.length > 1" class="scene-index" :aria-label="tr('场次目录')">
      <strong>{{ tr('场次目录') }}</strong>
      <ol>
        <li v-for="(scene, index) in script.scenes" :key="index">
          <button type="button" :aria-controls="`${readerId}-${index}`" @click="goToScene(index)">
            <span>{{ scene.number }}</span><span>{{ scene.heading }}</span>
          </button>
        </li>
      </ol>
    </nav>
    <section class="screenplay-reading">
      <p v-for="(line, index) in script.intro" :key="index" :class="line.kind"><b v-if="line.label">{{ line.label }}</b>{{ line.text }}</p>
      <section v-for="(scene, index) in script.scenes" :key="index" class="script-scene">
        <h4 :id="`${readerId}-${index}`" tabindex="-1" class="scene-heading"><span>{{ scene.number }}</span>　{{ scene.location }}<small>{{ scene.setting }}</small></h4>
        <p v-for="(line, i) in scene.lines" :key="i" :class="line.kind"><b v-if="line.label">{{ line.label }}</b>{{ line.text }}</p>
      </section>
    </section>
  </div>
</template>

<style scoped>
.screenplay-reader { display: grid; align-items: start; }
.screenplay-reader.has-index { grid-template-columns: minmax(148px, 196px) minmax(0, 1fr); gap: clamp(24px, 4vw, 64px); }
.scene-index { position: sticky; top: calc(var(--short-drama-header-height, 72px) + 16px); min-width: 0; padding-inline-end: 18px; border-inline-end: 1px solid var(--app-border); }
.scene-index > strong { font-size: 12px; color: var(--app-text-secondary); }
.scene-index ol { display: grid; gap: 3px; margin: 10px 0 0; padding: 0; list-style: none; }
.scene-index button { display: flex; width: 100%; gap: 9px; padding: 8px 5px; border: 0; border-radius: 6px; background: transparent; text-align: start; color: var(--app-text-secondary); cursor: pointer; font: inherit; font-size: 12px; line-height: 1.6; }
.scene-index button span:first-child { flex: none; font-variant-numeric: tabular-nums; color: var(--app-accent); }
.scene-index button:hover { color: var(--app-text); background: var(--app-surface-hover); }
.scene-index button:focus-visible, .scene-heading:focus-visible { outline: 2px solid var(--app-accent); outline-offset: 2px; }
.screenplay-reading { width: 100%; max-width: 52em; min-width: 0; color: var(--app-text); font-size: 15px; line-height: 1.85; overflow-wrap: anywhere; }
.screenplay-reading p { margin: .72em 0; }
.screenplay-reading .title { color: var(--app-text-secondary); font-size: 13px; font-weight: 600; }
.screenplay-reading > :first-child { margin-top: 0; }
.script-scene + .script-scene { margin-top: 28px; padding-top: 22px; border-top: 1px solid var(--app-border); }
.scene-heading { scroll-margin-top: calc(var(--short-drama-header-height, 72px) + 16px); margin: 0 0 12px; color: var(--app-text); font-size: 18px; line-height: 1.55; }
.scene-heading small { color: var(--app-text-secondary); font-size: 13px; font-weight: 500; white-space: pre-wrap; }
.scene-heading > span { color: var(--app-accent); font-variant-numeric: tabular-nums; }
.screenplay-reading .note { margin: 2px 0; font-size: 13px; color: var(--app-text-secondary); }
.note b { font-weight: 600; }
.action { position: relative; padding-inline-start: 1.25em; }
.action b { position: absolute; inset-inline-start: 0; font-weight: 400; color: var(--app-text-secondary); }
.screenplay-reading .dialogue { margin-inline-start: 1.25em; padding-inline-start: 12px; border-inline-start: 2px solid var(--app-border-strong); }
.dialogue b { font-weight: 650; }
@container creation-workspace (max-width: 780px) {
  .screenplay-reader.has-index { grid-template-columns: minmax(0, 1fr); gap: 18px; }
  .scene-index { position: static; border: 0; border-bottom: 1px solid var(--app-border); padding: 0 0 10px; }
  .scene-index ol { display: flex; overflow-x: auto; margin-top: 5px; }
  .scene-index li { flex: none; }
  .scene-index button { white-space: nowrap; }
}
</style>
