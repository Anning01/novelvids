import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { catalogApi } from './catalog'
import { libraryApi } from './api'
import AppSelect from '@/components/AppSelect.vue'
import AppButton from '@/components/AppButton.vue'
import TeamResourcePanel from './TeamResourcePanel.vue'
vi.mock('./api',()=>({libraryApi:{folders:vi.fn()}}))
vi.mock('./catalog',()=>({catalogApi:{list:vi.fn()}}))
beforeEach(()=>{vi.clearAllMocks();vi.mocked(libraryApi.folders).mockResolvedValue({data:[]} as never);vi.mocked(catalogApi.list).mockImplementation(async query=>({data:{items:[{key:'media:7',catalog:'media',id:7,kind:query?.kind,name:'Shared',url:'/media/shared',origin:'team',folder_id:0,state:'ready',editable:true,created_at:'',duration:3}],pagination:{page:1,pages:1,total:1,page_size:24}}}) as never)})
it.each([['audio','bgm'],['sticker','sticker'],['video','video']] as const)('previews %s separately from inserting a typed library source',async(kind,resourceKind)=>{const wrapper=mount(TeamResourcePanel,{props:{kind,readOnly:false},global:{plugins:[createPinia()],components:{AppButton},stubs:{RouterLink:{template:'<a><slot/></a>'}}}});await flushPromises();expect(catalogApi.list).toHaveBeenCalledWith(expect.objectContaining({kind:resourceKind,origin:'all'}));await wrapper.get('[aria-label="预览 Shared"]').trigger('click');expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({kind,source:{kind:'library',id:7}});expect(wrapper.emitted('add')).toBeUndefined();await wrapper.get('[aria-label="添加素材 Shared"]').trigger('click');expect(wrapper.emitted('add')).toHaveLength(1);wrapper.unmount()})

it('shows public resources alongside team uploads so shared BGM is usable in the editor',async()=>{
  const publicItem={key:'media:9',catalog:'media',id:9,kind:'bgm',name:'Public music',url:'https://oss/public.mp3',origin:'system',folder_id:0,state:'ready',editable:false,created_at:'',duration:5}
  const teamItem={key:'media:7',catalog:'media',id:7,kind:'bgm',name:'Shared',url:'/media/shared',origin:'team',folder_id:0,state:'ready',editable:true,created_at:'',duration:3}
  vi.mocked(catalogApi.list).mockResolvedValueOnce({data:{items:[teamItem,publicItem],pagination:{page:1,pages:1,total:2,page_size:24}}} as never)
  const wrapper=mount(TeamResourcePanel,{props:{kind:'audio',readOnly:false},global:{plugins:[createPinia()],components:{AppButton},stubs:{RouterLink:{template:'<a><slot/></a>'}}}})
  await flushPromises()
  expect(catalogApi.list).toHaveBeenCalledWith(expect.objectContaining({kind:'bgm',origin:'all'}))
  expect(wrapper.text()).toContain('Shared')
  expect(wrapper.text()).toContain('Public music')
  await wrapper.get('[aria-label="添加素材 Public music"]').trigger('click')
  expect(wrapper.emitted('add')?.[0]?.[0]).toMatchObject({name:'Public music',source:{kind:'library',id:9},duration:5})
  wrapper.unmount()
})

it('filters by nested folders and automatically appends pages once on intersection',async()=>{
  const callbacks: IntersectionObserverCallback[]=[]
  const disconnect=vi.fn()
  vi.stubGlobal('IntersectionObserver',class { constructor(callback:IntersectionObserverCallback){callbacks.push(callback)} observe=vi.fn();disconnect=disconnect })
  vi.mocked(libraryApi.folders).mockResolvedValue({data:[{id:2,parent_id:0,name:'Mood'},{id:3,parent_id:2,name:'Calm'}]} as never)
  vi.mocked(catalogApi.list).mockImplementation(async query=>({data:{items:[{key:`media:${query?.page}`,catalog:'media',id:query?.page,kind:'bgm',name:`Page ${query?.page}`,url:'/music.mp3',state:'ready',duration:3}],pagination:{page:query?.page,pages:2,total:2,page_size:1}}}) as never)
  const wrapper=mount(TeamResourcePanel,{props:{kind:'audio',readOnly:false},global:{plugins:[createPinia()],components:{AppButton},stubs:{RouterLink:true}}})
  await flushPromises()
  expect(wrapper.getComponent(AppSelect).props('options')).toContainEqual({value:'3',label:'Mood / Calm'})
  wrapper.getComponent(AppSelect).vm.$emit('update:modelValue','3')
  await flushPromises()
  expect(catalogApi.list).toHaveBeenLastCalledWith(expect.objectContaining({folder_id:3,page:1}))
  const callback=callbacks.at(-1)!
  callback([{isIntersecting:true}] as IntersectionObserverEntry[],{} as IntersectionObserver)
  callback([{isIntersecting:true}] as IntersectionObserverEntry[],{} as IntersectionObserver)
  await flushPromises()
  expect(vi.mocked(catalogApi.list).mock.calls.filter(([q])=>q?.folder_id===3&&q.page===2)).toHaveLength(1)
  expect(wrapper.text()).toContain('Page 1')
  expect(wrapper.text()).toContain('Page 2')
  callback([{isIntersecting:true}] as IntersectionObserverEntry[],{} as IntersectionObserver)
  await flushPromises()
  expect(vi.mocked(catalogApi.list).mock.calls.filter(([q])=>q?.page===2)).toHaveLength(1)
  wrapper.unmount()
  expect(disconnect).toHaveBeenCalled()
  vi.unstubAllGlobals()
})

