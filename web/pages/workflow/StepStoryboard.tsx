import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Textarea } from "@/components/ui/textarea"
import { Skeleton } from "@/components/ui/skeleton"
import { Sparkles, Loader2, Edit3, Trash2, Save, X, GripVertical } from "lucide-react"
import { api } from "@/services/api"
import type { Scene, Asset, AiTask } from "@/types"
import { TaskStatusEnum } from "@/types"
import { toast } from "sonner"
import { sleep } from "@/lib/helpers"

interface StepStoryboardProps {
  chapterId: number
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

export const StepStoryboard = ({ chapterId }: StepStoryboardProps) => {
  const [scenes, setScenes] = useState<Scene[]>([])
  const [loading, setLoading] = useState(true)
  const [generating, setGenerating] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editPrompt, setEditPrompt] = useState("")

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

  useEffect(() => {
    loadScenes()
  }, [chapterId])

  const handleGenerate = async () => {
    try {
      setGenerating(true)
      const res = await api.generateScenes({ chapter_id: chapterId })
      const task = await pollTask(res.data.id)
      if (task.status === TaskStatusEnum.COMPLETED) {
        toast.success("分镜生成完成")
      } else {
        toast.error("分镜生成失败")
      }
      await loadScenes()
    } catch (err) {
      toast.error((err as Error).message || "分镜生成失败")
    } finally {
      setGenerating(false)
    }
  }

  const handleEdit = (scene: Scene) => {
    setEditingId(scene.id)
    setEditPrompt(scene.prompt ?? "")
  }

  const handleCancelEdit = () => {
    setEditingId(null)
    setEditPrompt("")
  }

  const handleSavePrompt = async (sceneId: number) => {
    try {
      await api.patchScene(sceneId, { prompt: editPrompt })
      toast.success("提示词已保存")
      setEditingId(null)
      setEditPrompt("")
      await loadScenes()
    } catch (err) {
      toast.error((err as Error).message || "保存提示词失败")
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
              className="flex gap-4 p-4 bg-card border rounded-lg hover:border-primary/50 transition-colors"
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

                {/* Prompt editing / display */}
                {editingId === scene.id ? (
                  <div className="space-y-2">
                    <Textarea
                      value={editPrompt}
                      onChange={(e) => setEditPrompt(e.target.value)}
                      rows={3}
                      className="font-mono text-sm"
                    />
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        onClick={() => handleSavePrompt(scene.id)}
                      >
                        <Save className="h-3 w-3 mr-1" />
                        保存
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={handleCancelEdit}
                      >
                        <X className="h-3 w-3 mr-1" />
                        取消
                      </Button>
                    </div>
                  </div>
                ) : (
                  <>
                    {scene.prompt ? (
                      <p className="text-sm font-mono bg-background/50 border rounded p-2 text-muted-foreground">
                        {scene.prompt}
                      </p>
                    ) : (
                      <p className="text-sm text-muted-foreground italic">
                        暂无提示词
                      </p>
                    )}
                  </>
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
              <div className="flex flex-col gap-2 shrink-0">
                <Button
                  size="icon"
                  variant="ghost"
                  onClick={() => handleEdit(scene)}
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
    </div>
  )
}
