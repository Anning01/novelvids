import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const storyboardSource = readFileSync('src/pages/ShortDramaStoryboardPage.vue', 'utf8')
const settingsSource = readFileSync('src/pages/ShortDramaManualPage.vue', 'utf8')

it('keeps chapter asset extraction in settings instead of the storyboard', () => {
  expect(storyboardSource).not.toContain('aria-label="提取本章资产"')
  expect(storyboardSource).not.toContain('api.latestExtraction(chapterId)')
  expect(settingsSource).toContain('aria-label="提取本章资产"')
  expect(settingsSource).toContain('@click="extractSelectedChapterAssets"')
})

it('restores the extraction task in settings and hides completed status', () => {
  expect(settingsSource).toContain('api.latestExtraction(selectedChapterId.value)')
  expect(settingsSource).toContain('void monitorExtractionTask(extractionTask.value.id)')
  expect(settingsSource).toContain("if (extractionTask.value?.status === TaskStatusEnum.COMPLETED) return false")
})
