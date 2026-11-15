import { expect, it } from 'vitest'
import { assetGallery, storyboardGallery } from './imageGallery'
import type { Asset, Scene } from '@/types'
it('browses all available chapter sheets in shot order, retaining original shot numbers and previous render', () => {
  const scenes = [
    {id:3, sequence:3, metadata:{storyboard_sheet:{previous_image_url:'/media/3.png'}}},
    {id:1, sequence:1, metadata:{storyboard_sheet:{image_url:'/media/1.png'}}},
    {id:2, sequence:2},
  ] as Scene[]
  expect(storyboardGallery(scenes)).toEqual([
    {src:'/media/1.png',alt:'分镜 1 · 线稿故事版',label:'1'},
    {src:'/media/3.png',alt:'分镜 3 · 线稿故事版',label:'3'},
  ])
  expect(scenes[0]!.id).toBe(3)
})


it('browses one main image per asset and one image per variant, excluding alternate shots and history', () => {
  const assets = [
    {id:3, asset_type:2, canonical_name:'山谷', main_image:'/valley.png'},
    {id:1, asset_type:1, canonical_name:'苏玄', main_image:'/base.png', angle_image_1:'/angle.png',
      metadata:{image_gallery:['/old.png']}, variants:[
        {id:1,name:'前世',images:['/past.png','/past-alternate.png']},
        {id:2,name:'襁褓',images:['/baby.png']},
        {id:3,name:'未生成',images:[]},
      ]},
    {id:2, asset_type:1, canonical_name:'小伙伴', main_image:'/friend.png'},
  ] as Asset[]
  expect(assetGallery(assets)).toEqual([
    {src:'/base.png',alt:'苏玄'}, {src:'/past.png',alt:'苏玄 · 前世'},
    {src:'/baby.png',alt:'苏玄 · 襁褓'}, {src:'/friend.png',alt:'小伙伴'},
    {src:'/valley.png',alt:'山谷'},
  ])
  expect(assets[0]!.id).toBe(3)
})
