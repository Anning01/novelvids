import { describe, expect, it } from 'vitest'
import { formatVideoGenerationError } from './videoGenerationError'

describe('formatVideoGenerationError', () => {
  it('把真人隐私错误转换为素材序号明确的中文提示', () => {
    const result = formatVideoGenerationError(
      "视频供应商请求失败：The request failed because the input image 'content[2]' may contain real person. Request id: req-123 (InputImageSensitiveContentDetected.PrivacyInformation)（HTTP 400，request_id=req-123）",
    )

    expect(result.title).toBe('第 2 张参考图包含真人信息')
    expect(result.message).toContain('隐私保护')
    expect(result.suggestion).toContain('删除或替换')
    expect(result.errorCode).toBe('InputImageSensitiveContentDetected.PrivacyInformation')
    expect(result.requestId).toBe('req-123')
    expect(result.httpStatus).toBe(400)
    expect(result.referenceImageNumber).toBe(2)
  })

  it('保留未知错误的可读原因与技术字段', () => {
    const result = formatVideoGenerationError(
      '视频供应商请求失败：参考视频时长超出限制（InvalidParameter）（HTTP 422，request_id=req-422）',
    )

    expect(result.title).toBe('视频生成失败')
    expect(result.message).toContain('参考视频时长超出限制')
    expect(result.requestId).toBe('req-422')
    expect(result.httpStatus).toBe(422)
  })

  it('把参考图下载失败转换为带序号的中文提示', () => {
    const result = formatVideoGenerationError(
      "视频供应商请求失败：The parameter `content[1].image_uri` specified in the request is not valid: resource download failed. (InvalidParameterValue)（HTTP 400，request_id=req-400）",
    )

    expect(result.title).toBe('第 1 张参考图下载失败')
    expect(result.message).toContain('无法被供应商下载')
    expect(result.category).toBe('download')
    expect(result.referenceImageNumber).toBe(1)
    expect(result.requestId).toBe('req-400')
    expect(result.httpStatus).toBe(400)
  })
})
