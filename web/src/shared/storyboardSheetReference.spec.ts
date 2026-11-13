import { describe, expect, it } from 'vitest'
import { bindSheet, includeSheet, sheetReference, unbindSheet } from './storyboardSheetReference'
import { referencedVideoMedia, videoReferenceMentionSyntax } from './scenePromptReferences'
import type { Scene, VideoReferenceMedia } from '@/types'

describe('storyboard reference binding', () => {
  const scene: Scene = {id:5,sequence:5,created_at:'',updated_at:'',metadata:{storyboard_sheet:{image_url:'/media/sheet.png'}},
    storyboard_binding_rules:{general:{line:'{image} 构图。',headings:['【引用】']},minimax_h3:{line:'{image} supplies composition.',headings:['subject_definitions:']}}}
  it('selects the image for submission from each draft and keeps its own structure', () => {
    const sheet = sheetReference(scene)!
    const media = includeSheet([{type:'image',url:'/media/other.png'}],sheet)
    const syntax = videoReferenceMentionSyntax(sheet)
    for (const [model, text, suffix] of [['', '【引用】\n人物：小张','构图。'],['minimax_h3','subject_definitions:\n<Subject 1> is the boy.','supplies composition.']]) {
      const linked = bindSheet(text!,scene,model)
      expect(linked.split('\n')[1]).toBe(syntax+' '+suffix)
      expect(referencedVideoMedia(linked,media)).toEqual([sheet])
      expect(bindSheet(linked,scene,model)).toBe(linked)
      expect(unbindSheet(linked,scene)).toBe(text)
    }
  })
  it('replaces a regenerated image in the same slot without duplicating the sheet', () => {
    const first = sheetReference(scene)!
    const later: VideoReferenceMedia = {...first,url:'/media/new.png'}
    expect(includeSheet([first],later)).toEqual([later])
    expect(videoReferenceMentionSyntax(first)).toBe(videoReferenceMentionSyntax(later))
  })
})

import { bindBlocking, unbindBlocking, withBlockingReference } from './sceneBlockingReference'

it('binds the overhead image alongside the sheet, with the same order after changing drafts', () => {
  const shot: Scene = {id: 5, sequence: 5, created_at: '', updated_at: '', blocking_reference: {
    type: 'image', name: '定位图', url: '/media/map.svg', mention_url: 'novelvids:blocking-map',
    rules: {general: {line: '{image} 按图调度', headings: ['空间关系：']},
      minimax_h3: {line: '{image} defines the camera axis.', headings: ['subject_definitions:']}},
  }}
  const sheet: VideoReferenceMedia = {type:'image', url:'/media/sheet.png', mention_url:'novelvids:storyboard-sheet'}
  const media = withBlockingReference(shot, [sheet])
  for (const model of ['', 'minimax_h3']) {
    const base = (model ? 'subject_definitions:' : '空间关系：王家牛棚门前') + '\n' + videoReferenceMentionSyntax(sheet)
    const bound = bindBlocking(base, shot, model)
    expect(bound.split('\n')[1]).toContain(videoReferenceMentionSyntax(shot.blocking_reference!))
    expect(referencedVideoMedia(bound, media).map(item => item.url)).toEqual(['/media/sheet.png', '/media/map.svg'])
    expect(bindBlocking(bound, shot, model)).toBe(bound)
    expect(unbindBlocking(bound, shot)).toBe(base)
  }
})
