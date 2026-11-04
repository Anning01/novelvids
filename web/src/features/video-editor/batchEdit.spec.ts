import { expect, it } from 'vitest'
import { patchClips } from './batchEdit'
import { editorFixture } from './fixtures'
import type { AudioClip } from './types'

it('changes only requested compatible fields in one batch and preserves other values',()=>{
  const doc=editorFixture().document
  const audio:AudioClip={id:'a',type:'audio',name:'BGM',source:{kind:'asset',id:4},start:0,duration:5,trim_in:0,volume:.4,fade_in:0,fade_out:0,loop:false}
  doc.clips.push(audio,{id:'s',type:'subtitle',name:'',start:0,duration:3,text:'Keep',font:'sans',font_size:42,color:'#ffffff',bottom:10})
  const next=patchClips(doc,['v1','a','s'],{volume:.2})
  expect(next.clips[0]).toMatchObject({volume:.2,speed:1})
  expect(next.clips.find(c=>c.id==='a')).toMatchObject({volume:.2})
  expect(next.clips.find(c=>c.id==='s')).not.toHaveProperty('volume')
  expect(next.clips.find(c=>c.id==='s')).toBe(doc.clips.find(c=>c.id==='s'))
  expect(next.clips[1]).toBe(doc.clips[1])
  expect(doc.clips[0]).toMatchObject({volume:1})
})

it('handles 500 clips in one batch without cloning unselected clips or changing their timing',()=>{
  const doc=editorFixture().document
  doc.clips=Array.from({length:500},(_,i)=>({id:`s${i}`,type:'subtitle' as const,name:'',start:i,duration:1,text:`Line ${i}`,font:'sans' as const,font_size:42,color:'#ffffff',bottom:10}))
  const ids=doc.clips.slice(0,400).map(c=>c.id)
  const result=patchClips(doc,ids,{font_size:32,bold:true})
  expect(result.clips.slice(0,400).every(c=>c.type==='subtitle'&&c.font_size===32&&c.bold)).toBe(true)
  expect(result.clips[450]).toBe(doc.clips[450])
  expect(result.clips.map(c=>c.start)).toEqual(doc.clips.map(c=>c.start))
})

it('retimes several videos using each source endpoint and keeps the main track contiguous',async()=>{
  const {retimeClips}=await import('./batchEdit')
  const fixture=editorFixture()
  fixture.document.clips.push({id:'s',type:'subtitle',name:'',start:4,duration:1,text:'Later',font:'sans',font_size:42,color:'#ffffff',bottom:10})
  const next=retimeClips(fixture.document,['v1','v2'],2,fixture.media)
  expect(next.clips.filter(c=>c.type==='video').map(c=>[c.start,c.duration,c.speed,c.trim_out])).toEqual([[0,1,2,2],[1,1,2,2],[2,2,1,undefined]])
  expect(next.clips.find(c=>c.id==='s')?.start).toBe(2)
  expect(fixture.document.clips[0]?.duration).toBe(2)
})
