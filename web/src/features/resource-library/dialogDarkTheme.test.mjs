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

  it('ensures video card cover has overflow hidden and play button is centered', () => {
    const vuePath = path.resolve(__dirname, 'ResourceLibraryBrowser.vue')
    const vueContent = fs.readFileSync(vuePath, 'utf-8')

    // 验证封面容器带有 overflow: hidden 与 16/9 固定比例，防止非 16:9 图片溢出撑破
    expect(vueContent).toContain('.library-cover { position:relative; width:100%; aspect-ratio:16/9;')
    expect(vueContent).toContain('overflow:hidden;')
    // 验证播放按钮绝对居中
    expect(vueContent).toContain('.library-play { position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);')
    // 验证时长定位在封面右下角
    expect(vueContent).toContain('.library-cover small { position:absolute; right:8px; bottom:8px;')
  })
})
