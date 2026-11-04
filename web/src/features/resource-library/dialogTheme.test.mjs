import { describe, expect, it } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

describe('resource library theme inheritance', () => {
  it('inherits the selected app theme on the page, dialogs and teleported menus', () => {
    const cssContent = fs.readFileSync(path.resolve(__dirname, 'dialog.css'), 'utf-8')
    const pageContent = fs.readFileSync(path.resolve(__dirname, '../../pages/ResourceLibraryPage.vue'), 'utf-8')

    expect(pageContent).toContain('background: var(--app-canvas)')
    expect(pageContent).toContain('color: var(--app-text)')
    expect(cssContent).toContain('--el-dialog-bg-color: var(--app-surface)')
    expect(cssContent).toContain('--el-text-color-primary: var(--app-text)')
    expect(cssContent).toMatch(/\.resource-library-dialog \.el-dialog__header\s*\{[^}]*background:\s*var\(--app-surface-muted\)/s)
    expect(cssContent).toMatch(/\.resource-library-dialog \.el-dialog__body\s*\{[^}]*background:\s*var\(--app-surface\)/s)
    expect(cssContent).not.toMatch(/color-scheme:\s*dark|--app-(?:surface|text|accent|canvas)[\w-]*:\s*(?:#|rgb)/)
    expect(cssContent).not.toMatch(/resource-library-select-menu|!important/)
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

  it('styles folder, rename and move dialogs like the upload dialog', () => {
    const cssContent = fs.readFileSync(path.resolve(__dirname, 'dialog.css'), 'utf-8')

    expect(cssContent).toMatch(/\.resource-library-dialog\.resource-library-dialog--form \.el-dialog__body\s*\{[^}]*padding:\s*20px 24px 22px/s)
    expect(cssContent).toMatch(/\.resource-library-dialog\.resource-library-dialog--form \.el-dialog__header\s*\{[^}]*padding:\s*16px 24px/s)
    expect(cssContent).toMatch(/\.resource-library-dialog\.resource-library-dialog--form \.el-dialog__footer\s*\{[^}]*border-top:\s*1px solid var\(--app-border\)[^}]*background:\s*var\(--app-surface-muted\)/s)
    expect(cssContent).toMatch(/\.resource-library-dialog\.resource-library-dialog--form \.catalog-form input\s*\{[^}]*border-radius:\s*9px[^}]*font-size:\s*13px/s)
    expect(cssContent).toMatch(/\.catalog-dialog__actions\s*\{[^}]*justify-content:\s*flex-end/s)
  })
})
