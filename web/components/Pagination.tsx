import { useState } from 'react'
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface PaginationProps {
  current: number
  total: number
  onChange: (page: number) => void
}

export const Pagination: React.FC<PaginationProps> = ({ current, total, onChange }) => {
  const [jumpValue, setJumpValue] = useState('')

  if (total <= 1) return null

  const handleJump = () => {
    const p = parseInt(jumpValue, 10)
    if (p >= 1 && p <= total && p !== current) {
      onChange(p)
    }
    setJumpValue('')
  }

  // 生成页码按钮列表：首页 ... 中间页码 ... 末页
  const getPageNumbers = (): (number | '...')[] => {
    if (total <= 7) {
      return Array.from({ length: total }, (_, i) => i + 1)
    }
    const pages: (number | '...')[] = [1]
    let start = Math.max(2, current - 1)
    let end = Math.min(total - 1, current + 1)
    // 靠近首页时多显示右边
    if (current <= 3) {
      start = 2
      end = 4
    }
    // 靠近末页时多显示左边
    if (current >= total - 2) {
      start = total - 3
      end = total - 1
    }
    if (start > 2) pages.push('...')
    for (let i = start; i <= end; i++) pages.push(i)
    if (end < total - 1) pages.push('...')
    pages.push(total)
    return pages
  }

  return (
    <div className="flex items-center justify-center gap-1.5 pt-4">
      {/* 首页 */}
      <Button
        variant="outline"
        size="icon"
        className="h-8 w-8"
        onClick={() => onChange(1)}
        disabled={current <= 1}
        title="首页"
      >
        <ChevronsLeft className="h-4 w-4" />
      </Button>
      {/* 上一页 */}
      <Button
        variant="outline"
        size="icon"
        className="h-8 w-8"
        onClick={() => onChange(current - 1)}
        disabled={current <= 1}
        title="上一页"
      >
        <ChevronLeft className="h-4 w-4" />
      </Button>

      {/* 页码按钮 */}
      {getPageNumbers().map((p, i) =>
        p === '...' ? (
          <span key={`ellipsis-${i}`} className="px-1 text-muted-foreground text-sm select-none">
            ...
          </span>
        ) : (
          <Button
            key={p}
            variant={p === current ? 'default' : 'outline'}
            size="icon"
            className="h-8 w-8 text-xs"
            onClick={() => onChange(p)}
          >
            {p}
          </Button>
        ),
      )}

      {/* 下一页 */}
      <Button
        variant="outline"
        size="icon"
        className="h-8 w-8"
        onClick={() => onChange(current + 1)}
        disabled={current >= total}
        title="下一页"
      >
        <ChevronRight className="h-4 w-4" />
      </Button>
      {/* 末页 */}
      <Button
        variant="outline"
        size="icon"
        className="h-8 w-8"
        onClick={() => onChange(total)}
        disabled={current >= total}
        title="末页"
      >
        <ChevronsRight className="h-4 w-4" />
      </Button>

      {/* 跳转 */}
      {total > 5 && (
        <div className="flex items-center gap-1.5 ml-3">
          <span className="text-sm text-muted-foreground whitespace-nowrap">跳至</span>
          <Input
            className="h-8 w-14 text-center text-sm"
            value={jumpValue}
            onChange={(e) => setJumpValue(e.target.value.replace(/\D/g, ''))}
            onKeyDown={(e) => e.key === 'Enter' && handleJump()}
            placeholder={`${current}`}
          />
          <span className="text-sm text-muted-foreground whitespace-nowrap">页</span>
        </div>
      )}
    </div>
  )
}
