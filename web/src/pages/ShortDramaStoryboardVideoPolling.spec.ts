import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api, ApiRequestError } from '@/api'
import ShortDramaStoryboardPage from './ShortDramaStoryboardPage.vue'
import ScenePromptEditor from '@/components/ScenePromptEditor.vue'
import { injectLastFrameContinuityInstruction } from '@/shared/lastFrameContinuity'
import type { Scene, VideoGenerationModel } from '@/types'

vi.mock('@/api', async importOriginal => {
  const original = await importOriginal<typeof import('@/api')>()
  return { ...original, api: { ...original.api, novelMeta: vi.fn(), chapters: vi.fn(),
    videoGenerationModels: vi.fn(), workbenchBootstrap: vi.fn(), queryVideo: vi.fn(), generateVideo: vi.fn(),
    extractVideoLastFrame: vi.fn(), videoGenerationHistory: vi.fn(), scene: vi.fn(), updateScene: vi.fn() } }
})

const chapter = { id: 450, novel_id: 9, number: 1, name: '第一章', content: '', created_at: '', updated_at: '' }
const scene = { id: 109, chapter_id: 450, sequence: 1, description: '等待后台结果', prompt: '人物向前走',
  duration: 6, metadata: { current_video_id: 37 }, created_at: '', updated_at: '' }
const pending = { id: 37, scene_id: 109, status: 2, model_type: 1, url: null, metadata: {}, created_at: '', updated_at: '' }
const completed = { ...pending, status: 3, url: '/media/finished.mp4' }
const wrappers: ReturnType<typeof mount>[] = []
const model: VideoGenerationModel = { config_id: 11, name: '测试视频模型', model: 'test-video', model_type: 'seedance_2', concurrency: 1, capabilities: {
  resolutions: ['480p'], default_resolution: '480p', aspect_ratios: ['16:9'],
  aspect_ratios_by_mode: { reference: ['16:9'], keyframes: ['16:9'] }, default_aspect_ratio: '16:9',
  duration_min: 2, duration_max: 15, default_output_format: 'mp4',
  generation_modes: ['reference', 'keyframes'], output_formats: ['mp4'], supports_auto_duration: false,
  supports_audio: true, supports_return_last_frame: true, default_generate_audio: true,
  max_reference_images: 9, max_reference_videos: 3, max_reference_audios: 3,
  reference_video_duration_max: 15, reference_video_total_duration_max: 15,
  reference_audio_duration_max: 15, reference_audio_total_duration_max: 15,
  reference_image_formats: ['png'], reference_video_formats: ['mp4'], reference_video_codecs: ['h264'],
  reference_video_audio_codecs: ['aac'], reference_video_resolutions: ['480p'],
  reference_image_max_size_mb: 30, reference_video_max_size_mb: 200, reference_media_duration_min: 2,
  reference_media_ratio_min: 0.4, reference_media_ratio_max: 2.5, reference_media_side_min: 300,
  reference_media_side_max: 6000, reference_video_pixels_min: 409600, reference_video_pixels_max: 8295044,
  reference_video_fps_min: 24, reference_video_fps_max: 60,
} }

beforeEach(() => {
  vi.useFakeTimers(); vi.clearAllMocks(); sessionStorage.clear()
  vi.mocked(api.novelMeta).mockResolvedValue({ data: { id: 9, name: '状态回归', author: 'Agent 创建', created_at: '', updated_at: '' } } as never)
  vi.mocked(api.chapters).mockResolvedValue({ data: { items: [chapter], pagination: { page: 1, pages: 1 } } } as never)
  vi.mocked(api.videoGenerationModels).mockResolvedValue({ data: [] } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene)], assets: [], videos: { 109: [pending] } } } as never)
  vi.mocked(api.updateScene).mockReset()
  vi.mocked(api.scene).mockReset()
})
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()); vi.useRealTimers(); vi.restoreAllMocks(); delete document.documentElement.dataset.appTheme })

