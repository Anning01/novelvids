import { expect, it } from 'vitest'
import { createSourceFile, isExpressionStatement, isStringLiteral, ScriptTarget } from 'typescript'
import catalog from './messages.json'

const sources = import.meta.glob<string>('../**/*.{vue,ts}', { query: '?raw', import: 'default', eager: true })

it('provides a translation for every static UI message used by the application', () => {
  const keys = new Set(Object.values(catalog).flatMap(entries => Object.keys(entries)))
  const missing: string[] = []
  for (const [path, content] of Object.entries(sources)) {
    if (/\.(?:spec|test|d)\.ts$/.test(path)) continue
    for (const match of content.matchAll(/\btr\(\s*('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")/g)) {
      const statement = createSourceFile('message.ts', match[1]!, ScriptTarget.Latest).statements[0]
      if (statement && isExpressionStatement(statement) && isStringLiteral(statement.expression)) {
        const source = statement.expression.text
        if (!keys.has(source)) missing.push(`${path}: ${source}`)
      }
    }
  }
  expect(missing).toEqual([])
})
