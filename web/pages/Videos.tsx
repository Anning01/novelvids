import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { MonitorPlay, RefreshCw, Trash2, Loader2, Film, X, BookOpen, ArrowLeft, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { Input } from '@/components/ui/input'
import { api } from '@/services/api'
import type { Video, Pagination, Novel } from '@/types'
import { TaskStatusEnum } from '@/types'
import { statusColor, statusLabel, modelLabel } from '@/lib/helpers'
import { toast } from 'sonner'

export const VideosPage = () => {
  const { id: novelIdStr } = useParams<{ id?: string }>()
  const novelId = novelIdStr ? parseInt(novelIdStr) : null

  const [videos, setVideos] = useState<Video[]>([])
  const [novels, setNovels] = useState<Novel[]>([])
  const [currentNovel, setCurrentNovel] = useState<Novel | null>(null)
  const [pagination, setPagination] = useState<Pagination | null>(null)
  const [page, setPage] = useState(1)
  const [searchKeyword, setSearchKeyword] = useState('')
  const [loading, setLoading] = useState(true)
  const [refreshingIds, setRefreshingIds] = useState<Set<number>>(new Set())
  const [deletingIds, setDeletingIds] = useState<Set<number>>(new Set())

  const fetchNovelVideos = async (id: number) => {
    try {
      setLoading(true)
      const [novelRes, videosRes] = await Promise.all([
        api.getNovel(id),
        api.getNovelVideos(id)
      ])
      setCurrentNovel(novelRes.data)
      setVideos(videosRes.data)
    } catch (err: any) {
      toast.error(err.message || '获取项目视频失败')
    } finally {
      setLoading(false)
    }
  }

  const fetchNovels = async (p: number = page, search?: string) => {
    try {
      setLoading(true)
      const res = await api.getNovels(p, 20, search)
      setNovels(res.data.items)
      setPagination(res.data.pagination)
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (novelId) {
      fetchNovelVideos(novelId)
    } else {
      fetchNovels(page, searchKeyword)
    }
  }, [novelId, page])

  // 搜索处理
  const handleSearch = () => {
    setPage(1)
    fetchNovels(1, searchKeyword)
  }

  // 按回车搜索
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch()
    }
  }

  const handleRefreshStatus = async (video: Video) => {
    setRefreshingIds((prev) => new Set(prev).add(video.id))
    try {
      const res = await api.queryVideo(video.id)
      setVideos((prev) =>
        prev.map((v) => (v.id === video.id ? res.data : v)),
      )
      toast.success('状态已刷新')
    } catch (err) {
      toast.error((err as Error).message || '刷新状态失败')
    } finally {
      setRefreshingIds((prev) => {
        const next = new Set(prev)
        next.delete(video.id)
        return next
      })
    }
  }

  const handleDelete = async (video: Video) => {
    if (!window.confirm('确定删除该视频？')) return
    setDeletingIds((prev) => new Set(prev).add(video.id))
    try {
      await api.deleteVideo(video.id)
      toast.success('视频已删除')
      if (novelId) {
        fetchNovelVideos(novelId)
      }
    } catch (err) {
      toast.error((err as Error).message || '删除视频失败')
    } finally {
      setDeletingIds((prev) => {
        const next = new Set(prev)
        next.delete(video.id)
        return next
      })
    }
  }

  const formatDate = (dateStr: string) => {
    const d = new Date(dateStr)
    return d.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const renderVideoPreview = (video: Video) => {
    switch (video.status) {
      case TaskStatusEnum.COMPLETED:
        return (
          <video
            src={video.url}
            muted
            className="h-full w-full object-cover"
          />
        )
      case TaskStatusEnum.PROCESSING:
      case TaskStatusEnum.PENDING:
      case TaskStatusEnum.QUEUED:
        return (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary/10 to-accent/5">
            <Loader2 className="h-10 w-10 animate-spin text-primary/50" />
          </div>
        )
      case TaskStatusEnum.FAILED:
        return (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-destructive/10 to-background">
            <X className="h-10 w-10 text-red-500/70" />
          </div>
        )
      default:
        return (
          <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-muted to-background">
            <Film className="h-10 w-10 text-muted-foreground/30" />
          </div>
        )
    }
  }

  const canRefresh = (video: Video) =>
    video.status !== TaskStatusEnum.COMPLETED &&
    video.status !== TaskStatusEnum.FAILED &&
    video.status !== TaskStatusEnum.CANCELLED

  const totalPages = pagination?.pages ?? 1

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="space-y-4">
        <div className="animate-fade-up flex items-center gap-4">
          {novelId && (
            <Link to="/videos">
              <Button variant="ghost" size="icon" className="flex-shrink-0">
                <ArrowLeft className="h-5 w-5" />
              </Button>
            </Link>
          )}
          <div className="flex-shrink-0">
            <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
              <div className="relative">
                <MonitorPlay className="h-8 w-8 text-primary" />
                <div className="absolute inset-0 blur-lg bg-primary/30 rounded-full" />
              </div>
              <span className="gradient-text">
                {novelId ? (currentNovel?.name || '项目视频') : '视频库'}
              </span>
            </h1>
            <p className="text-muted-foreground mt-1.5 text-sm">
              {novelId
                ? (currentNovel?.description || '该项目下的所有生成视频')
                : '所有项目的生成视频'
              }
            </p>
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            {!novelId && (
              <>
                <Input
                  placeholder="搜索项目名称或作者..."
                  value={searchKeyword}
                  onChange={(e) => setSearchKeyword(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="w-48"
                />
                <Button onClick={handleSearch} disabled={loading} size="icon">
                  <Search className="h-4 w-4" />
                </Button>
              </>
            )}
            <Button
              variant="secondary"
              onClick={() => novelId ? fetchNovelVideos(novelId) : fetchNovels(page, searchKeyword)}
              disabled={loading}
              className="flex-shrink-0"
            >
              <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
              刷新
            </Button>
          </div>
        </div>
      </div>

      {/* Decorative line */}
      <div className="decorative-line animate-fade-in" style={{ animationDelay: '150ms' }} />

      {/* Loading State */}
      {loading && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3 stagger-children">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i}>
              <Skeleton className="aspect-video w-full rounded-t-lg" />
              <CardFooter className="flex flex-col items-start gap-2 p-4">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-4 w-32" />
              </CardFooter>
            </Card>
          ))}
        </div>
      )}

      {/* Empty State - Projects */}
      {!loading && !novelId && novels.length === 0 && (
        <div className="animate-scale-in flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-muted-foreground/20 p-16 relative overflow-hidden">
          <div className="absolute inset-0 animate-shimmer" />
          <MonitorPlay className="mb-4 h-16 w-16 text-muted-foreground/30 animate-float" />
          <p className="text-lg font-semibold text-muted-foreground">暂无项目</p>
          <p className="text-sm text-muted-foreground/60 mt-2">请先创建项目</p>
        </div>
      )}

      {/* Empty State - Videos */}
      {!loading && novelId && videos.length === 0 && (
        <div className="animate-scale-in flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-muted-foreground/20 p-16 relative overflow-hidden">
          <div className="absolute inset-0 animate-shimmer" />
          <MonitorPlay className="mb-4 h-16 w-16 text-muted-foreground/30 animate-float" />
          <p className="text-lg font-semibold text-muted-foreground">暂无视频</p>
          <p className="text-sm text-muted-foreground/60 mt-2">该项目还没有生成任何视频</p>
        </div>
      )}

      {/* Projects Grid */}
      {!loading && !novelId && novels.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3 stagger-children">
            {novels.map((novel) => (
              <Link key={novel.id} to={`/videos/novel/${novel.id}`} className="group">
                <Card className="card-glow overflow-hidden transition-all duration-300 hover:ring-2 hover:ring-primary/30 hover:shadow-xl hover:shadow-primary/5 hover:-translate-y-0.5">
                  {/* Cover Area */}
                  <div className="relative aspect-video overflow-hidden">
                    {novel.cover ? (
                      <img
                        src={novel.cover}
                        alt={novel.name}
                        className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                      />
                    ) : (
                      <div className="flex h-full w-full items-center justify-center bg-gradient-to-br from-primary/20 via-primary/5 to-accent/10">
                        <BookOpen className="h-12 w-12 text-muted-foreground/20 group-hover:text-primary/30 transition-colors duration-300" />
                      </div>
                    )}
                    {/* Gradient Overlay */}
                    <div className="absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black/70 via-black/30 to-transparent" />
                    {/* Chapter Count Badge */}
                    <Badge
                      variant="secondary"
                      className="absolute bottom-2.5 left-2.5 text-xs backdrop-blur-sm bg-black/40 border-white/10 text-white/90"
                    >
                      {novel.total_chapters ?? 0} 章节
                    </Badge>
                  </div>
                  {/* Info */}
                  <CardContent className="p-4 space-y-1.5">
                    <h3 className="font-semibold text-base truncate group-hover:text-primary transition-colors duration-200">{novel.name}</h3>
                    {novel.author && (
                      <p className="text-sm text-muted-foreground">{novel.author}</p>
                    )}
                    {novel.description && (
                      <p className="text-sm text-muted-foreground/60 line-clamp-2">
                        {novel.description}
                      </p>
                    )}
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-center gap-4 pt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
              >
                上一页
              </Button>
              <span className="text-sm text-muted-foreground">
                第 {page} / {totalPages} 页
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
              >
                下一页
              </Button>
            </div>
          )}
        </>
      )}

      {/* Videos Grid */}
      {!loading && novelId && videos.length > 0 && (
        <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-3 stagger-children">
          {videos.map((video) => (
            <Card key={video.id} className="card-glow group overflow-hidden transition-all duration-300 hover:ring-2 hover:ring-primary/30 hover:shadow-xl hover:shadow-primary/5 hover:-translate-y-0.5">
              <CardContent className="relative p-0">
                {/* Video Preview */}
                <div className="aspect-video overflow-hidden">
                  {renderVideoPreview(video)}
                </div>

                {/* Status Badge */}
                <Badge
                  variant={statusColor(video.status) as any}
                  className="absolute left-2.5 top-2.5 backdrop-blur-sm"
                >
                  {statusLabel(video.status)}
                </Badge>

                {/* Hover Overlay */}
                <div className="absolute inset-0 flex items-center justify-center gap-3 bg-black/60 backdrop-blur-sm opacity-0 transition-all duration-200 group-hover:opacity-100">
                  {canRefresh(video) && (
                    <Button
                      size="icon"
                      variant="secondary"
                      className="h-10 w-10 rounded-full"
                      onClick={() => handleRefreshStatus(video)}
                      disabled={refreshingIds.has(video.id)}
                    >
                      {refreshingIds.has(video.id) ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <RefreshCw className="h-4 w-4" />
                      )}
                    </Button>
                  )}
                  <Button
                    size="icon"
                    variant="destructive"
                    className="h-10 w-10 rounded-full"
                    onClick={() => handleDelete(video)}
                    disabled={deletingIds.has(video.id)}
                  >
                    {deletingIds.has(video.id) ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Trash2 className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </CardContent>

              <CardFooter className="flex flex-col items-start gap-2 p-4">
                <div className="flex w-full items-center justify-between">
                  <span className="text-sm font-medium">
                    视频 #{video.id}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    场景 #{video.scene_id}
                  </span>
                </div>
                <div className="flex w-full items-center justify-between">
                  <Badge variant="outline">{modelLabel(video.model_type)}</Badge>
                  <span className="text-xs text-muted-foreground">
                    {video.created_at && formatDate(video.created_at)}
                  </span>
                </div>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
