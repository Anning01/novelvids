import { expect, it } from 'vitest'
import { modelImageMentions } from './modelImageMentions'
import type { VideoInputImageReference } from '@/types'

it('resolves exact picture numbers and explicit subject definitions without guessing ambiguous subjects', () => {
  const images: VideoInputImageReference[] = [1, 2, 5].map(number => ({number, label: String(number), url: String(number), source: 'asset'}))
  const text = 'subject_definitions:\n<Subject 1> from <Picture 2>\n<Subject 2> combines <Picture 1> and <Picture 5>\n\nsummary:\n<Subject 3> near <Picture 7>'
  expect(modelImageMentions(text, images).map(x => [x.syntax,x.image.number])).toEqual([
    ['<Subject 1>',2], ['<Picture 2>',2], ['<Picture 1>',1], ['<Picture 5>',5],
  ])
})

it('maps Seedance picture, subject and scene tokens using the stated bindings', () => {
  const images: VideoInputImageReference[] = [1,2,3].map(number => ({number, label: String(number), url: String(number), source: 'asset'}))
  const text = '参考 @图片1、@图片2、@图片3。将 @图片2 中老人的外形定义为<主体1>；将 @图片1 中男子定义为<主体2>；将 @图片3 中的院落定义为<场景1>。随后<主体1>走进<场景1>。'
  expect(modelImageMentions(text, images).map(({syntax,image}) => [syntax,image.number])).toEqual([
    ['@图片1',1], ['@图片2',2], ['@图片3',3], ['<主体1>',2], ['<主体2>',1], ['<场景1>',3],
  ])
})
