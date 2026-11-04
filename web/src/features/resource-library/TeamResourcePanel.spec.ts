import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { catalogApi } from './catalog'
import TeamResourcePanel from './TeamResourcePanel.vue'
vi.mock('./catalog',()=>({catalogApi:{list:vi.fn()}}))
beforeEach(()=>{vi.clearAllMocks();vi.mocked(catalogApi.list).mockImplementation(async query=>({data:{items:[{key:'media:7',catalog:'media',id:7,kind:query?.kind,name:'Shared',url:'/media/shared',origin:'team',folder_id:0,state:'ready',editable:true,created_at:'',duration:3}],pagination:{page:1,pages:1,total:1,page_size:24}}}) as never)})
it.each([['audio','bgm'],['sticker','sticker'],['video','video']] as const)('previews %s separately from inserting a typed library source',async(kind,resourceKind)=>{const wrapper=mount(TeamResourcePanel,{props:{kind,readOnly:false},global:{plugins:[createPinia()],stubs:{RouterLink:{template:'<a><slot/></a>'}}}});await flushPromises();expect(catalogApi.list).toHaveBeenCalledWith(expect.objectContaining({kind:resourceKind,origin:'team'}));await wrapper.get('[aria-label="预览 Shared"]').trigger('click');expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({kind,source:{kind:'library',id:7}});expect(wrapper.emitted('add')).toBeUndefined();await wrapper.get('[aria-label="添加素材 Shared"]').trigger('click');expect(wrapper.emitted('add')).toHaveLength(1);wrapper.unmount()})
