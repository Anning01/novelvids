import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import { Sparkles, Loader2, User, MapPin, Box } from "lucide-react"
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
        toast.error("实体提取失败")
      }
      await loadAssets()
    } catch (err) {
      toast.error((err as Error).message || "实体提取失败")
    } finally {
      setExtracting(false)
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
                      <Card key={asset.id}>
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
                                  小名: {asset.aliases.join(", ")}
                                </p>
                              )}
                              {asset.description && (
                                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                                  {asset.description}
                                </p>
                              )}
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
    </div>
  )
}
