import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VideoGenerationErrorState from './VideoGenerationErrorState.vue'

const privacyError = "视频供应商请求失败：The request failed because the input image 'content[3]' may contain real person. Request id: req-123 (InputImageSensitiveContentDetected.PrivacyInformation)（HTTP 400，request_id=req-123）"
const downloadError = '视频供应商请求失败：The parameter `content[1].image_uri` specified in the request is not valid: resource download failed. (InvalidParameterValue)（HTTP 400，request_id=req-400）'

describe('VideoGenerationErrorState', () => {
  it('shows the asset nickname and locates the rejected reference', async () => {
    const wrapper = mount(VideoGenerationErrorState, {
      props: {
        error: privacyError,
        reference: {
          number: 3,
          url: '/media/chen.png',
          label: '陈经理',
          source: 'asset',
          assetId: 2,
        },
      },
    })

    expect(wrapper.text()).toContain('参考图「陈经理」包含真人信息')
    expect(wrapper.text()).toContain('参考图「陈经理」可能包含真实人物')
    expect(wrapper.get('.video-generation-error__reference img').attributes('src')).toBe('/media/chen.png')
    await wrapper.get('[aria-label="定位参考图 陈经理"]').trigger('click')
    expect(wrapper.emitted('locateReference')).toEqual([[3]])
  })

  it('下载失败时显示问题参考图昵称与定位按钮', async () => {
    const wrapper = mount(VideoGenerationErrorState, {
      props: {
        error: downloadError,
        reference: {
          number: 1,
          url: '/media/li.png',
          label: '李七夜',
          source: 'asset',
          assetId: 2,
        },
      },
    })

    expect(wrapper.text()).toContain('参考图「李七夜」下载失败')
    expect(wrapper.text()).toContain('参考图「李七夜」地址无效或无法被供应商下载')
    expect(wrapper.get('.video-generation-error__reference img').attributes('src')).toBe('/media/li.png')
    await wrapper.get('[aria-label="定位参考图 李七夜"]').trigger('click')
    expect(wrapper.emitted('locateReference')).toEqual([[1]])
  })
})
