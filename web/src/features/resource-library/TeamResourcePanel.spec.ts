import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { catalogApi } from './catalog'
import TeamResourcePanel from './TeamResourcePanel.vue'
vi.mock('./catalog',()=>({catalogApi:{list:vi.fn()}}))
beforeEach(()=>{vi.clearAllMocks();vi.mocked(catalogApi.list).mockImplementation(async query=>({data:{items:[{key:'media:7',catalog:'media',id:7,kind:query?.kind,name:'Shared',url:'/media/shared',origin:'team',folder_id:0,state:'ready',editable:true,created_at:'',duration:3}],pagination:{page:1,pages:1,total:1,page_size:24}}}) as never)})
it.each([['audio','bgm'],['sticker','sticker'],['video','video']] as const)('previews %s separately from inserting a typed library source',async(kind,resourceKind)=>{const wrapper=mount(TeamResourcePanel,{props:{kind,readOnly:false},global:{plugins:[createPinia()],stubs:{RouterLink:{template:'<a><slot/></a>'}}}});await flushPromises();expect(catalogApi.list).toHaveBeenCalledWith(expect.objectContaining({kind:resourceKind,origin:'all'}));await wrapper.get('[aria-label="预览 Shared"]').trigger('click');expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({kind,source:{kind:'library',id:7}});expect(wrapper.emitted('add')).toBeUndefined();await wrapper.get('[aria-label="添加素材 Shared"]').trigger('click');expect(wrapper.emitted('add')).toHaveLength(1);wrapper.unmount()})

it('shows public resources alongside team uploads so shared BGM is usable in the editor',async()=>{
  const publicItem={key:'media:9',catalog:'media',id:9,kind:'bgm',name:'Public music',url:'https://oss/public.mp3',origin:'system',folder_id:0,state:'ready',editable:false,created_at:'',duration:5}
  const teamItem={key:'media:7',catalog:'media',id:7,kind:'bgm',name:'Shared',url:'/media/shared',origin:'team',folder_id:0,state:'ready',editable:true,created_at:'',duration:3}
  vi.mocked(catalogApi.list).mockResolvedValueOnce({data:{items:[teamItem,publicItem],pagination:{page:1,pages:1,total:2,page_size:24}}} as never)
  const wrapper=mount(TeamResourcePanel,{props:{kind:'audio',readOnly:false},global:{plugins:[createPinia()],stubs:{RouterLink:{template:'<a><slot/></a>'}}}})
  await flushPromises()
  expect(catalogApi.list).toHaveBeenCalledWith(expect.objectContaining({kind:'bgm',origin:'all'}))
  expect(wrapper.text()).toContain('Shared')
  expect(wrapper.text()).toContain('Public music')
  await wrapper.get('[aria-label="添加素材 Public music"]').trigger('click')
  expect(wrapper.emitted('add')?.[0]?.[0]).toMatchObject({name:'Public music',source:{kind:'library',id:9},duration:5})
  wrapper.unmount()
})
