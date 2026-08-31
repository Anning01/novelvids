import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'
import ScenePromptFocusDialog from './ScenePromptFocusDialog.vue'
import type { ScenePromptMentionOption } from './ScenePromptEditor.vue'

const options: ScenePromptMentionOption[] = [{
  id: 'person-1',
  kind: 'person',
  label: '林冲',
  syntax: '@{林冲}',
  group: '出镜角色',
  previewUrl: '/media/linchong.png',
}]

afterEach(() => {
  document.body.style.overflow = ''
  document.body.innerHTML = ''
})

function mountDialog(open = false) {
  return mount(ScenePromptFocusDialog, {
    props: {
      open,
      sceneSequence: 3,
      modelValue: '镜头跟随 @{林冲} 进入房间',
      options,
    },
    attachTo: document.body,
    global: {
      stubs: {
        Teleport: true,
        Transition: false,
      },
    },
  })
}

describe('ScenePromptFocusDialog', () => {
  it('opens an accessible focus editor and moves keyboard focus into the prompt', async () => {
    const trigger = document.createElement('button')
    document.body.append(trigger)
    trigger.focus()
    const wrapper = mountDialog()

    await wrapper.setProps({ open: true })
    await nextTick()

    const dialog = wrapper.get('[role="dialog"]')
    const editor = wrapper.get<HTMLElement>('.scene-prompt-editor__input')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(dialog.text()).toContain('分镜 3 · 专注编辑')
    expect(wrapper.find('.scene-prompt-focus__footer button').exists()).toBe(false)
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.activeElement).toBe(editor.element)
  })

  it('edits the same prompt value and reports the updated content to the storyboard', async () => {
    const wrapper = mountDialog(true)
    const editor = wrapper.get<HTMLElement>('.scene-prompt-editor__input')
    editor.element.append(document.createTextNode('，缓慢推进。'))
    await editor.trigger('input')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['镜头跟随 @{林冲} 进入房间，缓慢推进。'])
    expect(wrapper.get('.scene-prompt-focus__footer').text()).toContain('修改自动保存')
  })

  it('closes with Escape from the editor, restores page scrolling and returns focus to the trigger', async () => {
    const trigger = document.createElement('button')
    document.body.append(trigger)
    trigger.focus()
    const wrapper = mountDialog()
    await wrapper.setProps({ open: true })
    await nextTick()

    await wrapper.get('.scene-prompt-editor__input').trigger('keydown', { key: 'Escape' })
    await nextTick()
    expect(wrapper.emitted('close')).toHaveLength(1)

    await wrapper.setProps({ open: false })
    await nextTick()
    expect(document.body.style.overflow).toBe('')
    expect(document.activeElement).toBe(trigger)
  })

  it('closes with Escape even when focus has moved outside the dialog content', async () => {
    const wrapper = mountDialog(true)
    document.body.focus()

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    await nextTick()

    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('exits focus mode with one Escape even when a nested media preview is open', async () => {
    const wrapper = mountDialog(true)
    await wrapper.get('.scene-prompt-editor__mention').trigger('click')
    expect(wrapper.find('[aria-label="图片放大查看"]').exists()).toBe(true)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }))
    await nextTick()
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
