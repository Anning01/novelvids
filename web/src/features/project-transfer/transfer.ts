import { API_BASE, authHeaders, request } from '@/api'
import { tr } from '@/i18n'
import type { SingleResponse } from '@/types'
import { parseWorkbenchState, WORKBENCH_LAYOUT_VERSION } from '@/features/workbench/store/workbenchPersistence'
import { BrowserMedia } from './canvasMedia'
import { ProjectZip } from './projectZip'

interface ExportMedia { member: string; url: string; authenticated: boolean; storage: 'media' | 'remake' | 'export' }
interface ExportPlan { project: Record<string, unknown>; files: ExportMedia[] }

export async function exportProject(id: number, signal: AbortSignal) {
  const route = `/novel/${id}/transfer`
  let {data: plan} = await request<SingleResponse<ExportPlan>>(route, {signal})
  const browserMedia = new BrowserMedia()
  const layouts: Record<string, unknown> = {}
  for (const chapter of plan.project.chapters as Array<{id:number}>) {
    const key = `novelvids:canvas:${chapter.id}:layout:v`
    const saved = localStorage.getItem(key + WORKBENCH_LAYOUT_VERSION) || localStorage.getItem(key + '1')
    if (!saved) continue
    const layout = parseWorkbenchState(saved)
    if (!layout) throw new Error(tr('本地画布存档无法读取，请检查后重新导出'))
    layouts[String(chapter.id)] = browserMedia.detach(layout)
  }
  if (Object.keys(layouts).length) {
    plan = (await request<SingleResponse<ExportPlan>>(route,{method:'POST',body:JSON.stringify(layouts),signal})).data
  }
  const apiOrigin = new URL(API_BASE, location.href).origin
  const archive = new ProjectZip()
  const media = []
  for (const item of plan.files) {
    const url = new URL(item.url, apiOrigin)
    const signedIn = item.authenticated && url.origin === apiOrigin && /^\/api\/video\/exports\/\d+\/download$/.test(url.pathname)
    const response = await fetch(url, {signal, headers: signedIn ? authHeaders() : {}, credentials: 'omit',
      redirect: signedIn ? 'error' : 'follow', referrerPolicy: 'no-referrer'})
    const contentType = response.headers.get('content-type') ?? ''
    if (!response.ok || contentType.includes('text/html') || (contentType.includes('application/json') && !item.member.endsWith('.json'))) throw new Error(tr('作品素材下载失败，请重试'))
    media.push({...await archive.add(item.member, await response.blob(), signal), storage: item.storage})
  }
  for await (const {member,blob} of browserMedia.files(plan.files.length,signal)) {
    media.push({...await archive.add(member,blob,signal),storage:'media' as const})
  }
  if (Object.keys(layouts).length) plan.project.canvases = browserMedia.attach(plan.project.canvases)
  const manifest = { format: 'novelvids.project', version: 2, project: plan.project, media }
  await archive.add('project.json', new Blob([JSON.stringify(manifest)]), signal)
  return archive.finish()
}

export function importProject(file: File, signal: AbortSignal) {
  const form = new FormData()
  form.append('file', file)
  return request<SingleResponse<{id:number; name:string}>>('/novel/import-project', {method:'POST', body:form, signal})
}
