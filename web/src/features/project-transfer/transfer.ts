import { API_BASE, authHeaders, request } from '@/api'
import { tr } from '@/i18n'
import type { SingleResponse } from '@/types'
import { ProjectZip } from './projectZip'

interface ExportMedia { member: string; url: string; authenticated: boolean; storage: 'media' | 'remake' | 'export' }
interface ExportPlan { project: Record<string, unknown>; files: ExportMedia[] }

export async function exportProject(id: number, signal: AbortSignal) {
  const {data: plan} = await request<SingleResponse<ExportPlan>>(`/novel/${id}/transfer`, { signal })
  const apiOrigin = new URL(API_BASE, location.href).origin
  const archive = new ProjectZip()
  const media = []
  for (const item of plan.files) {
    const url = new URL(item.url, apiOrigin)
    const signedIn = item.authenticated && url.origin === apiOrigin && /^\/api\/video\/exports\/\d+\/download$/.test(url.pathname)
    const response = await fetch(url, {signal, headers: signedIn ? authHeaders() : {}, credentials: 'omit',
      redirect: signedIn ? 'error' : 'follow', referrerPolicy: 'no-referrer'})
    if (!response.ok || response.headers.get('content-type')?.includes('application/json')) throw new Error(tr('作品素材下载失败，请重试'))
    media.push({...await archive.add(item.member, await response.blob(), signal), storage: item.storage})
  }
  const manifest = { format: 'novelvids.project', version: 2, project: plan.project, media }
  await archive.add('project.json', new Blob([JSON.stringify(manifest)]), signal)
  return archive.finish()
}

export function importProject(file: File, signal: AbortSignal) {
  const form = new FormData()
  form.append('file', file)
  return request<SingleResponse<{id:number; name:string}>>('/novel/import-project', {method:'POST', body:form, signal})
}