it('preserves loaded pages on failure and retries the failed page',async()=>{
  vi.mocked(catalogApi.list).mockResolvedValueOnce({data:{items:[{key:'media:1',id:1,catalog:'media',kind:'bgm',name:'First',url:'/one.mp3',state:'ready'}],pagination:{page:1,pages:2,total:2,page_size:1}}} as never)
  const wrapper=mount(TeamResourcePanel,{props:{kind:'audio',readOnly:true},global:{plugins:[createPinia()],components:{AppButton},stubs:{RouterLink:true}}})
  await flushPromises()
  expect(wrapper.get('[aria-label="添加素材 First"]').attributes('disabled')).toBeDefined()
  vi.mocked(catalogApi.list).mockRejectedValueOnce(new Error('Network failed'))
  await wrapper.findAll('button').find(button=>button.text()==='加载更多')!.trigger('click')
  await flushPromises()
  expect(wrapper.get('[role="alert"]').text()).toBe('Network failed')
  expect(wrapper.text()).toContain('First')
  vi.mocked(catalogApi.list).mockResolvedValueOnce({data:{items:[{key:'media:2',id:2,catalog:'media',kind:'bgm',name:'Second',url:'/two.mp3',state:'ready'}],pagination:{page:2,pages:2,total:2,page_size:1}}} as never)
  await wrapper.findAll('button').find(button=>button.text()==='重新加载')!.trigger('click')
  await flushPromises()
  expect(catalogApi.list).toHaveBeenLastCalledWith(expect.objectContaining({page:2}))
  expect(wrapper.text()).toContain('First')
  expect(wrapper.text()).toContain('Second')
  expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  wrapper.unmount()
})

it('ignores an earlier response after the folder changes',async()=>{
  let finish!: (value: never)=>void
  vi.mocked(catalogApi.list).mockImplementationOnce(()=>new Promise(resolve=>{finish=resolve}))
  vi.mocked(libraryApi.folders).mockResolvedValue({data:[{id:2,parent_id:0,name:'Mood'}]} as never)
  const wrapper=mount(TeamResourcePanel,{props:{kind:'audio',readOnly:false},global:{plugins:[createPinia()],components:{AppButton},stubs:{RouterLink:true}}})
  await flushPromises()
  wrapper.getComponent(AppSelect).vm.$emit('update:modelValue','2')
  await flushPromises()
  finish({data:{items:[{key:'media:99',id:99,catalog:'media',kind:'bgm',name:'Stale',state:'ready'}],pagination:{page:1,pages:8,total:8,page_size:1}}} as never)
  await flushPromises()
  expect(wrapper.text()).toContain('Shared')
  expect(wrapper.text()).not.toContain('Stale')
  wrapper.unmount()
})


it.each(['light','dark'])('uses the shared compact folder selector and themed popup (%s)',async theme=>{
  document.documentElement.dataset.appTheme=theme
  vi.mocked(libraryApi.folders).mockResolvedValue({data:[{id:2,parent_id:0,name:'Mood'},{id:3,parent_id:2,name:'Calm'}]} as never)
  const wrapper=mount(TeamResourcePanel,{props:{kind:'audio',readOnly:false},global:{plugins:[createPinia()],components:{AppButton},stubs:{RouterLink:true}}})
  await flushPromises()
  expect(wrapper.find('select').exists()).toBe(false)
  expect(wrapper.getComponent(AppSelect).props('density')).toBe('compact')
  await wrapper.get('button[aria-label="文件夹"]').trigger('click')
  const menu=document.querySelector<HTMLElement>('[role="listbox"][aria-label="文件夹"]')!
  expect(menu).not.toBeNull()
  const option=Array.from(menu.querySelectorAll<HTMLButtonElement>('[role="option"]')).find(row=>row.textContent?.includes('Mood / Calm'))!
  option.click();await flushPromises()
  expect(catalogApi.list).toHaveBeenLastCalledWith(expect.objectContaining({folder_id:3,page:1}))
  expect(wrapper.get('button[aria-label="文件夹"]').text()).toContain('Mood / Calm')
  expect(document.querySelector('[role="listbox"][aria-label="文件夹"]')).toBeNull()
  await wrapper.get('button[aria-label="文件夹"]').trigger('click')
  await wrapper.get('button[aria-label="文件夹"]').trigger('keydown',{key:'Escape'})
  expect(document.querySelector('[role="listbox"][aria-label="文件夹"]')).toBeNull()
  wrapper.unmount()
})
