import { api } from '@/api'
import { tr } from '@/i18n'
import { appConfirm } from '@/shared/confirmDialog'

export function confirmChapterDeletion(label: string) {
  return appConfirm({
    title: tr('永久删除「{p0}」？', { p0: label }),
    message: tr('本集正文、剧本、分镜、剪辑和成片将永久删除。跨集资产会保留。'),
    confirmLabel: tr('永久删除'),
  })
}

export function confirmVideoDeletion(label: string, published = false) {
  return appConfirm({
    title: tr('永久删除「{p0}」？', { p0: label }),
    message: tr(published ? '该版本将从作品展示中移除，删除后无法恢复。' : '删除后无法恢复。'),
    confirmLabel: tr('永久删除'),
  })
}

export async function confirmAssetDeletion(
  targets: { id: number; variantId?: number; name: string }[],
) {
  const impacts = await Promise.all(targets.map(target => api.assetDeletionImpact(target.id, target.variantId)))
  const shots = new Map(impacts.flatMap(result => result.data).map(shot => [
    `${shot.chapter_number}:${shot.sequence}`, shot,
  ]))
  const details = [...shots.values()].sort((a, b) => a.chapter_number - b.chapter_number || a.sequence - b.sequence)
    .map(shot => tr('第 {p0} 集 · 分镜 {p1}', { p0: shot.chapter_number, p1: shot.sequence }))
  return appConfirm({
    title: targets.length === 1
      ? tr('永久删除「{p0}」？', { p0: targets[0].name })
      : tr('永久删除选中的 {p0} 项资产？', { p0: targets.length }),
    message: details.length
      ? tr('删除后无法恢复。以下 {p0} 个分镜将解除引用，已生成的视频会保留。', { p0: details.length })
      : tr('删除后无法恢复。'),
    details,
    confirmLabel: tr('永久删除'),
  })
}
