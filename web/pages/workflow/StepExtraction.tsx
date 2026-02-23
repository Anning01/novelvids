import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Sparkles, Loader2, User, MapPin, Box, Pencil, Trash2 } from "lucide-react"
import { api } from "@/services/api"
import type { Asset, AiTask } from "@/types"
import { AssetTypeEnum, TaskStatusEnum } from "@/types"
import { toast } from "sonner"
import { sleep } from "@/lib/helpers"

interface StepExtractionProps {
  chapterId: number
  novelId: number
}

async function pollTask(taskId: string): Promise<AiTask> {
  while (true) {
    await sleep(3000)
    const res = await api.getTask(taskId)
    const t = res.data
    if (
      t.status === TaskStatusEnum.COMPLETED ||
      t.status === TaskStatusEnum.FAILED ||
      t.status === TaskStatusEnum.CANCELLED
    ) {
      return t
    }
  }
}

export const StepExtraction = ({ chapterId, novelId }: StepExtractionProps) => {
  const [assets, setAssets] = useState<Asset[]>([])
  const [loading, setLoading] = useState(true)
  const [extracting, setExtracting] = useState(false)

  // Edit dialog state
  const [editingAsset, setEditingAsset] = useState<Asset | null>(null)
  const [editForm, setEditForm] = useState({
    canonical_name: "",
    aliases: "",
    description: "",
    base_traits: "",
  })
  const [saving, setSaving] = useState(false)

  const loadAssets = async () => {
    try {
      setLoading(true)
      const res = await api.getAssets(novelId)
      setAssets(res.data.items)
    } catch (err) {
      toast.error((err as Error).message || "加载资产失败")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadAssets()
  }, [novelId])

  const handleExtract = async () => {
    try {
      setExtracting(true)
      const res = await api.extractEntities(chapterId)
      const task = await pollTask(res.data.id)
      if (task.status === TaskStatusEnum.COMPLETED) {
        toast.success("实体提取完成")
      } else {
        toast.error(task.error_message || "实体提取失败")
      }
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "实体提取失败")
    } finally {
      setExtracting(false)
    }
  }

  const handleEditOpen = (asset: Asset) => {
    setEditingAsset(asset)
    setEditForm({
      canonical_name: asset.canonical_name || "",
      aliases: asset.aliases?.join(", ") || "",
      description: asset.description || "",
      base_traits: asset.base_traits || "",
    })
  }

  const handleEditSave = async () => {
    if (!editingAsset) return
    try {
      setSaving(true)
      await api.updateAsset(editingAsset.id, {
        canonical_name: editForm.canonical_name.trim(),
        aliases: editForm.aliases
          ? editForm.aliases.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
          : [],
        description: editForm.description.trim() || undefined,
        base_traits: editForm.base_traits.trim() || undefined,
      })
      toast.success("资产已更新")
      setEditingAsset(null)
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "更新失败")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (asset: Asset) => {
    if (!confirm(`确定要删除「${asset.canonical_name}」吗？`)) return
    try {
      await api.deleteAsset(asset.id)
      toast.success("已删除")
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "删除失败")
    }
  }

  const persons = assets.filter((a) => a.asset_type === AssetTypeEnum.PERSON)
  const scenes = assets.filter((a) => a.asset_type === AssetTypeEnum.SCENE)
  const items = assets.filter((a) => a.asset_type === AssetTypeEnum.ITEM)

  const sections = [
    {
      label: "角色",
      icon: User,
      color: "border-blue-500",
      textColor: "text-blue-500",
      data: persons,
    },
    {
      label: "场景",
      icon: MapPin,
      color: "border-green-500",
      textColor: "text-green-500",
      data: scenes,
    },
    {
      label: "道具",
      icon: Box,
      color: "border-amber-500",
      textColor: "text-amber-500",
      data: items,
    },
  ]

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">实体提取</h2>
          <p className="text-muted-foreground mt-1">
            分析章节内容，自动识别角色、场景和道具
          </p>
        </div>
        <Button onClick={handleExtract} disabled={extracting}>
          {extracting ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              分析中...
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4 mr-2" />
              自动提取
            </>
          )}
        </Button>
      </div>

      {/* Loading skeleton */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-28 rounded-lg" />
          ))}
        </div>
      ) : (
        /* Sections */
        <div className="space-y-8">
          {sections.map((section) => {
            const Icon = section.icon
            return (
              <div key={section.label}>
                {/* Section heading with colored left border */}
                <div
                  className={`flex items-center gap-2 mb-4 pl-3 border-l-4 ${section.color}`}
                >
                  <Icon className={`h-5 w-5 ${section.textColor}`} />
                  <h3 className="text-lg font-semibold">{section.label}</h3>
                  <Badge variant="secondary" className="ml-1">
                    {section.data.length}
                  </Badge>
                </div>

                {section.data.length === 0 ? (
                  <p className="text-sm text-muted-foreground pl-3">暂无数据</p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {section.data.map((asset) => (
                      <Card key={asset.id} className="group relative">
                        <CardContent className="p-4">
                          <div className="flex items-start gap-3">
                            {/* Thumbnail */}
                            {asset.main_image ? (
                              <img
                                src={asset.main_image}
                                alt={asset.canonical_name}
                                className="w-12 h-12 rounded object-cover flex-shrink-0"
                              />
                            ) : (
                              <div className="w-12 h-12 rounded bg-secondary flex items-center justify-center flex-shrink-0">
                                <span className="text-xs text-muted-foreground">
                                  {asset.canonical_name.slice(0, 1)}
                                </span>
                              </div>
                            )}

                            <div className="flex-1 min-w-0">
                              <p className="font-bold text-sm truncate">
                                {asset.canonical_name}
                              </p>
                              {asset.aliases && asset.aliases.length > 0 && (
                                <p className="text-xs text-muted-foreground mt-0.5">
                                  别名: {asset.aliases.join(", ")}
                                </p>
                              )}
                              {asset.description && (
                                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                  {asset.description}
                                </p>
                              )}
                            </div>

                            {/* Action buttons - show on hover */}
                            <div className="flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity flex-shrink-0">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-primary"
                                onClick={() => handleEditOpen(asset)}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-muted-foreground hover:text-destructive"
                                onClick={() => handleDelete(asset)}
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </Button>
                            </div>
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Edit Dialog */}
      <Dialog open={!!editingAsset} onOpenChange={(open) => !open && setEditingAsset(null)}>
        <DialogContent className="glass">
          <DialogHeader>
            <DialogTitle className="gradient-text text-xl">编辑资产</DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <label className="text-sm font-medium">名称</label>
              <Input
                value={editForm.canonical_name}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, canonical_name: e.target.value }))
                }
                placeholder="资产名称"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">别名</label>
              <Input
                value={editForm.aliases}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, aliases: e.target.value }))
                }
                placeholder="多个别名用逗号分隔"
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">描述</label>
              <Textarea
                value={editForm.description}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, description: e.target.value }))
                }
                placeholder="详细描述"
                rows={3}
              />
            </div>

            <div className="space-y-2">
              <label className="text-sm font-medium">固有特征 (用于 Prompt)</label>
              <Textarea
                value={editForm.base_traits}
                onChange={(e) =>
                  setEditForm((f) => ({ ...f, base_traits: e.target.value }))
                }
                placeholder="英文特征描述，用于生成参考图"
                rows={6}
                className="font-mono text-sm"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditingAsset(null)} disabled={saving}>
              取消
            </Button>
            <Button
              onClick={handleEditSave}
              disabled={!editForm.canonical_name.trim() || saving}
              className="shadow-lg shadow-primary/20"
            >
              {saving && <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />}
              保存
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
