import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const source = readFileSync('src/pages/ShortDramaStoryboardPage.vue', 'utf8')

it('keeps the current chapter toolbar below the shared fixed header while scenes scroll', () => {
  expect(source).toContain('.chapter-toolbar { position: sticky; top: var(--short-drama-header-height,72px);')
  expect(source).toContain('scroll-margin-top: calc(var(--short-drama-header-height,72px) + 116px)')
  expect(source).toContain("document.querySelector<HTMLElement>('.app-content')")
  expect(source).toContain('if (programmaticSceneId)')
  expect(source).not.toContain('new IntersectionObserver')
})

it('places scene status inside the storyboard main gutter instead of reserving another shell rail', () => {
  expect(source).toContain('<section class="storyboard-main"')
  expect(source).toContain('<ShortDramaSceneStatusRail')
  expect(source).not.toContain('show-scene-status-rail')
  expect(source).toContain("'--short-drama-scene-status-offset': `${chapterToolbarHeight}px`")
})

it('keeps creation actions local to each scene and exposes configured batch generation', () => {
  expect(source).toContain('@click="insertSceneAfter(scene)"')
  expect(source).toContain('在下方添加分镜')
  expect(source.indexOf('@click="insertSceneAfter(scene)"')).toBeLessThan(source.indexOf('@click="duplicateScene(scene)"'))
  expect(source).toContain('@click="openBatchVideoDialog"')
  expect(source).toContain('<ShortDramaBatchVideoDialog')
  expect(source).toContain('@generate="batchGenerateVideos"')
  expect(source).toContain('批量生视频')
  expect(source).toContain('Math.min(model.concurrency, targets.length)')
  expect(source).toContain('class="chapter-model-select"')
})
