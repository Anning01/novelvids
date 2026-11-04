import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/features/auth/authStore'
import { tr } from '@/i18n'
import { catalogApi, type CatalogResource } from './catalog'
export function useLibraryMedia(data:()=>Record<string,unknown>){
  const auth=useAuthStore(),item=ref<CatalogResource|null>(null),error=ref('')
  let sequence=0
  watch(()=>[data().library_resource_id,data().resource_catalog_key,auth.activeTeamId],async()=>{const version=++sequence;item.value=null;error.value='';const key=typeof data().resource_catalog_key==='string'?String(data().resource_catalog_key):Number(data().library_resource_id)?`media:${Number(data().library_resource_id)}`:'';if(!key)return;try{const response=await catalogApi.get(key);if(version===sequence)item.value=response.data}catch{if(version===sequence)error.value=tr('资源已删除或不可用，请重新选择')}},{immediate:true})
  onBeforeUnmount(()=>{++sequence})
  return {item,error,url:computed(()=>item.value?.url||(typeof data().url==='string'?String(data().url):''))}
}
