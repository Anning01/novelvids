import React, { useEffect, useState, useCallback } from 'react'
import { Link, useParams, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import {
  BookOpen,
  ChevronRight,
  Edit3,
  Trash2,
  Sparkles,
  Loader2,
  FileText,
  ArrowLeft,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/services/api'
import type { Novel, Chapter, Pagination } from '@/types'

export const NovelDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const novelId = Number(id)

  const [novel, setNovel] = useState<Novel | null>(null)
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [chapterPagination, setChapterPagination] = useState<Pagination | null>(null)
  const [chapterPage, setChapterPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [splitting, setSplitting] = useState(false)

  const [editOpen, setEditOpen] = useState(false)
  const [editForm, setEditForm] = useState({
    name: '',
    author: '',
    description: '',
    content: '',
  })
  const [saving, setSaving] = useState(false)

  const fetchNovel = useCallback(async () => {
    try {
      const res = await api.getNovel(novelId)
      setNovel(res.data)
    } catch (err) {
      console.error('Failed to fetch novel:', err)
    }
  }, [novelId])

  const fetchChapters = useCallback(async (p: number = chapterPage) => {
    try {
      const res = await api.getChapters(novelId, p, 50)
      setChapters(res.data.items)
      setChapterPagination(res.data.pagination)
    } catch (err) {
      console.error('Failed to fetch chapters:', err)
    }
  }, [novelId, chapterPage])

  const loadData = useCallback(async () => {
    setLoading(true)
    await Promise.all([fetchNovel(), fetchChapters(1)])
    setLoading(false)
  }, [fetchNovel, fetchChapters])

  useEffect(() => {
    if (novelId) loadData()
  }, [novelId, loadData])

  useEffect(() => {
    if (chapterPage > 1) fetchChapters(chapterPage)
  }, [chapterPage, fetchChapters])

  const handleEditOpen = () => {
    if (!novel) return
    setEditForm({
      name: novel.name || '',
      author: novel.author || '',
      description: novel.description || '',
      content: novel.content || '',
    })
    setEditOpen(true)
  }

  const handleSave = async () => {
    if (!novel) return
    setSaving(true)
    try {
      const res = await api.updateNovel(novel.id, {
        name: editForm.name,
        author: editForm.author,
        description: editForm.description,
        content: editForm.content,
      })
      setNovel(res.data)
      setEditOpen(false)
      toast.success('小说已更新')
    } catch (err) {
      console.error('Failed to update novel:', err)
      toast.error((err as Error).message || '更新失败')
    } finally {
      setSaving(false)
    }
  }

  const handleSplit = async () => {
    if (!novel) return
    setSplitting(true)
    try {
      await api.splitNovel(novel.id)
      toast.success('章节拆分完成')
      await fetchChapters()
    } catch (err) {
      console.error('Failed to split novel:', err)
      toast.error((err as Error).message || '拆分失败')
    } finally {
      setSplitting(false)
    }
  }

  const handleDeleteNovel = async () => {
    if (!novel) return
    if (!window.confirm(`确定要删除小说「${novel.name}」吗？此操作不可撤销。`)) return
    try {
      await api.deleteNovel(novel.id)
      toast.success('小说已删除')
      navigate('/')
    } catch (err) {
      console.error('Failed to delete novel:', err)
      toast.error((err as Error).message || '删除失败')
    }
  }

  const handleDeleteChapter = async (chapter: Chapter) => {
    if (!window.confirm(`确定要删除章节「${chapter.name}」吗？`)) return
    try {
      await api.deleteChapter(chapter.id)
      toast.success('章节已删除')
      setChapters((prev) => prev.filter((c) => c.id !== chapter.id))
    } catch (err) {
      console.error('Failed to delete chapter:', err)
      toast.error((err as Error).message || '删除失败')
    }
  }

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const contentLength = novel?.content?.length ?? 0

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="sticky top-0 z-10 glass border-b px-6 py-4">
          <Skeleton className="h-4 w-48 mb-4" />
          <div className="flex gap-5">
            <Skeleton className="w-20 h-28 rounded-lg" />
            <div className="flex-1 space-y-3">
              <Skeleton className="h-7 w-64" />
              <Skeleton className="h-4 w-96" />
              <div className="flex gap-4">
                <Skeleton className="h-4 w-20" />
                <Skeleton className="h-4 w-32" />
                <Skeleton className="h-4 w-24" />
              </div>
            </div>
          </div>
        </div>
        <div className="px-6 space-y-3">
          <Skeleton className="h-6 w-32" />
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-16 w-full rounded-lg" />
          ))}
        </div>
      </div>
    )
  }

  if (!novel) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-muted-foreground animate-fade-up">
        <BookOpen className="h-12 w-12 mb-4 opacity-50" />
        <p>小说不存在或加载失败</p>
        <Link to="/" className="mt-4 text-primary hover:underline">
          返回项目列表
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header bar */}
      <div className="sticky top-0 z-10 glass border-b px-6 py-4">
        {/* Breadcrumb */}
        <div className="animate-fade-in flex items-center gap-2 text-sm text-muted-foreground mb-4">
          <Link to="/" className="hover:text-primary transition-colors flex items-center gap-1">
            <ArrowLeft className="h-3.5 w-3.5" />
            项目列表
          </Link>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="text-foreground">{novel.name}</span>
        </div>

        <div className="animate-fade-up flex items-start justify-between gap-6">
          {/* Left side: cover + info */}
          <div className="flex gap-5 min-w-0">
            <div className="w-20 h-28 rounded-lg bg-gradient-to-br from-primary/20 via-primary/5 to-accent/10 border border-primary/10 flex-shrink-0 overflow-hidden flex items-center justify-center shadow-lg shadow-primary/5">
              {novel.cover ? (
                <img
                  src={novel.cover}
                  alt={novel.name}
                  className="w-full h-full object-cover"
                />
              ) : (
                <BookOpen className="h-8 w-8 text-muted-foreground/30" />
              )}
            </div>

            <div className="min-w-0 space-y-2">
              <h1 className="text-xl font-bold truncate">{novel.name}</h1>
              {novel.description && (
                <p className="text-sm text-muted-foreground/70 line-clamp-2">
                  {novel.description}
                </p>
              )}
              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                {novel.author && (
                  <span>
                    作者：<span className="text-foreground">{novel.author}</span>
                  </span>
                )}
                <span>
                  创建时间：<span className="text-foreground">{formatDate(novel.created_at)}</span>
                </span>
                {contentLength > 0 && (
                  <span>
                    内容字数：<span className="text-primary font-medium">{contentLength.toLocaleString()}</span>
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Right side buttons */}
          <div className="flex items-center gap-2 flex-shrink-0">
            <Button variant="ghost" size="sm" onClick={handleEditOpen} className="hover:bg-primary/10 hover:text-primary">
              <Edit3 className="h-4 w-4 mr-1.5" />
              编辑
            </Button>
            <Button
              variant="destructive"
              size="icon"
              className="h-8 w-8"
              onClick={handleDeleteNovel}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              onClick={handleSplit}
              disabled={splitting}
              className="shadow-lg shadow-primary/20"
            >
              {splitting ? (
                <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4 mr-1.5" />
              )}
              智能拆分章节
            </Button>
          </div>
        </div>
      </div>

      {/* Chapter list */}
      <div className="px-6 pb-6 animate-fade-up" style={{ animationDelay: '150ms' }}>
        <div className="flex items-center gap-2 mb-4">
          <FileText className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">章节列表</h2>
          <span className="text-sm text-muted-foreground">({chapterPagination?.total ?? chapters.length})</span>
        </div>

        {chapters.length === 0 ? (
          <div className="border-2 border-dashed border-muted-foreground/20 rounded-2xl py-16 flex flex-col items-center justify-center text-muted-foreground relative overflow-hidden">
            <div className="absolute inset-0 animate-shimmer" />
            <BookOpen className="h-12 w-12 mb-3 opacity-30 animate-float" />
            <p className="text-sm">暂无章节</p>
            <p className="text-xs mt-1 text-muted-foreground/60">请先粘贴小说内容，然后使用「智能拆分章节」</p>
          </div>
        ) : (
          <>
          <div className="space-y-2 stagger-children">
            {chapters.map((chapter) => (
              <div
                key={chapter.id}
                className="group bg-card/40 border border-border/50 rounded-lg px-4 py-3 flex items-center gap-4 hover:bg-card/80 hover:border-primary/20 transition-all duration-200"
              >
                {/* Chapter number circle */}
                <div className="w-8 h-8 rounded-full bg-primary/10 text-primary text-sm font-semibold flex items-center justify-center flex-shrink-0 border border-primary/20">
                  {chapter.number}
                </div>

                {/* Chapter name */}
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium truncate block group-hover:text-foreground transition-colors">
                    {chapter.name}
                  </span>
                </div>

                {/* Status badges */}
                <div className="flex items-center gap-2">
                  {chapter.workflow_status !== undefined && chapter.workflow_status >= 1 ? (
                    <Badge variant="success">实体就绪</Badge>
                  ) : (
                    <Badge variant="outline">待提取</Badge>
                  )}
                  {chapter.workflow_status !== undefined && chapter.workflow_status >= 2 ? (
                    <Badge variant="success">分镜就绪</Badge>
                  ) : (
                    <Badge variant="outline">无分镜</Badge>
                  )}
                </div>

                {/* Delete button */}
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 opacity-0 group-hover:opacity-100 transition-all text-muted-foreground hover:text-destructive"
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    handleDeleteChapter(chapter)
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>

                {/* Enter workflow link */}
                <Link
                  to={`/novel/${novelId}/chapter/${chapter.id}/step/1`}
                  className="flex items-center gap-1 text-sm text-primary hover:text-primary/80 transition-colors flex-shrink-0 group/link"
                >
                  进入工作流
                  <ChevronRight className="h-4 w-4 transition-transform group-hover/link:translate-x-0.5" />
                </Link>
              </div>
            ))}
          </div>

          {/* Chapter Pagination */}
          {chapterPagination && chapterPagination.pages > 1 && (
            <div className="flex items-center justify-center gap-4 pt-4">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setChapterPage((p) => Math.max(1, p - 1))}
                disabled={chapterPage <= 1}
              >
                上一页
              </Button>
              <span className="text-sm text-muted-foreground">
                第 {chapterPage} / {chapterPagination.pages} 页
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setChapterPage((p) => Math.min(chapterPagination!.pages, p + 1))}
                disabled={chapterPage >= chapterPagination.pages}
              >
                下一页
              </Button>
            </div>
          )}
          </>
        )}
      </div>

      {/* Edit dialog */}
      <Dialog open={editOpen} onOpenChange={setEditOpen}>
        <DialogContent className="glass max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="gradient-text text-xl">编辑小说</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">名称</label>
              <Input
                value={editForm.name}
                onChange={(e) =>
                  setEditForm((prev) => ({ ...prev, name: e.target.value }))
                }
                placeholder="小说名称"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">作者</label>
              <Input
                value={editForm.author}
                onChange={(e) =>
                  setEditForm((prev) => ({ ...prev, author: e.target.value }))
                }
                placeholder="作者名称"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">简介</label>
              <Textarea
                value={editForm.description}
                onChange={(e) =>
                  setEditForm((prev) => ({ ...prev, description: e.target.value }))
                }
                placeholder="小说简介"
                rows={3}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">内容</label>
              <Textarea
                value={editForm.content}
                onChange={(e) =>
                  setEditForm((prev) => ({ ...prev, content: e.target.value }))
                }
                placeholder="在此粘贴小说全文..."
                rows={16}
                className="font-mono text-sm"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditOpen(false)} disabled={saving}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={saving} className="shadow-lg shadow-primary/20">
              {saving && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