async function render() {
  const router = createRouter({ history: createMemoryHistory(), routes: [
    { path: '/create/short-drama/storyboard/:projectId', component: ShortDramaStoryboardPage },
  ] })
  await router.push('/create/short-drama/storyboard/9?chapter=450'); await router.isReady()
  const wrapper = mount(ShortDramaStoryboardPage, { global: { plugins: [createPinia(), router], stubs: {
    ShortDramaWorkspaceShell: { template: '<div><slot name="header-end" /><slot /></div>' },
    DeferredVideoPlayer: { props: ['src'], template: '<video data-testid="preview" :src="src" />' },
  } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, router }
}

it('resumes an existing task and displays a background completion without refreshing or generating', async () => {
  vi.mocked(api.queryVideo).mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  expect(api.queryVideo).toHaveBeenCalled()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  expect(wrapper.find('.preview-empty.is-running').exists()).toBe(false)
  expect(api.generateVideo).not.toHaveBeenCalled()
})

it('extracts an existing video tail and updates the next shot reference without refreshing or generating', async () => {
  const nextScene = { ...scene, id: 110, sequence: 2, prompt: '保留下一镜头的画面', metadata: {} }
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene), nextScene], assets: [], videos: { 109: [completed] } } } as never)
  vi.mocked(api.extractVideoLastFrame).mockResolvedValue({ data: { ...completed, metadata: {
    last_frame_url: '/media/tail.png', last_frame_source: 'ffmpeg', last_frame_injected_scene_id: 110,
    last_frame_reference: { type: 'image', url: '/media/tail.png', name: '本镜头尾帧.png' },
    last_frame_prompt_instruction: '【首帧衔接】\n首帧参考：@{参考图片:/media/tail.png}',
  } } } as never)
  const { wrapper } = await render()
  const trigger = wrapper.findAll('button').find(button => button.text().includes('提取尾帧'))!
  await trigger.trigger('click'); await flushPromises()
  expect(api.extractVideoLastFrame).toHaveBeenCalledWith(37)
  expect(wrapper.text()).toContain('下载尾帧')
  expect(wrapper.text()).toContain('保留下一镜头的画面')
  expect(wrapper.text()).toContain('首帧衔接')
  expect(wrapper.find('img[src="/media/tail.png"]').exists()).toBe(true)
  expect(api.generateVideo).not.toHaveBeenCalled()
})

it.each(['zh', 'en'])('saves the next shot against the injected server prompt while preserving local edits (%s)', async language => {
  vi.mocked(api.videoGenerationModels).mockResolvedValue({ data: [model] } as never)
  const instruction = language === 'zh' ? '【首帧衔接】\n首帧参考：@{参考图片:%2Fmedia%2Ftail.png}'
    : '[First-frame continuity]\nFirst-frame reference: @{参考图片:%2Fmedia%2Ftail.png}'
  const original = '【镜头描述】\n保留下一镜头的画面'
  const edited = '【镜头描述】\n用户正在修改的动作'
  const nextScene = { ...scene, id: 110, sequence: 2, prompt: original, metadata: {} }
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene), nextScene], assets: [], videos: { 109: [pending] } } } as never)
  vi.mocked(api.queryVideo).mockResolvedValueOnce({ data: pending } as never).mockResolvedValue({ data: {
    ...completed, metadata: { last_frame_injected_scene_id: 110, last_frame_prompt_instruction: instruction,
      last_frame_reference: { type: 'image', url: '/media/tail.png', name: '尾帧.png' } },
  } } as never)
  const serverPrompt = injectLastFrameContinuityInstruction(original, instruction)
  let storedPrompt: string | null = serverPrompt
  vi.mocked(api.updateScene).mockImplementation(async (_id, values, expected) => {
    if (expected !== storedPrompt) throw new ApiRequestError('提示词已被其他操作修改', 409, 200)
    storedPrompt = values.prompt ?? null
    return { data: { ...nextScene, ...values } } as never
  })
  vi.mocked(api.generateVideo).mockResolvedValue({ data: { ...completed, id: 38, scene_id: 110 } } as never)
  const { wrapper } = await render()
  wrapper.findAllComponents(ScenePromptEditor)[1]!.vm.$emit('update:modelValue', edited)
  await flushPromises()
  window.dispatchEvent(new Event('focus')); await flushPromises()
  const trigger = wrapper.get('#scene-110 button[aria-label="生成视频"]')
  await trigger.trigger('click'); await flushPromises()
  expect(api.updateScene).toHaveBeenCalledWith(110, expect.objectContaining({
    prompt: injectLastFrameContinuityInstruction(edited, instruction),
  }), serverPrompt)
  expect(api.generateVideo).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('用户正在修改的动作')
  const saved = injectLastFrameContinuityInstruction(edited, instruction)
  wrapper.findAllComponents(ScenePromptEditor)[1]!.vm.$emit('update:modelValue', `${saved}\n继续调整`)
  await flushPromises(); await vi.advanceTimersByTimeAsync(600); await flushPromises()
  expect(api.updateScene).toHaveBeenLastCalledWith(110, expect.objectContaining({ prompt: `${saved}\n继续调整` }), saved)
  expect(api.generateVideo).toHaveBeenCalledTimes(1)
})

