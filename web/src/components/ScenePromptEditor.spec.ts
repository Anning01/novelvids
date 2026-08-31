import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import AppButton from './AppButton.vue'
import ScenePromptEditor, { type ScenePromptMentionOption } from './ScenePromptEditor.vue'

const options: ScenePromptMentionOption[] = [
  {
    id: 'scene-1',
    kind: 'scene',
    label: '断罪山脉',
    syntax: '@{断罪山脉}',
    group: '分镜场景',
    previewUrl: '/media/mountain.png',
    thumbnailUrl: '/media/mountain.png',
  },
  {
    id: 'person-2',
    kind: 'person',
    label: '艾伦',
    syntax: '@{艾伦}',
    group: '出镜角色',
    previewUrl: '/media/allen.png',
    aliases: ['主角'],
  },
  {
    id: 'duration-3',
    kind: 'duration',
    label: '请设置时长',
    syntax: '@{镜头时长}',
    group: '镜头参数',
  },
  {
    id: 'audio-4',
    kind: 'audio',
    label: '音频1 · 儒雅沧原',
    syntax: '@音频1',
    group: '角色音色参考',
    audioUrl: '/media/voice.mp3',
  },
]

afterEach(() => {
  document.body.innerHTML = ''
  window.getSelection()?.removeAllRanges()
  vi.unstubAllGlobals()
})

