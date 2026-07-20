import { lazy, Suspense } from "react"
import { Button } from "@/components/ui/button"
import { User, Image as ImageIcon, Workflow, ChevronLeft, Check, Loader2 } from "lucide-react"
import { Link, useParams } from "react-router-dom"
import { StepExtraction } from "./StepExtraction"
import { StepAssets } from "./StepAssets"
import { cn } from "@/lib/utils"

const CreativeCanvas = lazy(() => import("./CreativeCanvas").then((module) => ({ default: module.CreativeCanvas })))

const steps = [
  { id: 1, label: "内容理解", description: "提取角色与场景", icon: User },
  { id: 2, label: "视觉资产", description: "统一人物与世界观", icon: ImageIcon },
  { id: 3, label: "创作画布", description: "分镜与视频生成", icon: Workflow },
]

export const WorkflowLayout = () => {
  const { novelId, chapterId, stepId } = useParams<{
    novelId: string
    chapterId: string
    stepId: string
  }>()

  const nId = parseInt(novelId ?? "0")
  const cId = parseInt(chapterId ?? "0")
  const currentStep = parseInt(stepId ?? "1")

  const renderStepContent = () => {
    switch (currentStep) {
      case 1:
        return <StepExtraction chapterId={cId} novelId={nId} />
      case 2:
        return <StepAssets chapterId={cId} novelId={nId} />
      case 3:
        return <Suspense fallback={<CanvasLoading />}><CreativeCanvas chapterId={cId} novelId={nId} /></Suspense>
      case 4:
        return <Suspense fallback={<CanvasLoading />}><CreativeCanvas chapterId={cId} novelId={nId} /></Suspense>
      default:
        return <StepExtraction chapterId={cId} novelId={nId} />
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      <header className="workflow-header">
        <div className="workflow-header__back">
          <Button variant="ghost" size="sm" asChild>
            <Link to={`/novel/${novelId}`}>
              <ChevronLeft className="h-4 w-4 mr-1" />
              返回章节
            </Link>
          </Button>
          <span className="workflow-header__divider" />
          <div>
            <strong>章节制作流程</strong>
            <small>Chapter workspace</small>
          </div>
        </div>
        <nav className="workflow-steps" aria-label="章节制作进度">
          {steps.map((step) => {
            const visibleStep = Math.min(currentStep, 3)
            const isActive = visibleStep === step.id
            const isPast = currentStep > step.id
            const Icon = step.icon
            return (
              <Link
                key={step.id}
                to={`/novel/${novelId}/chapter/${chapterId}/step/${step.id}`}
                className={cn(
                  "workflow-step",
                  isActive && "is-active",
                  isPast && "is-complete"
                )}
              >
                <span className="workflow-step__icon">{isPast ? <Check /> : <Icon />}</span>
                <span><strong>{step.label}</strong><small>{step.description}</small></span>
              </Link>
            )
          })}
        </nav>
      </header>
      <div className={cn("min-h-0 flex-1", currentStep >= 3 ? "overflow-hidden" : "overflow-auto")}>
        {renderStepContent()}
      </div>
    </div>
  )
}

const CanvasLoading = () => (
  <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground">
    <Loader2 className="h-4 w-4 animate-spin" />正在打开创作画布…
  </div>
)
