import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import ShortDramaStoryboardPage from './ShortDramaStoryboardPage.vue'
import AppButton from '@/components/AppButton.vue'
import { api } from '@/api'
import { AssetTypeEnum } from '@/types'
import type { Asset, AssetVariant, AudioReference } from '@/types'

vi.mock('@/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api')>()
  return {
    ...actual,
    api: {
      ...actual.api,
      novelMeta: vi.fn(),
      chapters: vi.fn(),
      videoGenerationModels: vi.fn(),
      workbenchBootstrap: vi.fn(),
      audioReferences: vi.fn(),
      updateAsset: vi.fn(),
      updateAssetVariant: vi.fn(),
    },
  }
})

const chapter = {
  id: 348,
  novel_id: 8,
  number: 1,
  name: '第一章',
  content: '章节内容',
  created_at: '',
  updated_at: '',
}

const variant: AssetVariant = {
  id: 101,
  asset_id: 10,
  name: '退休形态',
  chapter_numbers: [1],
  images: [],
  metadata: {
    voice: '老头声音',
    voice_reference_id: 2,
    editor_form: { age_group: '老年', voice: '老头声音', voice_reference_id: 2 },
  },
  created_at: '',
  updated_at: '',
}

const character: Asset = {
  id: 10,
  novel_id: 8,
  asset_type: AssetTypeEnum.PERSON,
  canonical_name: '总工程师',
  metadata: { voice: '儒雅逸辰', voice_reference_id: 1 },
  variants: [variant],
  created_at: '',
  updated_at: '',
}

const selectedVoice: AudioReference = {
  id: 9,
  nickname: '沉稳男声',
  gender: '男',
  audio_url: '/media/voice.mp3',
  avatar_url: '',
  asset_id: '',
  is_active: true,
  created_at: '',
  updated_at: '',
}

const currentVoice: AudioReference = {
  ...selectedVoice,
  id: 2,
  nickname: '老头声音',
  audio_url: '/media/current-voice.mp3',
}

const AudioReferencePickerStub = defineComponent({
  name: 'AudioReferencePicker',
  props: {
    open: Boolean,
    selectedId: { type: Number, default: null },
    novelId: { type: Number, default: undefined },
  },
  emits: ['close', 'choose'],
  template: '<div v-if="open" data-testid="audio-reference-picker" />',
})

function bootstrap(assetVariantId: number | null) {
  return {
    code: 0,
    message: 'ok',
    data: {
      chapter,
      assets: [character],
      scenes: [{
        id: 201,
        chapter_id: chapter.id,
        sequence: 1,
        description: '办公室里的对话',
        prompt: '@总工程师开口说话',
        duration: 6,
        asset_ids: [character.id],
        metadata: { asset_variant_ids: { [character.id]: assetVariantId } },
        created_at: '',
        updated_at: '',
      }],
      videos: {},
    },
  }
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/create/short-drama/storyboard/:projectId', component: ShortDramaStoryboardPage }],
  })
  await router.push('/create/short-drama/storyboard/8?chapter=348')
  await router.isReady()
  return mount(ShortDramaStoryboardPage, {
    global: {
      plugins: [router],
      components: { AppButton },
      stubs: {
        Teleport: true,
        AudioReferencePicker: AudioReferencePickerStub,
        ShortDramaWorkspaceShell: { template: '<div><slot name="header-end" /><slot /></div>' },
      },
    },
  })
}

function openVoicePicker(wrapper: Awaited<ReturnType<typeof mountPage>>) {
  const picker = wrapper.findAllComponents(AudioReferencePickerStub).find(item => item.props('open'))
  if (!picker) throw new Error('音色选择器未打开')
  return picker
}

describe('分镜角色音色选择', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    vi.mocked(api.novelMeta).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        id: 8,
        name: '雾城',
        author: 'Agent 创建',
        description: 'Agent 模式 · 9:16 · 720p · 写实通用',
        total_chapters: 1,
        content_length: 10,
        created_at: '',
        updated_at: '',
      },
    })
    vi.mocked(api.chapters).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { items: [chapter], pagination: { total: 1, page: 1, page_size: 100, pages: 1 } },
    } as never)
    vi.mocked(api.videoGenerationModels).mockResolvedValue({ code: 0, message: 'ok', data: [] } as never)
    vi.mocked(api.workbenchBootstrap).mockResolvedValue(bootstrap(variant.id) as never)
    vi.mocked(api.audioReferences).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: { items: [currentVoice], pagination: { total: 1, page: 1, page_size: 24, pages: 1 } },
    })
  })

  it('点击当前衍生形态的音色后打开项目音频库，并立即保存到该形态', async () => {
    const updatedVariant: AssetVariant = {
      ...variant,
      metadata: {
        ...variant.metadata,
        voice: selectedVoice.nickname,
        voice_reference_id: selectedVoice.id,
        editor_form: { age_group: '老年', voice: selectedVoice.nickname, voice_reference_id: selectedVoice.id },
      },
    }
    vi.mocked(api.updateAssetVariant).mockResolvedValue({ code: 0, message: 'ok', data: updatedVariant })

    const wrapper = await mountPage()
    await flushPromises()
    expect(wrapper.text()).toContain('【角色 / 道具 / 场景引用】')
    expect(wrapper.text()).toContain('角色音色参考：')
    expect(wrapper.text()).toContain('不得复述样本原话')
    expect(wrapper.get('[data-mention-kind="audio"]').text()).toContain('音频1 · 老头声音')
    await wrapper.get('button[aria-label="为总工程师 · 退休形态更换音色"]').trigger('click')

    const picker = openVoicePicker(wrapper)
    expect(picker.props()).toMatchObject({ open: true, selectedId: 2, novelId: 8 })
    picker.vm.$emit('choose', selectedVoice)
    await flushPromises()

    expect(api.updateAssetVariant).toHaveBeenCalledWith(10, 101, {
      metadata: expect.objectContaining({
        voice: '沉稳男声',
        voice_reference_id: 9,
        editor_form: expect.objectContaining({
          age_group: '老年',
          voice: '沉稳男声',
          voice_reference_id: 9,
        }),
      }),
    })
    expect(api.updateAsset).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('沉稳男声')
    expect(picker.props('open')).toBe(false)
  })

  it('当前选择主形象时只保存主形象音色', async () => {
    vi.mocked(api.workbenchBootstrap).mockResolvedValue(bootstrap(null) as never)
    vi.mocked(api.updateAsset).mockResolvedValue({
      code: 0,
      message: 'ok',
      data: {
        ...character,
        metadata: { voice: selectedVoice.nickname, voice_reference_id: selectedVoice.id },
      },
    })

    const wrapper = await mountPage()
    await flushPromises()
    await wrapper.get('button[aria-label="为总工程师更换音色"]').trigger('click')
    const picker = openVoicePicker(wrapper)
    expect(picker.props('selectedId')).toBe(1)
    picker.vm.$emit('choose', selectedVoice)
    await flushPromises()

    expect(api.updateAsset).toHaveBeenCalledWith(10, {
      metadata: expect.objectContaining({ voice: '沉稳男声', voice_reference_id: 9 }),
    })
    expect(api.updateAssetVariant).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('沉稳男声')
  })
})
