import { useEffect, useState, useMemo } from "react"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog"
import { Sparkles, Loader2, Edit3, Trash2, GripVertical } from "lucide-react"
import { api } from "@/services/api"
import type { Scene, Asset, AiTask } from "@/types"
import { TaskStatusEnum } from "@/types"
import { toast } from "sonner"
import { sleep } from "@/lib/helpers"

interface StepStoryboardProps {
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

/** Parse text containing @EntityName references and render them as blue spans with hover preview */
function EntityText({
  text,
  assetMap,
}: {
  text: string
  assetMap: Map<string, Asset>
}) {
  const parts = useMemo(() => {
    const result: { type: "text" | "entity"; value: string }[] = []
    // Match @{Multi Word Name} (preferred) or @SingleWord (legacy)
    const regex = /@\{([^}]+)\}|@([\w\u4e00-\u9fff·]+)/g
    let lastIndex = 0
    let match: RegExpExecArray | null
    while ((match = regex.exec(text)) !== null) {
      if (match.index > lastIndex) {
        result.push({ type: "text", value: text.slice(lastIndex, match.index) })
      }
      // match[1] = braced name, match[2] = bare word name
      result.push({ type: "entity", value: match[1] || match[2] })
      lastIndex = regex.lastIndex
    }
    if (lastIndex < text.length) {
      result.push({ type: "text", value: text.slice(lastIndex) })
    }
    return result
  }, [text])

  return (
    <>
      {parts.map((part, i) => {
        if (part.type === "text") return <span key={i}>{part.value}</span>

        const asset = assetMap.get(part.value)

        // Unrecognized entity — render as plain text (not blue)
        if (!asset) return <span key={i}>@{part.value}</span>

        return (
          <span key={i} className="relative inline-block group/entity">
            <span className="text-blue-400 font-medium cursor-default border-b border-blue-400/30 border-dashed">
              @{part.value}
            </span>
            <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 hidden group-hover/entity:flex flex-col items-center z-50 pointer-events-none">
              <span className="bg-popover border rounded-xl shadow-2xl p-2.5 flex gap-3 items-start min-w-[240px]">
                {asset.main_image ? (
                  <img
                    src={asset.main_image}
                    alt={asset.canonical_name}
                    className="w-20 h-20 rounded-lg object-cover flex-shrink-0"
                  />
                ) : (
                  <span className="w-20 h-20 rounded-lg bg-secondary flex items-center justify-center text-lg text-muted-foreground flex-shrink-0">
                    {asset.canonical_name.slice(0, 1)}
                  </span>
                )}
                <span className="flex flex-col gap-1 min-w-0">
                  <span className="text-sm font-bold text-foreground truncate">
                    {asset.canonical_name}
                  </span>
                  {asset.aliases && asset.aliases.length > 0 && (
                    <span className="text-xs text-muted-foreground truncate">
                      {asset.aliases.join("、")}
                    </span>
                  )}
                  {asset.description && (
                    <span className="text-xs text-muted-foreground line-clamp-2 leading-relaxed">
                      {asset.description}
                    </span>
                  )}
                </span>
              </span>
              <span className="w-2.5 h-2.5 bg-popover border-b border-r rotate-45 -mt-2" />
            </span>
          </span>
        )
      })}
    </>
  )
}

