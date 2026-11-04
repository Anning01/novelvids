import { tr } from '@/i18n'
import { API_BASE, authHeaders, request, requestAllPages, uploadWithProgress } from '@/api'
import type { SingleResponse, PaginationResponse, AudioReference, DigitalHuman, Novel } from '@/types'
import type { ResourceFolder } from './types'
export type MediaKind = 'video' | 'image' | 'bgm' | 'sound' | 'sticker'
export type CatalogKind = MediaKind | 'voice' | 'character'
export interface CatalogResource {
  key: string; catalog: 'media' | 'voice' | 'human' | 'asset'; id: number; kind: CatalogKind
  name: string; url: string; storage_ref?: string; poster_url?: string; origin: 'team' | 'system' | 'personal'
  folder_id: number; created_at: string; editable: boolean; filename?: string; state?: string
  duration?: number; width?: number; height?: number; size_bytes?: number; gender?: string
  country?: string; occupation?: string; age?: number; asset_id?: string; source_asset_id?: number
  description?: string; asset_type?: number; payload?: AudioReference | DigitalHuman
}
export interface CatalogQuery {
  kind?: CatalogKind | 'all'; folder_id?: number; search?: string; origin?: string
  page?: number; page_size?: number; sort?: string; gender?: string; country?: string; age?: string; occupation?: string
}
export interface CatalogCapabilities {
  kinds: Record<MediaKind, {formats: string[]; max_size_mb: number}>
  voice: {formats: string[]; max_size_mb: number; min_duration: number; max_duration: number}
  folder_depth: number
}
const root='/resource-library/catalog'
const json=(method:string,data:unknown)=>({method,body:JSON.stringify(data)})
export const catalogApi={
  projects:()=>requestAllPages<Novel>(page=>`${root}/projects?page=${page}`),
  projectCharacters:(novelId:number)=>requestAllPages<import('@/types').Asset>((page,size)=>`/asset?novel_id=${novelId}&asset_type=1&page=${page}&page_size=${size}`),
  list: (query: CatalogQuery={})=>{
    const params=new URLSearchParams()
    Object.entries(query).forEach(([key,value])=>{if(value!==undefined&&value!=='')params.set(key,String(value))})
    return request<PaginationResponse<CatalogResource>>(`${root}?${params}`)
  },
  capabilities:()=>request<SingleResponse<CatalogCapabilities>>(`${root}/capabilities`),
  get:(key:string)=>request<SingleResponse<CatalogResource>>(`${root}/${encodeURIComponent(key)}`),
  rename:(key:string,name:string)=>request<SingleResponse<CatalogResource>>(`${root}/${encodeURIComponent(key)}`,json('PATCH',{name})),
  move:(keys:string[],folder_id:number)=>request(`${root}/move`,json('POST',{keys,folder_id})),
  publish:(catalog:'asset'|'editor',source_id:number,folder_id=0,kind:MediaKind='video')=>request<SingleResponse<CatalogResource>>(`${root}/publish`,json('POST',{catalog,source_id,folder_id,kind})),
  apply:(key:string,novel_id:number,asset_id?:number,variant_id?:number,chapter_id?:number,canonical_name?:string)=>request<SingleResponse<{novel_id:number;asset_id?:number}>>(`${root}/${encodeURIComponent(key)}/apply`,json('POST',{novel_id,asset_id,variant_id,chapter_id,canonical_name})),
  async upload(file:File,kind:MediaKind,folderId:number,onProgress?:(n:number)=>void){
    const headers=authHeaders(), jsonHeaders={...headers,'Content-Type':'application/json'}
    const policy=await request<SingleResponse<{direct:boolean;resource_id?:number;upload_url?:string;fields?:Record<string,string>}>>(`${root}/upload-policy`,{...json('POST',{filename:file.name,kind,folder_id:folderId}),headers:jsonHeaders})
    const form=new FormData()
    let url=`${API_BASE}${root}/upload`, uploadHeaders=headers
    if(policy.data.direct){
      Object.entries(policy.data.fields||{}).forEach(([key,value])=>form.append(key,value));url=policy.data.upload_url!;uploadHeaders={}
    }else{form.append('kind',kind);form.append('folder_id',String(folderId))}
    form.append('file',file)
    try{
      const result=await uploadWithProgress(url,form,uploadHeaders,onProgress)
      if(result.status<200||result.status>=300)throw new Error(tr('资源上传失败'))
      if(policy.data.direct)return (await request<SingleResponse<CatalogResource>>(`${root}/resources/${policy.data.resource_id}/finalize`,{method:'POST',headers:jsonHeaders})).data
      const payload=JSON.parse(result.text) as SingleResponse<CatalogResource>
      if(payload.code!==0)throw new Error(payload.message)
      return payload.data
    }catch(reason){
      if(policy.data.direct)await request(`/resource-library/resources/${policy.data.resource_id}/cancel-upload`,{method:'POST',headers:jsonHeaders}).catch(()=>undefined)
      throw reason
    }
  },
  async uploadVoice(file:File,nickname:string,gender:string,folderId=0,onProgress?:(n:number)=>void){
    const form=new FormData();form.append('file',file);form.append('nickname',nickname);form.append('gender',gender);form.append('folder_id',String(folderId))
    const result=await uploadWithProgress(`${API_BASE}${root}/voices/upload`,form,authHeaders(),onProgress)
    const payload=JSON.parse(result.text) as SingleResponse<CatalogResource>
    if(result.status>=400||payload.code!==0)throw new Error(payload.message)
    return payload.data
  },
}
export type {ResourceFolder}
