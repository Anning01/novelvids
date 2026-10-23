import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

describe('resource library dark theme isolation', () => {
  it('enforces dark color scheme and dark surface variables in dialog.css', () => {
    const cssPath = path.resolve(__dirname, 'dialog.css')
    const cssContent = fs.readFileSync(cssPath, 'utf-8')

    expect(cssContent).toContain('.resource-library-dialog')
    expect(cssContent).toContain('color-scheme: dark')
    expect(cssContent).toContain('--app-surface: #211e1b')
    expect(cssContent).toContain('--app-text: #eee9e2')
    expect(cssContent).toContain('--el-dialog-bg-color: #211e1b')
    expect(cssContent).toContain('resource-library-select-menu')
  })
})
