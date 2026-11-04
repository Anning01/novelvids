import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import EditorTimeline from '@/features/video-editor/EditorTimeline.vue'
import { editorFixture } from '@/features/video-editor/fixtures'

describe('short drama editing timeline', () => {
  it('renders separate overlay, subtitle, video and music tracks with an accessible scalable ruler', () => {
    const fixture = editorFixture()
    const wrapper = mount(EditorTimeline, { props: { document: fixture.document, media: fixture.media, selectedId: 'v1', time: 0, readOnly: false, canUndo: false, canRedo: false } })
    expect(wrapper.findAll('.editor-track-row')).toHaveLength(4)
    expect(wrapper.findAll('.clip-video')).toHaveLength(3)
    expect(wrapper.find('input[aria-label="时间轴刻度尺寸"]').exists()).toBe(true)
    expect(wrapper.find('.editor-playhead').exists()).toBe(true)
    wrapper.unmount()
  })
  it('offers keyboard alternatives for moving and trimming without changing the source', async () => {
    const fixture = editorFixture()
    const wrapper = mount(EditorTimeline, { props: { document: fixture.document, media: fixture.media, selectedId: 'v1', time: 0, readOnly: false, canUndo: false, canRedo: false } })
    await wrapper.findAll('.clip-video')[0]!.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('move')?.[0]).toEqual(['v1', 1 / 24])
    await wrapper.get('[aria-label="调整片段出点"]').trigger('keydown', { key: 'ArrowLeft' })
    expect(wrapper.emitted('edge')?.[0]).toEqual(['v1', 'right', -1 / 24])
    expect(fixture.document.clips[0]?.duration).toBe(2)
    wrapper.unmount()
  })
})
