import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { BookOpen, Plus, Trash2, Sparkles, ImagePlus, X } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { Badge } from '@/components/ui/badge'
import { api } from '@/services/api'
import type { Novel, Pagination as PaginationType } from '@/types'
import { Pagination } from '@/components/Pagination'

export const Dashboard = () => {
  const [novels, setNovels] = useState<Novel[]>([])
  const [loading, setLoading] = useState(true)
  const [pagination, setPagination] = useState<PaginationType | null>(null)
  const [page, setPage] = useState(1)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState({ name: '', author: '', description: '' })
  const [coverFile, setCoverFile] = useState<File | null>(null)
  const [coverPreview, setCoverPreview] = useState<string | null>(null)

  const handleCoverChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setCoverFile(file)
    setCoverPreview(URL.createObjectURL(file))
  }

  const clearCover = () => {
    setCoverFile(null)
    if (coverPreview) URL.revokeObjectURL(coverPreview)
    setCoverPreview(null)
  }

  const fetchNovels = async (p: number = page) => {
    try {
      setLoading(true)
      const res = await api.getNovels(p)
      setNovels(res.data.items)
      setPagination(res.data.pagination)
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchNovels(page)
  }, [page])

  const handleCreate = async () => {
    if (!form.name.trim()) return
    try {
      setCreating(true)
      let cover: string | undefined
      if (coverFile) {
        const uploadRes = await api.uploadFiles([coverFile])
        const uploaded = uploadRes.data.files[0]
        cover = `/media/${uploaded.filename}`
      }
      await api.createNovel({
        name: form.name.trim(),
        author: form.author.trim() || undefined,
        description: form.description.trim() || undefined,
        cover,
      })
      toast.success('项目创建成功')
      setDialogOpen(false)
      setForm({ name: '', author: '', description: '' })
      clearCover()
      await fetchNovels(page)
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setCreating(false)
    }
  }

  const handleDelete = async (e: React.MouseEvent, id: number) => {
    e.preventDefault()
    e.stopPropagation()
    if (!window.confirm('确定删除该项目及其所有数据？')) return
    try {
      await api.deleteNovel(id)
      toast.success('项目已删除')
      setNovels((prev) => prev.filter((n) => n.id !== id))
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="animate-fade-up flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <div className="relative">
              <Sparkles className="h-8 w-8 text-primary" />
              <div className="absolute inset-0 blur-lg bg-primary/30 rounded-full" />
            </div>
            <span className="gradient-text">我的项目</span>
          </h1>
          <p className="text-muted-foreground mt-1.5 text-sm">管理你的小说与剧本</p>
        </div>
        <Button onClick={() => setDialogOpen(true)} className="shadow-lg shadow-primary/20">
          <Plus className="mr-2 h-4 w-4" />
          新建项目
        </Button>
      </div>

      {/* Decorative line */}
      <div className="decorative-line animate-fade-in" style={{ animationDelay: '150ms' }} />

      {/* Loading State */}
      {loading && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 stagger-children">
          {Array.from({ length: 6 }).map((_, i) => (
            <Card key={i} className="overflow-hidden">
              <Skeleton className="aspect-video w-full" />
              <CardContent className="p-4 space-y-3">
                <Skeleton className="h-5 w-3/4" />
                <Skeleton className="h-4 w-1/2" />
                <Skeleton className="h-4 w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loading && novels.length === 0 && (
        <div className="animate-scale-in flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-muted-foreground/20 p-16 relative overflow-hidden">
          {/* Subtle shimmer bg */}
          <div className="absolute inset-0 animate-shimmer" />
          <div className="relative">
            <BookOpen className="h-16 w-16 text-muted-foreground/30 animate-float" />
          </div>
          <h3 className="mt-6 text-lg font-semibold text-muted-foreground">暂无项目</h3>
          <p className="mt-2 text-sm text-muted-foreground/60">开始创建你的第一个小说短剧项目</p>
          <Button variant="ghost" className="mt-6 border border-primary/20 hover:bg-primary/10 hover:text-primary transition-all" onClick={() => setDialogOpen(true)}>
            <Plus className="mr-2 h-4 w-4" />
            创建第一个项目
          </Button>
        </div>
      )}

      {/* Project Grid */}
      {!loading && novels.length > 0 && (
        <>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 stagger-children">
          {novels.map((novel) => (
            <Link key={novel.id} to={`/novel/${novel.id}`} className="group">
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
                  {/* Delete Button */}
                  <Button
                    variant="destructive"
                    size="icon"
                    className="absolute top-2 right-2 h-8 w-8 opacity-0 transition-all duration-200 group-hover:opacity-100 scale-90 group-hover:scale-100"
                    onClick={(e) => handleDelete(e, novel.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
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
        {pagination && pagination.pages > 1 && (
          <Pagination current={page} total={pagination.pages} onChange={setPage} />
        )}
        </>
      )}

      {/* Create Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="glass">
          <DialogHeader>
            <DialogTitle className="gradient-text text-xl">新建项目</DialogTitle>
            <DialogDescription>创建一个新的小说短剧项目</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            {/* Cover Upload */}
            <div className="space-y-2">
              <label className="text-sm font-medium">封面</label>
              {coverPreview ? (
                <div className="relative w-full aspect-video rounded-lg overflow-hidden border">
                  <img src={coverPreview} alt="封面预览" className="h-full w-full object-cover" />
                  <Button
                    variant="destructive"
                    size="icon"
                    className="absolute top-2 right-2 h-7 w-7"
                    onClick={clearCover}
                  >
                    <X className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ) : (
                <label className="flex flex-col items-center justify-center w-full h-32 border-2 border-dashed rounded-lg cursor-pointer hover:border-primary/50 hover:bg-primary/5 transition-colors">
                  <ImagePlus className="h-8 w-8 text-muted-foreground/40" />
                  <span className="mt-2 text-sm text-muted-foreground/60">点击上传封面图片</span>
                  <input type="file" accept="image/*" className="hidden" onChange={handleCoverChange} />
                </label>
              )}
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">
                小说名称 <span className="text-destructive">*</span>
              </label>
              <Input
                placeholder="输入小说名称"
                value={form.name}
                onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">作者</label>
              <Input
                placeholder="输入作者名称"
                value={form.author}
                onChange={(e) => setForm((f) => ({ ...f, author: e.target.value }))}
              />
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">简介</label>
              <Textarea
                placeholder="输入小说简介"
                rows={3}
                value={form.description}
                onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={handleCreate} disabled={!form.name.trim() || creating} className="shadow-lg shadow-primary/20">
              {creating ? '创建中...' : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
