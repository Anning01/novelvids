import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const configPageSource = readFileSync('src/pages/ConfigPage.vue', 'utf8')
const agentPageSource = readFileSync('src/pages/ShortDramaAgentPage.vue', 'utf8')

it('exposes remake decomposition as an explicit LLM capability', () => {
  expect(configPageSource).toContain('taskTypes: [1, 3, 5, 6]')
  expect(configPageSource).not.toContain("id: 'remake'")
  expect(configPageSource).toContain("5: '项目分析'")
  expect(configPageSource).toContain("6: '重制'")
})

it('keeps model configuration out of the project analysis result', () => {
  expect(agentPageSource).not.toContain('MODEL READINESS')
  expect(agentPageSource).not.toContain('模型能力')
  expect(agentPageSource).not.toContain('loadModels')
})
