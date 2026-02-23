import { TaskStatusEnum, VideoModelTypeEnum } from '@/types'

export function statusColor(status?: TaskStatusEnum): string {
  switch (status) {
    case TaskStatusEnum.COMPLETED: return 'success'
    case TaskStatusEnum.PROCESSING: return 'info'
    case TaskStatusEnum.PENDING:
    case TaskStatusEnum.QUEUED: return 'warning'
    case TaskStatusEnum.FAILED: return 'destructive'
    case TaskStatusEnum.CANCELLED: return 'secondary'
    default: return 'outline'
  }
}

export function statusLabel(status?: TaskStatusEnum): string {
  switch (status) {
    case TaskStatusEnum.COMPLETED: return '已完成'
    case TaskStatusEnum.PROCESSING: return '处理中'
    case TaskStatusEnum.PENDING: return '等待中'
    case TaskStatusEnum.QUEUED: return '排队中'
    case TaskStatusEnum.FAILED: return '失败'
    case TaskStatusEnum.CANCELLED: return '已取消'
    default: return '未知'
  }
}

export function modelLabel(type?: VideoModelTypeEnum): string {
  switch (type) {
    case VideoModelTypeEnum.VIDU_Q2: return 'Vidu Q2'
    case VideoModelTypeEnum.SORA_2: return 'Sora 2'
    case VideoModelTypeEnum.SEEDANCE: return 'Seedance'
    case VideoModelTypeEnum.VEO_3: return 'Veo 3'
    default: return '未知'
  }
}

export function sleep(ms: number): Promise<void> {
  return new Promise(r => setTimeout(r, ms))
}
