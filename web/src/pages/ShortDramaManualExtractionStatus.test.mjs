import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const pageSource = readFileSync('src/pages/ShortDramaManualPage.vue', 'utf8')

it('removes completed extraction tasks from the settings workspace', () => {
  expect(pageSource).toContain("if (extractionTask.value?.status === TaskStatusEnum.COMPLETED) return false")
  expect(pageSource).toContain("v-if=\"project.creationMode === 'agent' && extractionStatusVisible\"")
  expect(pageSource).toMatch(/if \(task\.status === TaskStatusEnum\.COMPLETED\) \{\s*extractionTask\.value = null\s*await refreshAssets\(\)/s)
  expect(pageSource).not.toContain('extraction-task-status.is-success')
})
