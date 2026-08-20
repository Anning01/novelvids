export type VideoGenerationErrorCategory = 'privacy' | 'download' | 'other'

export interface VideoGenerationErrorInfo {
  title: string
  message: string
  suggestion: string
  raw: string
  errorCode?: string
  requestId?: string
  httpStatus?: number
  referenceImageNumber?: number
  category: VideoGenerationErrorCategory
}

const PRIVACY_ERROR_CODE = 'InputImageSensitiveContentDetected.PrivacyInformation'

function firstMatch(value: string, expressions: RegExp[]) {
  for (const expression of expressions) {
    const match = value.match(expression)
    if (match?.[1]) return match[1]
  }
  return undefined
}

function readableProviderMessage(raw: string) {
  return raw
    .replace(/^视频供应商(?:请求)?失败[：:]?\s*/u, '')
    .replace(/\s*Request id:\s*[\w-]+\.?/giu, '')
    .replace(/\s*\([A-Za-z][A-Za-z0-9_.-]+\)\s*/gu, ' ')
    .replace(/\s*（[A-Za-z][A-Za-z0-9_.-]+）\s*/gu, ' ')
    .replace(/\s*（HTTP\s*\d+[^）]*）\s*$/u, '')
    .replace(/\s+/gu, ' ')
    .trim()
}

export function formatVideoGenerationError(rawError: string): VideoGenerationErrorInfo {
  const raw = rawError.trim()
  const requestId = firstMatch(raw, [
    /Request id:\s*([\w-]+)/iu,
    /request_id[=:]\s*([\w-]+)/iu,
  ])
  const errorCode = firstMatch(raw, [
    /\(([A-Za-z][A-Za-z0-9_.-]+)\)\s*[（(]?HTTP/iu,
    /（([A-Za-z][A-Za-z0-9_.-]+)）\s*（HTTP/iu,
  ])
  const httpStatusText = firstMatch(raw, [/HTTP\s*(\d{3})/iu])
  const httpStatus = httpStatusText ? Number(httpStatusText) : undefined
  const contentIndexText = firstMatch(raw, [
    /input image\s*['"]?content\[(\d+)\]/iu,
    /content\[(\d+)\]\.image_uri/iu,
    /content\[(\d+)\]/iu,
  ])
  const referenceNumber = contentIndexText ? Number(contentIndexText) : undefined

  const isPrivacyError = raw.includes(PRIVACY_ERROR_CODE) || /may contain real person/iu.test(raw)
  const isDownloadError =
    !isPrivacyError &&
    (/resource download failed/iu.test(raw) ||
      (/image_uri/iu.test(raw) && /not valid/iu.test(raw)))

  if (isPrivacyError) {
    const target = referenceNumber && referenceNumber > 0
      ? `第 ${referenceNumber} 张参考图`
      : '参考图片'
    return {
      title: `${target}包含真人信息`,
      message: `${target}可能包含真实人物，供应商因隐私保护拒绝了本次生成。`,
      suggestion: '请删除或替换这张参考图，确认素材已获授权，或改用非真人形象后重试。',
      raw,
      errorCode: errorCode || PRIVACY_ERROR_CODE,
      requestId,
      httpStatus,
      referenceImageNumber: referenceNumber,
      category: 'privacy',
    }
  }

  if (isDownloadError) {
    const target = referenceNumber && referenceNumber > 0
      ? `第 ${referenceNumber} 张参考图`
      : '参考图片'
    return {
      title: `${target}下载失败`,
      message: `${target}地址无效或无法被供应商下载，请检查该素材是否可正常访问。`,
      suggestion: '请尝试重新上传参考素材，或在素材列表替换为有效图片后重新生成。',
      raw,
      errorCode,
      requestId,
      httpStatus,
      referenceImageNumber: referenceNumber,
      category: 'download',
    }
  }

  return {
    title: '视频生成失败',
    message: readableProviderMessage(raw) || '供应商未能完成本次视频生成。',
    suggestion: '请检查参考素材与生成参数后重试；若仍然失败，可在技术详情中复制请求编号进行排查。',
    raw,
    errorCode,
    requestId,
    httpStatus,
    category: 'other',
  }
}
