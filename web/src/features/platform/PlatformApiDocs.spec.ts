import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { setLocale } from '@/i18n'
import PlatformApiDocs from './PlatformApiDocs.vue'

beforeEach(() => setLocale('zh'))
afterEach(() => { delete document.documentElement.dataset.appTheme; vi.unstubAllGlobals() })

it.each(['light','dark'])('navigates endpoint documentation and copies complete request examples (%s)', async theme => {
  document.documentElement.dataset.appTheme = theme
  const writeText = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('navigator',{clipboard:{writeText}})
  const w = mount(PlatformApiDocs,{props:{baseUrl:'https://api.example/v1'},global:{stubs:{RouterLink:{template:'<a><slot /></a>'}}}})
  const select = async (title: string) => {
    await w.findAll('nav button').find(button => button.text().startsWith(title))!.trigger('click')
  }
  expect(w.get('.docs-article h2').text()).toBe('身份认证')
  await select('对话生成')
  expect(w.get('.docs-endpoint').text()).toContain('/v1/chat/completions')
  expect(w.get('table').text()).toContain('stream_options')
  expect(w.get('pre').text()).toContain('stream_options={"include_usage": True}')
  await w.get('[aria-label="复制代码"]').trigger('click')
  await flushPromises()
  expect(writeText).toHaveBeenLastCalledWith(w.get('pre').text())
  expect(w.get('[aria-label="复制代码"]').text()).toContain('已复制')
  await select('视频生成')
  expect(JSON.parse(w.get('pre').text())).toMatchObject({seconds:'4', size:'1280x720'})
  expect(w.get('.docs-followup').text()).toContain('/v1/videos/{id}')
  expect(w.get('.docs-followup').text()).toContain('/v1/videos/{id}/content')
  await select('素材直传')
  expect(w.get('pre').text()).toContain('content_md5')
  expect(w.get('.docs-endpoint').text()).toContain('/v1/media/uploads')
  await select('错误处理')
  expect(w.get('pre').text()).toContain('error.response.text')
  expect(w.find('a[href="https://api.example/v1/agent-guide.md"]').exists()).toBe(true)
  await select('查询模型列表')
  expect(w.get('pre').text()).toContain('/models" \\\n  -H')
  expect(w.find('a[href="https://api.example/v1/openapi.json"]').exists()).toBe(true)
  expect(w.text()).not.toMatch(/studio\/media-lease|upload.token/i)
  w.unmount()
})
