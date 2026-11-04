import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import { catalogApi, type CatalogResource } from './catalog'
import { libraryApi } from './api'
import AppSelect from '@/components/AppSelect.vue'
import { useAuthStore } from '@/features/auth/authStore'
import ResourceCatalogBrowser from './ResourceCatalogBrowser.vue'
vi.mock('./catalog',()=>({catalogApi:{list:vi.fn(),capabilities:vi.fn(),rename:vi.fn(),move:vi.fn(),projects:vi.fn(),upload:vi.fn()}}))
vi.mock('./api',()=>({libraryApi:{folders:vi.fn(),writeFolder:vi.fn(),delete:vi.fn()}}))
const item:CatalogResource={key:'media:1',catalog:'media',id:1,kind:'bgm',name:'Shared music',url:'/music.wav',origin:'team',folder_id:0,created_at:'',editable:true,duration:3,state:'ready'}
const page=(items:CatalogResource[])=>({code:0,message:'',data:{items,pagination:{total:items.length,page:1,page_size:24,pages:1}}})
beforeEach(()=>{vi.clearAllMocks();vi.mocked(catalogApi.list).mockResolvedValue(page([item]) as never);vi.mocked(catalogApi.capabilities).mockResolvedValue({data:{kinds:{video:{formats:['mp4'],max_size_mb:100},bgm:{formats:['wav'],max_size_mb:100}},voice:{formats:['mp3','wav'],max_size_mb:15},folder_depth:2}} as never);vi.mocked(libraryApi.folders).mockResolvedValue({data:[{id:2,name:'音乐',parent_id:0,deleting:false}]} as never)})
function render(viewer=false){const pinia=createPinia(),auth=useAuthStore(pinia);auth.enabled=viewer;auth.memberships=viewer?[{team_id:1,role:'viewer'}] as never:[];return mount(ResourceCatalogBrowser,{global:{plugins:[pinia],stubs:{AppButton:{template:'<button><slot/></button>'},ElDialog:{props:['modelValue'],template:'<section v-if="modelValue"><slot/><slot name="footer"/></section>'},CatalogApplyDialog:true,RouterLink:{template:'<a><slot/></a>'}}}})}
it.each(['light','dark'])('lists typed team resources and applies kind + folder + search together (%s)',async theme=>{document.documentElement.dataset.appTheme=theme;const wrapper=render();await flushPromises();await wrapper.findAll('.catalog-tabs button').find(b=>b.text()==='BGM')!.trigger('click');await flushPromises();await wrapper.findAll('.catalog-folder>button')[0]!.trigger('click');await flushPromises();await wrapper.get('[aria-label="搜索资源"]').setValue('Shared');await wrapper.get('.catalog-filter').trigger('submit');await flushPromises();expect(catalogApi.list).toHaveBeenLastCalledWith(expect.objectContaining({kind:'bgm',folder_id:2,search:'Shared'}));expect(wrapper.text()).toContain('Shared music');wrapper.unmount()})
it.each(['light','dark'])('marks only the current folder and sends its exact scope (%s)',async theme=>{
 document.documentElement.dataset.appTheme=theme
 vi.mocked(libraryApi.folders).mockResolvedValue({data:[{id:2,name:'音乐',parent_id:0,deleting:false},{id:3,name:'子目录',parent_id:2,deleting:false}]} as never)
 const wrapper=render();await flushPromises()
 for(const [name,folderId] of [['全部文件夹',undefined],['音乐',2],['子目录',3],['未分类',0],['全部文件夹',undefined]] as const){
  await wrapper.get('.catalog-folders').findAll('button').find(button=>button.text()===name)!.trigger('click');await flushPromises()
  expect(wrapper.findAll('.catalog-folders [aria-current="page"]')).toHaveLength(1)
  expect(wrapper.get('.catalog-folders [aria-current="page"]').text()).toBe(name)
  expect(wrapper.get('.catalog-folders [aria-current="page"]').element.closest('.active')).not.toBeNull()
  expect(catalogApi.list).toHaveBeenLastCalledWith(expect.objectContaining({folder_id:folderId}))
 }
 wrapper.unmount()
})
it('previews and selects without applying or rewriting the resource',async()=>{const wrapper=render();await flushPromises();await wrapper.get('[aria-label="预览 Shared music"]').trigger('click');expect(wrapper.find('.catalog-details').exists()).toBe(true);expect(wrapper.get('audio').attributes('src')).toBe('/music.wav');expect(catalogApi.rename).not.toHaveBeenCalled();expect(catalogApi.upload).not.toHaveBeenCalled();wrapper.unmount()})
it('keeps upload and write operations unavailable to viewers',async()=>{const wrapper=render(true);await flushPromises();const upload=wrapper.findAll('button').find(b=>b.text()==='上传资源')!;expect(upload.attributes('disabled')).toBeDefined();await wrapper.get('[aria-label="预览 Shared music"]').trigger('click');expect(wrapper.findAll('button').find(b=>b.text()==='用于项目')!.attributes('disabled')).toBeDefined();wrapper.unmount()})
it('discards a previous team response after switching scope',async()=>{let resolve!:(value:ReturnType<typeof page>)=>void;vi.mocked(catalogApi.list).mockImplementationOnce(()=>new Promise(r=>{resolve=r}));const wrapper=render();await flushPromises();vi.mocked(catalogApi.list).mockResolvedValue(page([]) as never);useAuthStore().activeTeamId=8;await flushPromises();resolve(page([item]));await flushPromises();expect(wrapper.text()).not.toContain('Shared music');wrapper.unmount()})
it('shows a recoverable error instead of a false empty success',async()=>{vi.mocked(catalogApi.list).mockRejectedValueOnce(new Error('Network unavailable'));const wrapper=render();await flushPromises();expect(wrapper.get('[role="alert"]').text()).toContain('Network unavailable');vi.mocked(catalogApi.list).mockResolvedValue(page([item]) as never);await wrapper.findAll('button').find(b=>b.text()==='重新加载')!.trigger('click');await flushPromises();expect(wrapper.text()).toContain('Shared music');wrapper.unmount()})
it('finishes the visible upload queue and re-enables controls without refreshing',async()=>{let resolve!:(value:CatalogResource)=>void;vi.mocked(catalogApi.upload).mockImplementationOnce(()=>new Promise(r=>{resolve=r}));const wrapper=render();await flushPromises();await wrapper.findAll('button').find(b=>b.text()==='上传资源')!.trigger('click');const field=wrapper.get('input[type="file"]');Object.defineProperty(field.element,'files',{configurable:true,value:[new File(['video'],'clip.mp4',{type:'video/mp4'})]});await field.trigger('change');await flushPromises();expect(wrapper.get('button[aria-label="资源类型"]').attributes('disabled')).toBeDefined();resolve({...item,kind:'video'});await flushPromises();expect(wrapper.text()).toContain('上传成功，已存入资源库');expect(wrapper.get('button[aria-label="资源类型"]').attributes('disabled')).toBeUndefined();wrapper.unmount()})
it('refreshes selected details after moving a resource without changing its identity',async()=>{vi.mocked(catalogApi.move).mockResolvedValue({} as never);const wrapper=render();await flushPromises();await wrapper.get('[aria-label="预览 Shared music"]').trigger('click');await wrapper.get('input[type="checkbox"]').trigger('click');await wrapper.findAll('button').find(b=>b.text()==='移动到')!.trigger('click');wrapper.findAllComponents(AppSelect).find(select=>select.props('ariaLabel')==='目标文件夹')!.vm.$emit('update:modelValue','2');await flushPromises();vi.mocked(catalogApi.list).mockResolvedValue(page([{...item,folder_id:2}]) as never);await wrapper.get('.catalog-form').trigger('submit');await flushPromises();expect(catalogApi.move).toHaveBeenCalledWith(['media:1'],2);expect(wrapper.get('.catalog-details').text()).toContain('音乐');expect(wrapper.get('.catalog-details').text()).toContain('Shared music');wrapper.unmount()})
it('lays the upload dialog out as labelled fields with a drop zone and a compact destination row',async()=>{
 const wrapper=render();await flushPromises()
 await wrapper.findAll('button').find(b=>b.text()==='上传资源')!.trigger('click');await flushPromises()
 const upload=wrapper.get('.catalog-upload')
 expect(upload.findAll('.catalog-upload__label').map(label=>label.text())).toEqual(['资源类型','保存位置','上传文件'])
 expect(upload.get('.catalog-upload__path-value').text()).toContain('未分类')
 expect(upload.find('.app-dropzone').exists()).toBe(true)
 expect(upload.get('input[type="file"]').classes()).toContain('app-dropzone__input')
 wrapper.unmount()
})
it('keeps the voice upload action in the dialog footer and disabled until a usable clip exists',async()=>{
 const wrapper=render();await flushPromises()
 await wrapper.findAll('button').find(b=>b.text()==='上传资源')!.trigger('click');await flushPromises()
 wrapper.findAllComponents(AppSelect).find(select=>select.props('ariaLabel')==='资源类型')!.vm.$emit('update:modelValue','voice');await flushPromises()
 const action=wrapper.findAll('button').find(b=>b.text()==='上传到团队资源库')
 expect(action).toBeDefined()
 expect(action!.attributes('disabled')).toBeDefined()
 expect(wrapper.find('.catalog-upload__actions').exists()).toBe(true)
 expect(wrapper.get('.catalog-upload__hint').text()).toContain('选择 1–30 秒音频')
 wrapper.unmount()
})