export const StepStoryboard = ({ chapterId, novelId }: StepStoryboardProps) => {
  const [scenes, setScenes] = useState<Scene[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)

  // Edit dialog state
  const [editingScene, setEditingScene] = useState<Scene | null>(null)
  const [editForm, setEditForm] = useState({
    description: "",
    duration: "",
    prompt: "",
  })
  const [saving, setSaving] = useState(false)

  // Build name->asset lookup map
  const assetMap = useMemo(() => {
    const map = new Map<string, Asset>()
    for (const a of assets) {
      map.set(a.canonical_name, a)
      // Also register aliases
      if (a.aliases) {
        for (const alias of a.aliases) {
          map.set(alias, a)
        }
      }
    }
    return map
  }, [assets])

  const loadScenes = async () => {
    try {
      setLoading(true)
      const res = await api.getScenes(chapterId)
      setScenes(res.data.items)
    } catch (err) {
      toast.error((err as Error).message || "加载分镜失败")
    } finally {
      setLoading(false)
    }
  }

  const loadAssets = async () => {
    try {
      const res = await api.getAssets(novelId)
      setAssets(res.data.items)
    } catch {
      // Silent fail — assets are supplementary
    }
  }

  useEffect(() => {
    loadScenes()
    loadAssets()
  }, [chapterId, novelId])

  const handleGenerate = async () => {
    try {
      setGenerating(true)
      const res = await api.generateScenes({ chapter_id: chapterId })
      const task = await pollTask(res.data.id)
      if (task.status === TaskStatusEnum.COMPLETED) {
        toast.success("分镜生成完成")
      } else {
        toast.error(task.error_message || "分镜生成失败")
      }
      await loadScenes()
    } catch (err) {
      toast.error((err as Error).message || "分镜生成失败")
    } finally {
      setGenerating(false)
    }
  }

  const handleEditOpen = (scene: Scene) => {
    setEditingScene(scene)
    setEditForm({
      description: scene.description || "",
      duration: scene.duration != null ? String(scene.duration) : "",
      prompt: scene.prompt || "",
    })
  }

  const handleEditSave = async () => {
    if (!editingScene) return
    try {
      setSaving(true)
      const patch: Partial<Scene> = {}
      if (editForm.description.trim() !== (editingScene.description || ""))
        patch.description = editForm.description.trim() || undefined
      if (editForm.prompt.trim() !== (editingScene.prompt || ""))
        patch.prompt = editForm.prompt.trim() || undefined
      const dur = parseFloat(editForm.duration)
      if (!isNaN(dur) && dur !== editingScene.duration) patch.duration = dur

      await api.patchScene(editingScene.id, patch)
      toast.success("分镜已保存")
      setEditingScene(null)
      await loadScenes()
    } catch (err) {
      toast.error((err as Error).message || "保存失败")
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (sceneId: number) => {
    if (!window.confirm("确定删除该分镜？")) return
    try {
      await api.deleteScene(sceneId)
      toast.success("分镜已删除")
      setScenes((prev) => prev.filter((s) => s.id !== sceneId))
    } catch (err) {
      toast.error((err as Error).message || "删除分镜失败")
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold">分镜管理</h2>
          <p className="text-muted-foreground mt-1">
            将章节拆解为镜头和场景
          </p>
        </div>
        <Button onClick={handleGenerate} disabled={generating}>
          {generating ? (
            <>
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              生成中...
            </>
          ) : (
            <>
              <Sparkles className="h-4 w-4 mr-2" />
              生成分镜
            </>
          )}
        </Button>
      </div>

      {/* Loading skeleton */}
      {loading ? (
        <div className="space-y-3">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-24 rounded-lg" />
          ))}
        </div>
      ) : scenes.length === 0 ? (
        <p className="text-muted-foreground text-center py-12">暂无分镜数据</p>
      ) : (
        /* Scene list */
        <div className="space-y-3">
          {scenes.map((scene) => (
            <div
              key={scene.id}
              className="flex gap-4 p-4 bg-card border rounded-lg hover:border-primary/50 transition-colors group"
            >
              {/* Left: sequence number + duration */}
              <div className="flex flex-col items-center justify-center gap-1 shrink-0 w-16">
                <GripVertical className="h-4 w-4 text-muted-foreground/40" />
                <span className="text-2xl font-bold text-muted-foreground">
                  #{scene.sequence}
                </span>
                {scene.duration != null && (
                  <span className="text-xs text-muted-foreground">
                    {scene.duration}秒
                  </span>
                )}
              </div>

              {/* Middle: description, prompt, asset tags */}
              <div className="flex-1 space-y-2 min-w-0">
                {/* Description */}
                <p className="text-white font-medium">
                  {scene.description || "暂无描述"}
                </p>

                {/* Prompt display with @entity highlighting */}
                {scene.prompt ? (
                  <p className="text-sm font-mono bg-background/50 border rounded p-2 text-muted-foreground whitespace-pre-wrap leading-relaxed">
                    <EntityText text={scene.prompt} assetMap={assetMap} />
                  </p>
                ) : (
                  <p className="text-sm text-muted-foreground italic">
                    暂无提示词
                  </p>
                )}

                {/* Asset tags */}
                {scene.assets && scene.assets.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {scene.assets.map((asset) => (
                      <Badge
                        key={asset.id}
                        variant="outline"
                        className="bg-primary/10 text-primary border-primary/20"
                      >
                        @{asset.canonical_name}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>

              {/* Right: action buttons */}
              <div className="flex flex-col gap-2 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => handleEditOpen(scene)}
                >
                  <Edit3 className="h-4 w-4" />
                </Button>
                <Button
                  size="icon"
                  variant="ghost"
                  className="text-red-500 hover:text-red-400"
                  onClick={() => handleDelete(scene.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Edit Dialog */}
      <Dialog open={!!editingScene} onOpenChange={(open) => !open && setEditingScene(null)}>
        <DialogContent className="glass max-w-2xl">
          <DialogHeader>
            <DialogTitle className="gradient-text text-xl">
              编辑分镜 #{editingScene?.sequence}
            </DialogTitle>
          </DialogHeader>

          <div className="space-y-4 py-2">
            <div className="flex gap-4">
              <div className="space-y-2 flex-1">
                <label className="text-sm font-medium">描述</label>
                <Input
                  value={editForm.description}
                  onChange={(e) => setEditForm((f) => ({ ...f, description: e.target.value }))}
                  placeholder="镜头描述"
                />
              </div>
              <div className="space-y-2 w-28">
                <label className="text-sm font-medium">时长 (秒)</label>
                <Input
                  type="number"
                  step="0.5"
                  value={editForm.duration}
                  onChange={(e) => setEditForm((f) => ({ ...f, duration: e.target.value }))}
                  placeholder="4"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">提示词</label>
              <Textarea
                value={editForm.prompt}
                onChange={(e) => setEditForm((f) => ({ ...f, prompt: e.target.value }))}
                placeholder="Sora / 视频生成提示词"
                rows={8}
                className="font-mono text-sm"
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setEditingScene(null)} disabled={saving}>
              取消
            </Button>
            <Button
              onClick={handleEditSave}
              disabled={saving}
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
