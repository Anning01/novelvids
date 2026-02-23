import * as React from "react"
import { cn } from "@/lib/utils"

const Label = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <label
      ref={ref}
      className={cn(
        "text-xs font-bold uppercase tracking-wider text-muted-foreground mb-1.5 block",
        className
      )}
      {...props}
    />
  )
)
Label.displayName = "Label"

export { Label }
