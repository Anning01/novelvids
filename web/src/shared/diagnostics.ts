export const DIAGNOSTIC_LIMIT = 100
export interface DiagnosticEntry {
  time: string
  source: 'task' | 'web'
  [field: string]: unknown
}

const entries: DiagnosticEntry[] = []
let currentScope = ''
const modules = new Set(['auth','config','novel','chapter','scene','asset','video','task','file','creation-agent',
  'remake','billing','workbench','resource-library','video-editor','portfolio','finished-episodes','media-library','experience'])

export function diagnosticScope(scope: string) {
  if (scope !== currentScope) {
    currentScope = scope
    entries.length = 0
  }
}

export function recordRequestFailure(scope: string, url: string, method: string, httpStatus: number, code: number) {
  if (scope !== currentScope || url.startsWith('/diagnostics/')) return
  const path = url.split('?')[0] || ''
  const module = path.split('/')[1] || ''
  entries.push({time:new Date().toISOString(), source:'web', module:modules.has(module) ? module : 'other',
    method:['GET','POST','PUT','PATCH','DELETE'].includes(method) ? method : 'other',
    http_status:httpStatus, code:Number.isFinite(code) ? code : httpStatus,
    ...(path === '/remake/uploads' ? {operation:'upload_video'} : {})})
  if (entries.length > DIAGNOSTIC_LIMIT) entries.shift()
}

export function diagnosticReport(scope: string, tasks: DiagnosticEntry[], backendAvailable: boolean) {
  const combined = [...tasks, ...(scope === currentScope ? entries : [])]
    .sort((a,b) => Date.parse(b.time) - Date.parse(a.time)).slice(0,DIAGNOSTIC_LIMIT)
  return {format_version:1, exported_at:new Date().toISOString(), backend_available:backendAvailable,
    count:combined.length, entries:combined}
}
