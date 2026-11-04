import { expect,it } from 'vitest'
import { subtitleAppearance,subtitleBlockWidth } from './subtitleStyle'
import { editorFixture } from './fixtures'
import { addSubtitle,changeClip,subtitleLines } from './model'
import type { SubtitleClip } from './types'
it('applies text formatting, outline, spacing and alpha in preview coordinates',()=>{
 const [document,id]=addSubtitle(editorFixture().document,0,'Line one\nTwo')
 const clip={...document.clips.find(clip=>clip.id===id),bold:true,italic:true,underline:true,letter_spacing:6,line_spacing:12,align:'right',opacity:.5,stroke_color:'#ff244a',stroke_width:3,shadow:0} as SubtitleClip
 expect(subtitleAppearance(clip,540)).toMatchObject({fontWeight:700,fontStyle:'italic',textDecoration:'underline',letterSpacing:'3px',lineHeight:'31.2px',textAlign:'right',opacity:.5,WebkitTextStroke:'1.5px #ff244a',textShadow:'none'})
 expect(subtitleBlockWidth(clip,document,540)).toBeGreaterThan(80)
 for(const patch of [{opacity:1.1},{letter_spacing:-6},{line_spacing:101},{stroke_color:'red;other'}])expect(()=>changeClip(document,id,patch)).toThrow()
})
it('includes letter spacing when wrapping lines',()=>{
 const [document,id]=addSubtitle(editorFixture().document,0,'你好世界你好')
 const clip={...document.clips.find(clip=>clip.id===id),font_size:30,letter_spacing:20} as SubtitleClip
 expect(subtitleLines(clip,{...document,width:100,height:1080})).toBe('你好\n世界\n你好')
})
