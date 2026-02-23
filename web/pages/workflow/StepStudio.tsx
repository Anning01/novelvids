import { useEffect, useState } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Skeleton } from "@/components/ui/skeleton"
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from "@/components/ui/select"
import { Film, Video, Loader2, RefreshCw, AlertCircle } from "lucide-react"
import { api } from "@/services/api"
import type { Scene, Video as VideoType } from "@/types"
import { TaskStatusEnum, VideoModelTypeEnum } from "@/types"
import { toast } from "sonner"
import { sleep, statusLabel, statusColor, modelLabel } from "@/lib/helpers"

interface StepStudioProps {
  chapterId: number
}

async function pollVideo(videoId: number): Promise<VideoType> {
  while (true) {
    await sleep(4000)
    const res = await api.queryVideo(videoId)
    const v = res.data
    if (
      v.status === TaskStatusEnum.COMPLETED ||
      v.status === TaskStatusEnum.FAILED
    ) {
      return v
    }
  }
}

export const StepStudio = ({ chapterId }: StepStudioProps) => {
  const [scenes, setScenes] = useState<Scene[]>([])
  const [selectedScene, setSelectedScene] = useState<Scene | null>(null)
  const [videos, setVideos] = useState<VideoType[]>([])
  const [generating, setGenerating] = useState(false)
  const [loading, setLoading] = useState(true)
  const [selectedModel, setSelectedModel] = useState<number>(
    VideoModelTypeEnum.SEEDANCE
  )

  const loadScenes = async () => {
    try {
      setLoading(true)
      const res = await api.getScenes(chapterId)
      const items = res.data.items
      setScenes(items)
      if (items.length > 0 && !selectedScene) {
        setSelectedScene(items[0])
      }
    } catch (err) {
      toast.error((err as Error).message || "加载场景列表失败")
    } finally {
      setLoading(false)
    }
  }

  const loadVideos = async (sceneId: number) => {
    try {
      const res = await api.getVideos(1, 100, "-id", sceneId)
      setVideos(res.data.items)
    } catch (err) {
      toast.error((err as Error).message || "加载视频列表失败")
    }
  }

  useEffect(() => {
    loadScenes()
  }, [chapterId])

  useEffect(() => {
    if (selectedScene) {
      loadVideos(selectedScene.id)
    } else {
      setVideos([])
    }
  }, [selectedScene?.id])

  const latestVideo = videos.length > 0 ? videos[0] : null

  const handleGenerate = async () => {
    if (!selectedScene) return
    try {
      setGenerating(true)
      const res = await api.generateVideo({
        scene_id: selectedScene.id,
        model_type: selectedModel,
      })
      const newVideo = res.data
      setVideos((prev) => [newVideo, ...prev])
      const finished = await pollVideo(newVideo.id)
      setVideos((prev) =>
        prev.map((v) => (v.id === finished.id ? finished : v))
      )
      if (finished.status === TaskStatusEnum.COMPLETED) {
        toast.success("视频生成完成")
      } else {
        toast.error(finished.metadata?.error || "视频生成失败")
      }
    } catch (err) {
      toast.error((err as Error).message || "视频生成失败")
    } finally {
      setGenerating(false)
    }
  }

  const handleRefresh = async (videoId: number) => {
    try {
      const res = await api.queryVideo(videoId)
      setVideos((prev) =>
        prev.map((v) => (v.id === videoId ? res.data : v))
      )
    } catch (err) {
      toast.error((err as Error).message || "刷新视频状态失败")
    }
  }

  const handleSelectScene = (scene: Scene) => {
    setSelectedScene(scene)
  }

  const isProcessing = (v: VideoType) =>
    v.status === TaskStatusEnum.PROCESSING ||
    v.status === TaskStatusEnum.PENDING ||
    v.status === TaskStatusEnum.QUEUED

  return (
    <div className="flex h-full">
      {/* Left panel - scene list */}
      <div className="w-72 bg-card border-r flex flex-col">
        <div className="p-4 border-b">
          <h3 className="font-semibold">场景列表</h3>
        </div>
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="p-4 space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <Skeleton key={i} className="h-16 rounded-lg" />
              ))}
            </div>
          ) : (
            <div className="p-2 space-y-1">
              {scenes.map((scene) => {
                const isActive = selectedScene?.id === scene.id
                return (
                  <div
                    key={scene.id}
                    className={`p-3 rounded-lg cursor-pointer transition-colors border ${
                      isActive
                        ? "bg-primary/10 border-primary"
                        : "border-transparent hover:bg-secondary/50"
                    }`}
                    onClick={() => handleSelectScene(scene)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold text-muted-foreground">
                        #{scene.sequence}
                      </span>
                      {scene.duration != null && (
                        <span className="text-xs text-muted-foreground">
                          {scene.duration}秒
                        </span>
                      )}
                    </div>
                    <p className="text-sm mt-1 line-clamp-2 text-muted-foreground">
                      {scene.description || "暂无描述"}
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      {/* Right area */}
      <div className="flex-1 p-6 flex flex-col gap-6 overflow-auto">
        {!selectedScene ? (
          <div className="flex-1 flex items-center justify-center text-muted-foreground">
            请从左侧选择一个场景
          </div>
        ) : (
          <>
            {/* Preview area */}
            <div className="flex-1 bg-black/40 rounded-lg border flex items-center justify-center min-h-[300px] relative overflow-hidden">
              {latestVideo &&
              latestVideo.status === TaskStatusEnum.COMPLETED &&
              latestVideo.url ? (
                <div className="w-full h-full relative">
                  <video
                    src={latestVideo.url}
                    controls
                    className="w-full h-full object-contain"
                  />
                  <div className="absolute top-3 right-3">
                    <Badge variant="secondary">
                      {modelLabel(latestVideo.model_type)}
                    </Badge>
                  </div>
                </div>
              ) : latestVideo && isProcessing(latestVideo) ? (
                <div className="flex flex-col items-center gap-3 text-muted-foreground">
                  <Loader2 className="h-10 w-10 animate-spin" />
                  <p className="text-sm font-medium">视频生成中...</p>
                  <Badge variant="secondary">
                    {modelLabel(latestVideo.model_type)}
                  </Badge>
                  <Badge variant="outline">
                    {statusLabel(latestVideo.status)}
                  </Badge>
                </div>
              ) : latestVideo && latestVideo.status === TaskStatusEnum.FAILED ? (
                <div className="flex flex-col items-center gap-3 text-muted-foreground max-w-md text-center">
                  <AlertCircle className="h-10 w-10 text-red-500" />
                  <p className="text-sm font-medium text-red-400">视频生成失败</p>
                  {latestVideo.metadata?.error && (
                    <p className="text-xs text-red-400/80 bg-red-500/10 rounded-lg px-4 py-2">
                      {latestVideo.metadata.error}
                    </p>
                  )}
                  <Badge variant="secondary">
                    {modelLabel(latestVideo.model_type)}
                  </Badge>
                </div>
              ) : (
                <div className="flex flex-col items-center gap-3 text-muted-foreground">
                  <Film className="h-12 w-12" />
                  <p className="text-sm">暂无生成视频</p>
                </div>
              )}
            </div>

            {/* Control panel */}
            <div className="bg-card border rounded-xl p-6 space-y-4">
              {/* Prompt display */}
              <div>
                <label className="text-sm font-medium text-muted-foreground mb-2 block">
                  提示词
                </label>
                <div className="bg-background font-mono text-sm p-3 rounded-lg border min-h-[60px]">
                  {selectedScene.prompt || "暂无提示词"}
                </div>
              </div>

              {/* Controls row */}
              <div className="flex items-center gap-3">
                {/* Model selector */}
                <Select
                  value={String(selectedModel)}
                  onValueChange={(v) => setSelectedModel(Number(v))}
                >
                  <SelectTrigger className="w-[200px]">
                    <SelectValue placeholder="选择模型" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="4">Veo 3 (高质量)</SelectItem>
                    <SelectItem value="2">Sora 2</SelectItem>
                    <SelectItem value="1">Vidu Q2</SelectItem>
                    <SelectItem value="3">Seedance</SelectItem>
                  </SelectContent>
                </Select>

                {/* Generate button */}
                <Button
                  onClick={handleGenerate}
                  disabled={generating}
                >
                  {generating ? (
                    <>
                      <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      生成中...
                    </>
                  ) : (
                    <>
                      <Video className="h-4 w-4 mr-2" />
                      {videos.length > 0 ? "重新生成视频" : "生成视频"}
                    </>
                  )}
                </Button>
              </div>

              {/* Video history */}
              {videos.length > 1 && (
                <div>
                  <label className="text-sm font-medium text-muted-foreground mb-2 block">
                    历史版本
                  </label>
                  <div className="flex gap-3 overflow-x-auto pb-2">
                    {videos.map((video) => (
                      <Card
                        key={video.id}
                        className="shrink-0 p-3 w-44 space-y-2"
                      >
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono text-muted-foreground">
                            #{video.id}
                          </span>
                          <Button
                            size="icon"
                            variant="ghost"
                            className="h-6 w-6"
                            onClick={() => handleRefresh(video.id)}
                          >
                            <RefreshCw className="h-3 w-3" />
                          </Button>
                        </div>
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary" className="text-xs">
                            {modelLabel(video.model_type)}
                          </Badge>
                          <Badge variant="outline" className="text-xs">
                            {statusLabel(video.status)}
                          </Badge>
                        </div>
                        {video.status === TaskStatusEnum.FAILED && video.metadata?.error && (
                          <p className="text-xs text-red-400 line-clamp-2">
                            {video.metadata.error}
                          </p>
                        )}
                      </Card>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