it.each([409, 500])('does not submit a paid generation when saving fails (%s)', async code => {
  vi.mocked(api.videoGenerationModels).mockResolvedValue({ data: [model] } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene)], assets: [], videos: {} } } as never)
  vi.mocked(api.updateScene).mockRejectedValue(new ApiRequestError('保存失败', code, 200))
  vi.mocked(api.scene).mockResolvedValue({ data: { ...scene, prompt: '【首帧衔接】\n首帧参考：@{参考图片:tail}\n\n其他用户修改的画面',
    metadata: { previous_scene_last_frame_prompt_instruction: '【首帧衔接】\n首帧参考：@{参考图片:tail}' } } } as never)
  const { wrapper } = await render()
  wrapper.findComponent(ScenePromptEditor).vm.$emit('update:modelValue', '本地修改要保留')
  await flushPromises()
  await wrapper.get('button[aria-label="生成视频"]').trigger('click'); await flushPromises()
  expect(api.generateVideo).not.toHaveBeenCalled()
  expect(api.updateScene).toHaveBeenCalledTimes(1)
  expect(wrapper.text()).toContain('本地修改要保留')
  expect(wrapper.find('.preview-empty.is-running').exists()).toBe(false)
})

it('reconciles only a known server continuity prefix on a save race, then submits the saved draft', async () => {
  vi.mocked(api.videoGenerationModels).mockResolvedValue({ data: [model] } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene)], assets: [], videos: {} } } as never)
  const instruction = '【首帧衔接】\n首帧参考：@{参考图片:%2Fmedia%2Ftail.png}'
  const remote: Scene = { ...scene, prompt: injectLastFrameContinuityInstruction(scene.prompt, instruction), metadata: {
    previous_scene_last_frame_prompt_instruction: instruction,
    video_reference_media: [{ type: 'image', url: '/media/tail.png', mention_url: '/media/tail.png', name: '尾帧.png' }],
  } }
  vi.mocked(api.scene).mockResolvedValue({ data: remote } as never)
  vi.mocked(api.updateScene).mockRejectedValueOnce(new ApiRequestError('提示词已被其他操作修改', 409, 200))
    .mockImplementation(async (_id, values) => ({ data: { ...remote, ...values } }) as never)
  vi.mocked(api.generateVideo).mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  wrapper.findComponent(ScenePromptEditor).vm.$emit('update:modelValue', '保留本地动作')
  await flushPromises()
  await wrapper.get('button[aria-label="生成视频"]').trigger('click'); await flushPromises()
  expect(api.updateScene).toHaveBeenCalledTimes(2)
  expect(api.updateScene).toHaveBeenLastCalledWith(109, expect.objectContaining({
    prompt: injectLastFrameContinuityInstruction('保留本地动作', instruction),
    metadata: expect.objectContaining({ video_reference_media: expect.arrayContaining([expect.objectContaining({ url: '/media/tail.png' })]) }),
  }), remote.prompt)
  expect(api.generateVideo).toHaveBeenCalledTimes(1)
})

