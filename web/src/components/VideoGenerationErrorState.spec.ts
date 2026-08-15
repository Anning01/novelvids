import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import VideoGenerationErrorState from './VideoGenerationErrorState.vue'

const privacyError = "视频供应商请求失败：The request failed because the input image 'content[3]' may contain real person. Request id: req-123 (InputImageSensitiveContentDetected.PrivacyInformation)（HTTP 400，request_id=req-123）"

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
})
