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
