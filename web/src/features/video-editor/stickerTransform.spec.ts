import { expect,it } from 'vitest'
import { resizeSticker,scaleSticker,stickerRotation } from './stickerTransform'
import type { StickerClip } from './types'
const clip:StickerClip={id:'s',name:'',type:'sticker',start:0,duration:3,source:{kind:'asset',id:1},x:50,y:50,scale:1,opacity:1}
it('resizes around the center while preserving the locked ratio and bounds',()=>{
 expect(resizeSticker(clip,40,0,80,80)).toEqual({scale:1.5,scale_y:1.5})
 expect(scaleSticker({...clip,scale_y:2},2)).toEqual({scale:2,scale_y:4})
 expect(scaleSticker({...clip,scale_y:2},4)).toEqual({scale:2,scale_y:4})
 expect(resizeSticker(clip,-1000,-1000,80,80)).toEqual({scale:.1,scale_y:.1})
})
it('resizes width and height independently when unlocked and normalizes rotation',()=>{
 expect(resizeSticker({...clip,lock_aspect:false},40,0,80,80)).toEqual({scale:2,scale_y:1})
 expect(stickerRotation(270)).toBe(-90)
 expect(stickerRotation(-190)).toBe(170)
})
