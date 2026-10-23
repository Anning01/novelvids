import { tr } from '@/i18n'

const TOOL_LABELS: Record<string, { operation: string; progress: string }> = {
  read_creation_history: { operation: '回查对话历史', progress: '正在回查对话历史' },
  get_creation_context: { operation: '读取创作上下文', progress: '正在读取创作上下文' },
  list_creation_objects: {operation:'浏览作品对象',progress:'正在浏览作品对象'},
  read_creation_references: {operation:'查看对象引用',progress:'正在查看对象引用'},
  query_creation_objects: { operation: '查找对象', progress: '正在查找对象' },
  create_creation_setting: { operation: '创建新设定', progress: '正在创建新设定' },
  patch_creation_prompts: { operation: '保存提示词调整', progress: '正在保存提示词调整' },
  read_creation_objects: { operation: '查看设定和引用', progress: '正在查看设定和引用' },
  read_creation_prompt_page: { operation: '读取提示词原文', progress: '正在读取提示词原文' },
  apply_creation_changes: { operation: '保存创作调整', progress: '正在保存创作调整' },
  undo_creation_change: { operation: '撤销操作', progress: '正在撤销操作' },
  search_project_memory: { operation: '查找适用记忆', progress: '正在查找适用记忆' },
  get_creation_prompt_rules: { operation: '读取提示词规范', progress: '正在读取提示词规范' },
  finish_creation_reply: { operation: '保存回复与长期规则', progress: '正在保存回复与长期规则' },
}
export function creationAgentToolProgressLabel(name: string): string {
  return tr(TOOL_LABELS[name]?.progress ?? '正在调整提示词')
}
export function creationAgentToolOperationLabel(name: string): string {
  return tr(TOOL_LABELS[name]?.operation ?? '处理本地任务')
}