it('stops after a second save conflict instead of retrying indefinitely or generating', async () => {
  vi.mocked(api.videoGenerationModels).mockResolvedValue({ data: [model] } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValue({ data: { chapter, scenes: [structuredClone(scene)], assets: [], videos: {} } } as never)
  const instruction = '【首帧衔接】\n首帧参考：@{参考图片:%2Fmedia%2Ftail.png}'
  vi.mocked(api.scene).mockResolvedValue({ data: { ...scene, prompt: injectLastFrameContinuityInstruction(scene.prompt, instruction),
    metadata: { previous_scene_last_frame_prompt_instruction: instruction } } } as never)
  vi.mocked(api.updateScene).mockRejectedValue(new ApiRequestError('提示词再次被修改', 409, 200))
  const { wrapper } = await render()
  await wrapper.get('button[aria-label="生成视频"]').trigger('click'); await flushPromises()
  expect(api.updateScene).toHaveBeenCalledTimes(2)
  expect(api.generateVideo).not.toHaveBeenCalled()
  expect(wrapper.find('.preview-empty.is-running').exists()).toBe(false)
})

it.each(['light', 'dark'])('reconnects after a temporary failure and replaces the spinner in %s mode', async theme => {
  document.documentElement.dataset.appTheme = theme
  vi.mocked(api.queryVideo).mockRejectedValueOnce(new TypeError('Failed to fetch')).mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  expect(wrapper.text()).toContain('正在重新同步')
  await vi.advanceTimersByTimeAsync(4000); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  expect(wrapper.text()).not.toContain('正在重新同步')
  expect(api.generateVideo).not.toHaveBeenCalled()
})

it('synchronizes immediately on window focus and stops requests after unmount', async () => {
  vi.mocked(api.queryVideo).mockResolvedValueOnce({ data: pending } as never).mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  window.dispatchEvent(new Event('focus')); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  const calls = vi.mocked(api.queryVideo).mock.calls.length
  wrapper.unmount()
  await vi.advanceTimersByTimeAsync(60000)
  window.dispatchEvent(new Event('focus')); await flushPromises()
  expect(api.queryVideo).toHaveBeenCalledTimes(calls)
})

it('does not let an earlier processing response overwrite a completion obtained on focus', async () => {
  let finishEarlier: (value: unknown) => void = () => {}
  vi.mocked(api.queryVideo).mockImplementationOnce(() => new Promise(resolve => { finishEarlier = resolve as typeof finishEarlier }))
    .mockResolvedValue({ data: completed } as never)
  const { wrapper } = await render()
  window.dispatchEvent(new Event('focus')); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  finishEarlier({ data: pending }); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/finished.mp4')
  await vi.advanceTimersByTimeAsync(8000)
  expect(api.queryVideo).toHaveBeenCalledTimes(2)
})

it('ignores a previous chapter response without resetting another chapter or its prompt', async () => {
  const nextChapter = { ...chapter, id: 451, number: 2, name: '第二章' }
  const nextScene = { ...scene, id: 110, chapter_id: 451, prompt: '第二章独立提示词', metadata: { current_video_id: 39 } }
  vi.mocked(api.chapters).mockResolvedValue({ data: { items: [chapter, nextChapter], pagination: { page: 1, pages: 1 } } } as never)
  vi.mocked(api.workbenchBootstrap).mockResolvedValueOnce({ data: { chapter, scenes: [structuredClone(scene)], assets: [], videos: { 109: [pending] } } } as never)
    .mockResolvedValue({ data: { chapter: nextChapter, scenes: [nextScene], assets: [], videos: { 110: [{ ...completed, id: 39, scene_id: 110, url: '/media/next-chapter.mp4' }] } } } as never)
  let finishEarlier: (value: unknown) => void = () => {}
  vi.mocked(api.queryVideo).mockImplementation(() => new Promise(resolve => { finishEarlier = resolve as typeof finishEarlier }))
  const { wrapper, router } = await render()
  await router.push('/create/short-drama/storyboard/9?chapter=451'); await flushPromises()
  finishEarlier({ data: completed }); await flushPromises()
  expect(wrapper.get('[data-testid="preview"]').attributes('src')).toBe('/media/next-chapter.mp4')
  expect(wrapper.text()).toContain('第二章独立提示词')
})

it.each([401, 403, 404])('does not endlessly retry an unavailable or inaccessible video (%s)', async code => {
  vi.mocked(api.queryVideo).mockRejectedValue(new ApiRequestError('无法读取当前视频', code, 200))
  const { wrapper } = await render()
  expect(wrapper.text()).toContain('无法读取当前视频')
  expect(wrapper.text()).toContain('视频状态暂未同步')
  expect(wrapper.find('.preview-empty.is-running').exists()).toBe(false)
  await vi.advanceTimersByTimeAsync(60000)
  expect(api.queryVideo).toHaveBeenCalledTimes(1)
  expect(api.generateVideo).not.toHaveBeenCalled()
})
