const imageTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
const videoTypes = ['video/mp4', 'video/quicktime']

export const imageUploadAccept = imageTypes.join(',')
export const videoUploadAccept = [...videoTypes, '.mp4', '.mov'].join(',')

export function droppedMediaKind(file: File) {
  if (imageTypes.includes(file.type)) return 'image_media'
  if (videoTypes.includes(file.type)) return 'video_media'
  if (!file.type || file.type === 'application/octet-stream') {
    if (/\.(jpe?g|png|webp|gif)$/i.test(file.name)) return 'image_media'
    if (/\.(mp4|mov)$/i.test(file.name)) return 'video_media'
  }
  return null
}
