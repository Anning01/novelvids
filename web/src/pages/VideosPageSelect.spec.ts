import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { createPinia } from 'pinia'
import AppButton from '@/components/AppButton.vue'
import AppSelect from '@/components/AppSelect.vue'
import { request } from '@/api'
import { catalogApi } from '@/features/resource-library/catalog'
import VideosPage from './VideosPage.vue'
vi.mock('@/api',async original=>({...await original<typeof import('@/api')>(),request:vi.fn()}))
vi.mock('@/features/resource-library/catalog',()=>({catalogApi:{projects:vi.fn(),publish:vi.fn()}}))
beforeEach(()=>{vi.clearAllMocks();vi.mocked(catalogApi.projects).mockResolvedValue({data:{items:[{id:1,name:'Project One'},{id:2,name:'Project Two'}]}} as never);vi.mocked(request).mockResolvedValue({data:{items:[],pagination:{page:1,pages:1,total:0,page_size:24}}} as never)})
afterEach(()=>{document.body.innerHTML='';document.documentElement.removeAttribute('data-app-theme')})
it.each(['light','dark'])('uses the themed shared project selector and loads the selected project (%s)',async theme=>{
 document.documentElement.dataset.appTheme=theme
 const wrapper=mount(VideosPage,{attachTo:document.body,global:{plugins:[createPinia()],components:{AppButton},stubs:{RouterLink:{template:'<a><slot/></a>'}}}})
 await flushPromises()
 const select=wrapper.findComponent(AppSelect)
 expect(select.props('ariaLabel')).toBe('项目')
 expect(wrapper.find('select').exists()).toBe(false)
 await select.get('button').trigger('click');await flushPromises()
 const option=Array.from(document.querySelectorAll<HTMLButtonElement>('[role="option"]')).find(item=>item.textContent?.includes('Project Two'))
 expect(option).toBeTruthy();option!.click();await flushPromises()
 expect(select.props('modelValue')).toBe('2')
 expect(request).toHaveBeenLastCalledWith(expect.stringContaining('novel_id=2'))
 expect(select.get('button').text()).toContain('Project Two')
 wrapper.unmount()
})
