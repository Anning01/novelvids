import { mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import SceneVoiceTracks from './SceneVoiceTracks.vue'
import type { Asset, Scene } from '@/types'
it('shows the offscreen speaker by name and keeps the image bindings unchanged', async () => {
  const base = {novel_id: 1, asset_type: 1, created_at: '', updated_at: ''}
  const woman: Asset = {...base, id: 3, canonical_name: '王许氏', metadata:{work_package:{id:'woman'}}}
  const boy: Asset = {...base, id: 1, canonical_name: '徐长寿', metadata:{work_package:{id:'boy'}}}
  const scene: Scene = {id:4,sequence:4,created_at:'',updated_at:'',asset_ids:[1],metadata:{work_package:{voices:[
    {asset_id:'woman', mode:'offscreen',start:10.7,end:12.6,text:'徐长寿，开饭了！'},
    {asset_id:'boy', mode:'dialogue',start:12.8,end:13.4,text:'来了！'}]}}}
  const wrapper = mount(SceneVoiceTracks,{props:{scene,assets:[boy,woman]}})
  const [first,second] = wrapper.findAll('li')
  expect(first!.text()).toContain('王许氏画外音10.7–12.6s')
  expect(second!.text()).toContain('徐长寿对白12.8–13.4s')
  await first!.get('button').trigger('click')
  expect(wrapper.emitted('voice')?.[0]).toEqual([woman])
  expect(scene.asset_ids).toEqual([1])
  wrapper.unmount()
})
