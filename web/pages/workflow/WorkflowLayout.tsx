import { Button } from "@/components/ui/button"
import { User, Image as ImageIcon, Layers, Film, ChevronLeft } from "lucide-react"
import { Link, useParams } from "react-router-dom"
import { StepExtraction } from "./StepExtraction"
import { StepAssets } from "./StepAssets"
import { StepStoryboard } from "./StepStoryboard"
import { StepStudio } from "./StepStudio"
import { cn } from "@/lib/utils"

const steps = [
  { id: 1, label: "实体提取", icon: User },
  { id: 2, label: "视觉资产", icon: ImageIcon },
  { id: 3, label: "分镜管理", icon: Layers },
  { id: 4, label: "视频工作台", icon: Film },
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
        return <StepStoryboard chapterId={cId} novelId={nId} />
      case 4:
        return <StepStudio chapterId={cId} />
      default:
        return <StepExtraction chapterId={cId} novelId={nId} />
    }
  }

  return (
    <div className="flex h-full">
      {/* Left sidebar */}
      <div className="w-56 glass border-r flex flex-col flex-shrink-0">
        <div className="p-4 animate-fade-in">
          <Button variant="ghost" size="sm" asChild className="hover:bg-primary/10 hover:text-primary">
            <Link to={`/novel/${novelId}`}>
              <ChevronLeft className="h-4 w-4 mr-1" />
              返回小说
            </Link>
          </Button>
        </div>

        <div className="mx-4 decorative-line" />

        <div className="p-4 flex flex-col gap-1 animate-fade-up" style={{ animationDelay: '100ms' }}>
          <span className="text-xs uppercase tracking-wider text-muted-foreground/60 mb-2 font-medium">
            工作流步骤
          </span>

          {steps.map((step) => {
            const isActive = currentStep === step.id
            const isPast = currentStep > step.id
            const Icon = step.icon

            return (
              <Link
                key={step.id}
                to={`/novel/${novelId}/chapter/${chapterId}/step/${step.id}`}
                className={cn(
                  "flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 group relative overflow-hidden",
                  isActive
                    ? "bg-primary/10 text-primary border border-primary/20 shadow-sm shadow-primary/10"
                    : isPast
                      ? "text-foreground/70 hover:bg-white/[0.04] border border-transparent"
                      : "text-muted-foreground hover:bg-white/[0.04] border border-transparent"
                )}
              >
                {isActive && (
                  <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-primary rounded-r-full" />
                )}
                <div className={cn(
                  "w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0 transition-colors",
                  isActive
                    ? "bg-primary/20 text-primary"
                    : isPast
                      ? "bg-green-500/10 text-green-500"
                      : "bg-muted/50 text-muted-foreground"
                )}>
                  {isPast ? '✓' : step.id}
                </div>
                <Icon className={cn("h-4 w-4 flex-shrink-0", isActive && "text-primary")} />
                {step.label}
              </Link>
            )
          })}
        </div>
      </div>

      {/* Main content area */}
      <div className="flex-1 overflow-auto">
        {renderStepContent()}
      </div>
    </div>
  )
}
