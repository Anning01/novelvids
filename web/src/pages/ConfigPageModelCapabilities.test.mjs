import { readFileSync } from 'node:fs'
import { expect, it } from 'vitest'

const configPageSource = readFileSync('src/pages/ConfigPage.vue', 'utf8')
const agentPageSource = readFileSync('src/pages/ShortDramaAgentPage.vue', 'utf8')

it('exposes project analysis as a configurable LLM capability', () => {
  expect(configPageSource).toContain('taskTypes: [1, 3, 5]')
  expect(configPageSource).toContain("5: '项目分析'")
  expect(agentPageSource).toContain('[1, 3, 5].includes(value)')
})
