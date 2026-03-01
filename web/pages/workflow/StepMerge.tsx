import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Film, Loader2, Link2, Eye, EyeOff, Download, Check } from "lucide-react"
import { api } from "@/services/api"
import type { ChapterVideoItem, VideoMergeOut } from "@/types"
import { toast } from "sonner"
import { modelLabel } from "@/lib/helpers"

interface StepMergeProps {
  chapterId: number
}

export const StepMerge = ({ chapterId }: StepMergeProps) => {
  const [items, setItems] = useState<ChapterVideoItem[]>([])
  const [loading, setLoading] = useState(true)
  const [merging, setMerging] = useState(false)
  const [showOnlyWithVideo, setShowOnlyWithVideo] = useState(true)
  const [mergedResult, setMergedResult] = useState<VideoMergeOut | null>(null)

  const loadChapterVideos = async () => {
    try {
      setLoading(true)
      const res = await api.getChapterVideos(chapterId)
      setItems(res.data)
    } catch (err) {
      toast.error((err as Error).message || "加载视频失败")
    } finally {
      setLoading(false)
    }
  }

  const loadMergedVideo = async () => {
    try {
      const res = await api.getMergedVideo(chapterId)
      setMergedResult(res.data)
    } catch {
      // 没有合并视频，忽略错误
      setMergedResult(null)
    }
  }

  useEffect(() => {
    loadChapterVideos()
    loadMergedVideo()
  }, [chapterId])

  // 可见的项目
  const visibleItems = showOnlyWithVideo
    ? items.filter((item) => item.video !== null)
    : items

  // 所有分镜的总时长（不管是否有视频）
  const totalDuration = items.reduce((sum, item) => sum + (item.duration || 0), 0)
  // 所有分镜都有视频才能合并
  const canMerge = items.length > 0 && items.every((i) => i.video !== null)

  const handleMerge = async () => {
    const itemsWithoutVideo = items.filter((i) => i.video === null)
    if (itemsWithoutVideo.length > 0) {
      toast.info(`以下分镜尚未生成视频：#${itemsWithoutVideo.map(i => i.sequence).join(', #')}`)
      return
    }
    try {
      setMerging(true)
      const res = await api.mergeChapterVideos({ chapter_id: chapterId })
      setMergedResult(res.data)
      toast.success("视频合并完成")
    } catch (err) {
      toast.error((err as Error).message || "合并失败")
    } finally {
      setMerging(false)
    }
  }

  const handleDownload = () => {
    if (mergedResult?.merged_url) {
      window.open(mergedResult.merged_url, '_blank')
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">视频合成</h2>
          <p className="text-muted-foreground mt-1">
            将各分镜生成的视频合并为完整章节视频
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowOnlyWithVideo(!showOnlyWithVideo)}
          >
            {showOnlyWithVideo ? <Eye className="h-4 w-4 mr-2" /> : <EyeOff className="h-4 w-4 mr-2" />}
            {showOnlyWithVideo ? "显示全部" : "只看有视频"}
          </Button>
          <Button onClick={handleMerge} disabled={merging || !canMerge}>
            {merging ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                合并中...
              </>
            ) : (
              <>
                <Link2 className="h-4 w-4 mr-2" />
                合成视频
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Summary */}
      <Card className="p-4 bg-muted/30">
        <div className="flex items-center gap-6 text-sm">
          <div>
            <span className="text-muted-foreground">分镜数量：</span>
            <span className="font-medium">{items.length}</span>
          </div>
          <div>
            <span className="text-muted-foreground">已完成视频：</span>
            <span className="font-medium">{items.filter((i) => i.video !== null).length}/{items.length}</span>
          </div>
          <div>
            <span className="text-muted-foreground">预计时长：</span>
            <span className="font-medium">{totalDuration.toFixed(1)} 秒</span>
          </div>
        </div>
      </Card>

      {/* 合并后的视频预览 */}
      {mergedResult && (
        <Card className="p-4 bg-green-500/10 border-green-500/20">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-green-500/20 flex items-center justify-center">
                <Check className="h-6 w-6 text-green-500" />
              </div>
              <div>
                <p className="font-medium text-green-600 dark:text-green-400">视频合并成功！</p>
                <p className="text-sm text-muted-foreground">
                  合并了 {mergedResult.video_count} 个视频，总时长 {mergedResult.total_duration} 秒
                </p>
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={handleDownload}>
              <Download className="h-4 w-4 mr-2" />
              下载
            </Button>
          </div>
          {/* 视频预览 */}
          <div className="mt-4 rounded-lg overflow-hidden bg-black">
            <video
              src={mergedResult.merged_url}
              controls
              className="w-full max-h-80"
            />
          </div>
        </Card>
      )}

      {/* Loading */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-20 rounded-lg" />
          ))}
        </div>
      ) : (
        /* Scene/Video list */
        <div className="space-y-3">
          {visibleItems.map((item) => (
            <div
              key={item.scene_id}
              className="flex items-center gap-4 p-4 bg-card border rounded-lg hover:border-primary/50 transition-colors group"
            >
              {/* Sequence */}
              <div className="w-16 text-center shrink-0">
                <span className="text-lg font-bold text-muted-foreground">#{item.sequence}</span>
                {item.duration != null && (
                  <div className="text-xs text-muted-foreground">{item.duration}s</div>
                )}
              </div>

              {/* Description */}
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium truncate">
                  {item.description || "暂无描述"}
                </p>
                {item.video && (
                  <div className="flex items-center gap-2 mt-1">
                    <Badge variant="secondary" className="text-xs">
                      {modelLabel(item.video.model_type)}
                    </Badge>
                  </div>
                )}
              </div>

              {/* Video preview / status */}
              <div className="w-32 shrink-0">
                {item.video?.url ? (
                  <video
                    src={item.video.url}
                    className="w-full h-16 object-cover rounded bg-black/40"
                    muted
                    onMouseEnter={(e) => (e.currentTarget as HTMLVideoElement).play()}
                    onMouseLeave={(e) => {
                      const v = e.currentTarget as HTMLVideoElement
                      v.pause()
                      v.currentTime = 0
                    }}
                  />
                ) : (
                  <div className="w-full h-16 rounded bg-secondary/50 flex items-center justify-center">
                    <Film className="h-5 w-5 text-muted-foreground/40" />
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && visibleItems.length === 0 && (
        <div className="text-center py-12 text-muted-foreground">
          <Film className="h-12 w-12 mx-auto mb-4 opacity-50" />
          <p>暂无可合成的视频</p>
          <p className="text-sm mt-1">请先在"视频工作台"生成各分镜的视频</p>
        </div>
      )}
    </div>
  )
}
