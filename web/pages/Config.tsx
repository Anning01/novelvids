import { useEffect, useState } from 'react'
import { Settings, Plus, Edit3, Trash2, Power, Eye, EyeOff } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { api } from '@/services/api'
import type { AiModelConfig } from '@/types'

const TASK_TYPE_MAP: Record<number, string> = {
  1: '实体提取',
  2: '参考图生成',
  3: '分镜生成',
  4: '视频生成',
}

const defaultForm = {
  task_type: 1,
  name: '',
  base_url: '',
  api_key: '',
  model: '',
  concurrency: 1,
}

export const ConfigPage = () => {
  const [configs, setConfigs] = useState<AiModelConfig[]>([])
  const [loading, setLoading] = useState(true)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [editId, setEditId] = useState<number | null>(null)
  const [form, setForm] = useState({ ...defaultForm })
  const [visibleKeys, setVisibleKeys] = useState<Record<number, boolean>>({})

  const fetchConfigs = async () => {
    try {
      setLoading(true)
      const res = await api.getConfigs()
      setConfigs(res.data.items)
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchConfigs()
  }, [])

  const openCreate = () => {
    setEditId(null)
    setForm({ ...defaultForm })
    setDialogOpen(true)
  }

  const openEdit = (config: AiModelConfig) => {
    setEditId(config.id)
    setForm({
      task_type: config.task_type,
      name: config.name,
      base_url: config.base_url || '',
      api_key: config.api_key || '',
      model: config.model || '',
      concurrency: config.concurrency,
    })
    setDialogOpen(true)
  }

  const handleSave = async () => {
    if (!form.name.trim()) return
    try {
      setSaving(true)
      if (editId) {
        await api.patchConfig(editId, {
          task_type: form.task_type,
          name: form.name.trim(),
          base_url: form.base_url.trim() || undefined,
          api_key: form.api_key.trim() || undefined,
          model: form.model.trim() || undefined,
          concurrency: form.concurrency,
        })
        toast.success('配置已更新')
      } else {
        await api.createConfig({
          task_type: form.task_type,
          name: form.name.trim(),
          base_url: form.base_url.trim() || undefined,
          api_key: form.api_key.trim() || undefined,
          model: form.model.trim() || undefined,
          concurrency: form.concurrency,
        })
        toast.success('配置已创建')
      }
      setDialogOpen(false)
      setForm({ ...defaultForm })
      setEditId(null)
      await fetchConfigs()
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: number) => {
    if (!window.confirm('确定删除该配置？')) return
    try {
      await api.deleteConfig(id)
      toast.success('配置已删除')
      setConfigs((prev) => prev.filter((c) => c.id !== id))
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  const handleActivate = async (id: number) => {
    try {
      await api.activateConfig(id)
      toast.success('配置已启用')
      await fetchConfigs()
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  const toggleKeyVisibility = (id: number) => {
    setVisibleKeys((prev) => ({ ...prev, [id]: !prev[id] }))
  }

  const maskKey = (key?: string) => {
    if (!key) return '-'
    if (key.length <= 8) return '****'
    return key.slice(0, 4) + '****' + key.slice(-4)
  }

  return (
    <div className="p-8 max-w-7xl mx-auto space-y-8">
      {/* Header */}
      <div className="animate-fade-up flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight flex items-center gap-3">
            <div className="relative">
              <Settings className="h-8 w-8 text-primary" />
              <div className="absolute inset-0 blur-lg bg-primary/30 rounded-full" />
            </div>
            <span className="gradient-text">模型配置</span>
          </h1>
          <p className="text-muted-foreground mt-1.5 text-sm">管理各任务类型的AI模型配置</p>
        </div>
        <Button onClick={openCreate} className="shadow-lg shadow-primary/20">
          <Plus className="mr-2 h-4 w-4" />
          新增配置
        </Button>
      </div>

      {/* Decorative line */}
      <div className="decorative-line animate-fade-in" style={{ animationDelay: '150ms' }} />

      {/* Loading State */}
      {loading && (
        <div className="space-y-4 stagger-children">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-card/40 border rounded-lg p-5">
              <div className="flex items-center gap-4">
                <Skeleton className="h-3 w-3 rounded-full" />
                <div className="flex-1 space-y-2">
                  <Skeleton className="h-5 w-1/4" />
                  <Skeleton className="h-4 w-1/2" />
                </div>
                <Skeleton className="h-9 w-20" />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty State */}
      {!loading && configs.length === 0 && (
        <div className="animate-scale-in flex flex-col items-center justify-center rounded-2xl border-2 border-dashed border-muted-foreground/20 p-16 relative overflow-hidden">
          <div className="absolute inset-0 animate-shimmer" />
          <Settings className="h-16 w-16 text-muted-foreground/30 animate-float" />
          <h3 className="mt-6 text-lg font-semibold text-muted-foreground">暂无配置</h3>
          <p className="mt-2 text-sm text-muted-foreground/60">添加AI模型配置以开始使用</p>
          <Button variant="ghost" className="mt-6 border border-primary/20 hover:bg-primary/10 hover:text-primary transition-all" onClick={openCreate}>
            <Plus className="mr-2 h-4 w-4" />
            创建第一个配置
          </Button>
        </div>
      )}

      {/* Config List */}
      {!loading && configs.length > 0 && (
        <div className="space-y-3 stagger-children">
          {configs.map((config) => (
            <div
              key={config.id}
              className="group bg-card/40 border border-border/50 rounded-lg p-4 flex items-center gap-4 hover:bg-card/80 hover:border-primary/20 transition-all duration-200"
            >
              {/* Status Dot */}
              <div className="relative flex-shrink-0">
                <div
                  className={`h-3 w-3 rounded-full ${
                    config.is_active ? 'bg-green-500 shadow-lg shadow-green-500/50' : 'bg-muted-foreground/30'
                  }`}
                />
                {config.is_active && (
                  <div className="absolute inset-0 h-3 w-3 rounded-full bg-green-500 animate-ping opacity-40" />
                )}
              </div>

              {/* Info */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-bold text-base">{config.name}</span>
                  <Badge variant="default">
                    {TASK_TYPE_MAP[config.task_type] || `类型${config.task_type}`}
                  </Badge>
                  {config.is_active && (
                    <Badge variant="success">已启用</Badge>
                  )}
                </div>
                <div className="flex items-center gap-4 mt-1.5 text-sm text-muted-foreground flex-wrap">
                  <span>模型: <span className="text-foreground/80">{config.model || '-'}</span></span>
                  <span>URL: <span className="text-foreground/80">{config.base_url || '-'}</span></span>
                  <span className="flex items-center gap-1">
                    密钥:{' '}
                    <span className="font-mono text-xs text-foreground/80">
                      {visibleKeys[config.id]
                        ? config.api_key || '-'
                        : maskKey(config.api_key)}
                    </span>
                    <button
                      onClick={() => toggleKeyVisibility(config.id)}
                      className="inline-flex items-center justify-center text-muted-foreground hover:text-primary transition-colors"
                    >
                      {visibleKeys[config.id] ? (
                        <EyeOff className="h-3.5 w-3.5" />
                      ) : (
                        <Eye className="h-3.5 w-3.5" />
                      )}
                    </button>
                  </span>
                  <span>并发: <span className="text-primary font-medium">{config.concurrency}</span></span>
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity">
                {!config.is_active && (
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-8 w-8 text-green-500 hover:text-green-400 hover:bg-green-500/10 border-green-500/20"
                    onClick={() => handleActivate(config.id)}
                    title="启用"
                  >
                    <Power className="h-4 w-4" />
                  </Button>
                )}
                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8 hover:bg-primary/10 hover:text-primary hover:border-primary/20"
                  onClick={() => openEdit(config)}
                  title="编辑"
                >
                  <Edit3 className="h-4 w-4" />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  className="h-8 w-8 text-red-500 hover:text-red-400 hover:bg-red-500/10 border-red-500/20"
                  onClick={() => handleDelete(config.id)}
                  title="删除"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create / Edit Dialog */}
      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="glass">
          <DialogHeader>
            <DialogTitle className="gradient-text text-xl">{editId ? '编辑配置' : '新增配置'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>任务类型</Label>
              <Select
                value={String(form.task_type)}
                onValueChange={(v) =>
                  setForm((f) => ({ ...f, task_type: Number(v) }))
                }
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="1">实体提取</SelectItem>
                  <SelectItem value="2">参考图生成</SelectItem>
                  <SelectItem value="3">分镜生成</SelectItem>
                  <SelectItem value="4">视频生成</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>名称</Label>
              <Input
                placeholder="例如: gpt-4o, veo3"
                value={form.name}
                onChange={(e) =>
                  setForm((f) => ({ ...f, name: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label>基础URL</Label>
              <Input
                placeholder="https://api.example.com"
                value={form.base_url}
                onChange={(e) =>
                  setForm((f) => ({ ...f, base_url: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label>API密钥</Label>
              <Input
                type="password"
                placeholder="sk-..."
                value={form.api_key}
                onChange={(e) =>
                  setForm((f) => ({ ...f, api_key: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label>模型</Label>
              <Input
                placeholder="模型名称"
                value={form.model}
                onChange={(e) =>
                  setForm((f) => ({ ...f, model: e.target.value }))
                }
              />
            </div>
            <div className="space-y-2">
              <Label>并发数</Label>
              <Input
                type="number"
                min={1}
                value={form.concurrency}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    concurrency: parseInt(e.target.value, 10) || 1,
                  }))
                }
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              取消
            </Button>
            <Button onClick={handleSave} disabled={!form.name.trim() || saving} className="shadow-lg shadow-primary/20">
              {saving
                ? editId
                  ? '保存中...'
                  : '创建中...'
                : editId
                  ? '保存'
                  : '创建'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
