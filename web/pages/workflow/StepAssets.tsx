import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Image as ImageIcon, Loader2, RefreshCw } from "lucide-react"
import { api } from "@/services/api"
import type { Asset, AiTask } from "@/types"
import { AssetTypeEnum, TaskStatusEnum } from "@/types"
import { toast } from "sonner"
import { sleep } from "@/lib/helpers"

interface StepAssetsProps {
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
    )
      return t
  }
}

function assetTypeLabel(type: AssetTypeEnum): string {
  switch (type) {
    case AssetTypeEnum.PERSON:
      return "角色"
    case AssetTypeEnum.SCENE:
      return "场景"
    case AssetTypeEnum.ITEM:
      return "道具"
  }
}

export const StepAssets = ({ chapterId: _chapterId, novelId }: StepAssetsProps) => {
  const [assets, setAssets] = useState<Asset[]>([])
  const [loading, setLoading] = useState(true)
  const [processingId, setProcessingId] = useState<number | null>(null)

  const loadAssets = async () => {
    try {
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

  const handleGenerate = async (assetId: number) => {
    setProcessingId(assetId)
    try {
      const res = await api.generateAssetImage(assetId)
      const task = await pollTask(res.data.id)
      if (task.status === TaskStatusEnum.COMPLETED) {
        toast.success("参考图生成完成")
      } else {
        toast.error("参考图生成失败")
      }
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "参考图生成失败")
    } finally {
      setProcessingId(null)
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-2xl font-bold">视觉资产</h2>
        <p className="text-muted-foreground mt-1">为提取的实体生成视觉参考图</p>
      </div>

      {/* Loading state */}
      {loading ? (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {Array.from({ length: 8 }).map((_, i) => (
            <Card key={i} className="overflow-hidden">
              <Skeleton className="aspect-square w-full" />
              <div className="p-3 space-y-2">
                <Skeleton className="h-4 w-2/3" />
                <Skeleton className="h-4 w-1/3" />
              </div>
            </Card>
          ))}
        </div>
      ) : (
        /* Asset grid */
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {assets.map((asset) => {
            const isProcessing = processingId === asset.id
            const hasImage = !!asset.main_image

            return (
              <Card key={asset.id} className="overflow-hidden group">
                {/* Image area */}
                <div className="relative aspect-square bg-secondary/30">
                  {hasImage ? (
                    <img
                      src={asset.main_image}
                      alt={asset.canonical_name}
                      className="w-full h-full object-cover"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center">
                      <ImageIcon className="h-12 w-12 text-muted-foreground/40" />
                    </div>
                  )}

                  {/* Hover overlay */}
                  <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={isProcessing}
                      onClick={() => handleGenerate(asset.id)}
                    >
                      {isProcessing ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" />
                          生成中...
                        </>
                      ) : hasImage ? (
                        <>
                          <RefreshCw className="h-4 w-4" />
                          重新生成
                        </>
                      ) : (
                        "生成参考图"
                      )}
                    </Button>
                  </div>
                </div>

                {/* Info area */}
                <div className="p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-sm truncate">{asset.canonical_name}</span>
                    {hasImage && (
                      <span className="h-2 w-2 rounded-full bg-green-500 shrink-0" />
                    )}
                  </div>
                  <Badge variant="secondary">{assetTypeLabel(asset.asset_type)}</Badge>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
