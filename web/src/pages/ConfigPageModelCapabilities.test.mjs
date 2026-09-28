import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const configPageSource = readFileSync('src/pages/ConfigPage.vue', 'utf8')
const agentPageSource = readFileSync('src/pages/ShortDramaAgentPage.vue', 'utf8')

it('exposes remake decomposition as an explicit LLM capability', () => {
  expect(configPageSource).toContain('taskTypes: [1, 3, 5, 6, 7]')
  expect(configPageSource).not.toContain("id: 'remake'")
  expect(configPageSource).toContain("get 5() { return tr('项目分析') }")
  expect(configPageSource).toContain("get 6() { return tr('重制') }")
  expect(configPageSource).toContain('supports_tool_calls')
})

it('keeps model configuration out of the project analysis result', () => {
  expect(agentPageSource).not.toContain('MODEL READINESS')
  expect(agentPageSource).not.toContain('模型能力')
  expect(agentPageSource).not.toContain('loadModels')
})
