import { afterEach, expect, it, vi } from 'vitest'
import { MediaGain } from './mediaGain'
afterEach(()=>vi.unstubAllGlobals())
it('amplifies above unity, reuses the graph, supports mute and cleans up audio nodes',()=>{
 const source={connect:vi.fn(),disconnect:vi.fn()},gain={connect:vi.fn(),disconnect:vi.fn(),gain:{value:1}}
 const create=vi.fn(()=>source),close=vi.fn(async()=>{})
 vi.stubGlobal('AudioContext',class{state='running';destination={};createMediaElementSource=create;createGain=()=>gain;close=close})
 const mixer=new MediaGain(),element=document.createElement('audio')
 mixer.set(element,10)
 expect(element.volume).toBe(1);expect(gain.gain.value).toBe(10)
 mixer.set(element,.1);expect(gain.gain.value).toBe(.1)
 mixer.set(element,0);expect(gain.gain.value).toBe(0)
 expect(create).toHaveBeenCalledTimes(1)
 mixer.dispose();expect(close).toHaveBeenCalledOnce();expect(source.disconnect).toHaveBeenCalledOnce()
})
it('uses native media volume at unity and below without opening an audio context',()=>{
 const create=vi.fn();vi.stubGlobal('AudioContext',create)
 const mixer=new MediaGain(),element=document.createElement('audio')
 mixer.set(element,.1);expect(element.volume).toBe(.1);expect(create).not.toHaveBeenCalled()
 mixer.dispose()
})