describe('ScenePromptEditor', () => {
  it('caps the embedded editor at 600px and scrolls long prompts internally', () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '很长的提示词', options, embedded: true },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    expect(wrapper.classes()).toContain('is-embedded')
    expect(wrapper.find('.scene-prompt-editor__input').exists()).toBe(true)
  })

  it('renders persisted mention syntax as an interactive inline token', async () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '镜头进入 @{断罪山脉}', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    const mention = wrapper.find('[data-mention-id="scene-1"]')
    expect(mention.exists()).toBe(true)
    expect(mention.text()).toBe('断罪山脉')
    await mention.trigger('click')
    expect(wrapper.find('.image-lightbox').exists()).toBe(true)
  })

  it('previews referenced images and videos on hover in focus mode only', async () => {
    const videoOption: ScenePromptMentionOption = {
      id: 'video-5',
      kind: 'video',
      label: '走廊参考视频',
      syntax: '@{视频#走廊参考视频}',
      group: '参考视频',
      previewUrl: '/media/hallway.mp4',
      thumbnailUrl: '/media/hallway.mp4',
    }
    const wrapper = mount(ScenePromptEditor, {
      props: {
        modelValue: '@{断罪山脉} 转场至 @{视频#走廊参考视频}',
        options: [...options, videoOption],
        focusMode: true,
      },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    await wrapper.get('[data-mention-id="scene-1"]').trigger('pointerover')
    expect(wrapper.get('.scene-prompt-hover-preview img').attributes('src')).toBe('/media/mountain.png')
    expect(wrapper.get('.scene-prompt-hover-preview').attributes('role')).toBe('tooltip')
    expect(wrapper.find('.scene-prompt-hover-preview footer').exists()).toBe(false)
    expect(wrapper.get('.scene-prompt-hover-preview').text()).toBe('')

    await wrapper.get('[data-mention-id="scene-1"]').trigger('pointerout')
    expect(wrapper.find('.scene-prompt-hover-preview').exists()).toBe(false)

    await wrapper.get('[data-mention-id="video-5"]').trigger('pointerover')
    const video = wrapper.get('.scene-prompt-hover-preview video')
    expect(video.attributes('src')).toBe('/media/hallway.mp4')
    expect(video.attributes('autoplay')).toBeDefined()
    expect(video.attributes('loop')).toBeDefined()
    expect((video.element as HTMLVideoElement).muted).toBe(true)
  })

  it('centers hover previews above or below the referenced token instead of beside it', async () => {
    vi.stubGlobal('innerWidth', 1000)
    vi.stubGlobal('innerHeight', 800)
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '@{断罪山脉}', options, focusMode: true },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })
    const mention = wrapper.get<HTMLElement>('[data-mention-id="scene-1"]')
    const rect = vi.spyOn(mention.element, 'getBoundingClientRect').mockReturnValue({
      left: 450,
      right: 550,
      top: 500,
      bottom: 520,
      width: 100,
      height: 20,
      x: 450,
      y: 500,
      toJSON: () => ({}),
    })

    await mention.trigger('pointerover')

    expect(wrapper.get('.scene-prompt-hover-preview').attributes('style')).toContain('left: 290px')
    expect(wrapper.get('.scene-prompt-hover-preview').attributes('style')).toContain('top: 251.75px')

    await mention.trigger('pointerout')
    rect.mockReturnValue({
      left: 450,
      right: 550,
      top: 40,
      bottom: 60,
      width: 100,
      height: 20,
      x: 450,
      y: 40,
      toJSON: () => ({}),
    })
    await mention.trigger('pointerover')
    expect(wrapper.get('.scene-prompt-hover-preview').attributes('style')).toContain('left: 290px')
    expect(wrapper.get('.scene-prompt-hover-preview').attributes('style')).toContain('top: 72px')
  })

  it('does not show hover previews outside focus mode', async () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '@{断罪山脉}', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    await wrapper.get('[data-mention-id="scene-1"]').trigger('pointerover')
    expect(wrapper.find('.scene-prompt-hover-preview').exists()).toBe(false)
  })

  it('将音频引用渲染为可点击播放的音色标签', async () => {
    const play = vi.fn().mockResolvedValue(undefined)
    const pause = vi.fn()
    vi.stubGlobal('Audio', class {
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      play = play
      pause = pause
      constructor(public src: string) {}
    })
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '角色音色参考：\n@音频1 对应角色 @{艾伦}', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    const mention = wrapper.get('[data-mention-kind="audio"]')
    expect(mention.text()).toContain('音频1 · 儒雅沧原')
    expect(mention.find('svg').exists()).toBe(true)
    expect(mention.attributes('role')).toBe('button')
    const pointerdown = new MouseEvent('pointerdown', { bubbles: true, cancelable: true })
    mention.element.dispatchEvent(pointerdown)
    expect(pointerdown.defaultPrevented).toBe(true)
    await mention.trigger('click')
    expect(play).toHaveBeenCalledOnce()
    expect(mention.classes()).toContain('is-playing')
    await mention.trigger('click')
    expect(pause).toHaveBeenCalled()
    expect(mention.classes()).not.toContain('is-playing')
  })

  it('renders a legacy mention followed immediately by Chinese text and normalizes it on edit', async () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '走出单元楼。@艾伦沿着步道走', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    const mention = wrapper.get('[data-mention-id="person-2"]')
    expect(mention.text()).toBe('艾伦')
    const editor = wrapper.get<HTMLElement>('.scene-prompt-editor__input')
    editor.element.append(document.createTextNode('。'))
    await editor.trigger('input')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['走出单元楼。@{艾伦}沿着步道走。'])
  })

  it('renders a legacy asset alias as its canonical mention token', () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '@主角沿着步道走', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    const mention = wrapper.get('[data-mention-id="person-2"]')
    expect(mention.text()).toBe('艾伦')
    expect(mention.attributes('data-syntax')).toBe('@{艾伦}')
  })

  it('opens the mention picker when the user types at and inserts a selected reference', async () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '镜头进入 ', options },
      attachTo: document.body,
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    const editor = wrapper.find<HTMLElement>('.scene-prompt-editor__input')
    editor.element.replaceChildren(document.createTextNode('镜头进入 @'))
    const textNode = editor.element.firstChild!
    const range = document.createRange()
    range.setStart(textNode, textNode.textContent?.length || 0)
    range.collapse(true)
    window.getSelection()?.removeAllRanges()
    window.getSelection()?.addRange(range)
    await editor.trigger('input')
    expect(wrapper.find('[role="listbox"]').exists()).toBe(true)
    expect(wrapper.find('.scene-prompt-mentions__actions').text()).toContain('添加镜头时长')
    await wrapper.find('[role="option"]').trigger('pointerdown')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['镜头进入 @{断罪山脉} '])
  })

  it('does not render an instructional hint row above the prompt', () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    expect(wrapper.find('.scene-prompt-editor__hint').exists()).toBe(false)
  })

  it('opens the duration input immediately after selecting the duration action', async () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '镜头进入 ', options },
      attachTo: document.body,
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    const editor = wrapper.find<HTMLElement>('.scene-prompt-editor__input')
    editor.element.replaceChildren(document.createTextNode('镜头进入 @'))
    const textNode = editor.element.firstChild!
    const range = document.createRange()
    range.setStart(textNode, textNode.textContent?.length || 0)
    range.collapse(true)
    window.getSelection()?.removeAllRanges()
    window.getSelection()?.addRange(range)
    await editor.trigger('input')
    await wrapper.find('.scene-prompt-mentions__actions button').trigger('pointerdown')

    expect(wrapper.find('[data-mention-kind="duration"] svg').exists()).toBe(true)
    expect(wrapper.find('.scene-duration-editor').exists()).toBe(true)
    expect(document.activeElement).toBe(wrapper.find('.scene-duration-editor input').element)
  })

  it('emits plain prompt text while preserving mention syntax', async () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '@{艾伦} 出场', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })
    const editor = wrapper.find<HTMLElement>('.scene-prompt-editor__input')
    editor.element.append(document.createTextNode('。'))
    await editor.trigger('input')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['@{艾伦} 出场。'])
  })

  it('opens a compact duration editor and persists the selected seconds in syntax', async () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '镜头持续 @{镜头时长}', options },
      attachTo: document.body,
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    const mention = wrapper.find('[data-mention-kind="duration"]')
    expect(mention.text()).toBe('请设置时长')
    expect(mention.find('svg').exists()).toBe(true)
    await mention.trigger('click')
    const input = wrapper.find<HTMLInputElement>('.scene-duration-editor input')
    expect(input.attributes('min')).toBe('1')
    expect(input.attributes('max')).toBe('30')
    await input.setValue('2.5')
    await wrapper.find('.scene-duration-editor form, .scene-duration-editor').trigger('submit')

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['镜头持续 @{镜头时长:2.5s}'])
    expect(document.activeElement).toBe(wrapper.find('.scene-prompt-editor__input').element)
    const selection = window.getSelection()
    const durationNode = wrapper.find('[data-mention-kind="duration"]').element
    expect(selection?.rangeCount).toBe(1)
    expect(selection?.getRangeAt(0).startContainer).toBe(durationNode.parentNode)
    expect(selection?.getRangeAt(0).startOffset).toBe([...durationNode.parentNode!.childNodes].indexOf(durationNode) + 1)
  })

  it('renders persisted dynamic duration syntax after reload', () => {
    const wrapper = mount(ScenePromptEditor, {
      props: { modelValue: '镜头持续 @{镜头时长:8s}', options },
      global: { components: { AppButton }, stubs: { Teleport: true } },
    })

    expect(wrapper.find('[data-mention-kind="duration"]').text()).toBe('8s')
  })
})
