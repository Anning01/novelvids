import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { useWorkbenchStore } from '../store/workbenchStore'
import ChapterNode from './ChapterNode.vue'

const chapter = {
  id: 1107,
  novel_id: 9,
  number: 1,
  name: '开端',
  content: `江城市，第七卫星城。\n${'完整章节内容。'.repeat(80)}全文结尾。`,
  created_at: '2026-08-15T00:00:00.000Z',
  updated_at: '2026-08-15T00:00:00.000Z',
}

function mountChapterNode() {
  return mount(ChapterNode, {
    props: {
      id: 'chapter',
      type: 'chapter',
      label: '第 1 章',
      selected: true,
      connectable: true,
      data: { chapter },
    } as never,
  })
}

beforeEach(() => {
  setActivePinia(createPinia())
})

it('renders the complete chapter as a note without ports or node-frame controls', () => {
  const wrapper = mountChapterNode()
  const editor = wrapper.get<HTMLTextAreaElement>('textarea[aria-label="章节正文"]')

  expect(wrapper.get('article').classes()).toContain('workbench-chapter-note')
  expect(wrapper.get('article').classes()).toContain('is-selected')
  expect(wrapper.text()).toContain('第 1 章')
  expect(editor.element.value).toContain('江城市，第七卫星城。')
  expect(editor.element.value).toContain('全文结尾。')
  expect(wrapper.find('.workbench-node-frame').exists()).toBe(false)
  expect(wrapper.find('.vue-flow__handle').exists()).toBe(false)
  expect(wrapper.find('button').exists()).toBe(false)
  expect(wrapper.text()).not.toContain('双击编辑')
  expect(wrapper.text()).not.toContain('取消')
})

it('edits directly and automatically saves through the chapter API action on blur', async () => {
  const store = useWorkbenchStore()
  const saveChapter = vi.spyOn(store, 'saveChapter').mockResolvedValue({ ...chapter, content: '修改后的章节正文' })
  const wrapper = mountChapterNode()

  const editor = wrapper.get<HTMLTextAreaElement>('textarea[aria-label="章节正文"]')
  expect(editor.element.value).toBe(chapter.content)

  await editor.setValue('修改后的章节正文')
  await editor.trigger('blur')
  await flushPromises()

  expect(saveChapter).toHaveBeenCalledWith({ content: '修改后的章节正文' })
  expect(wrapper.find('button').exists()).toBe(false)
})
