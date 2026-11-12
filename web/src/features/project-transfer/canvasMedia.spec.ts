import { Blob as NativeBlob } from 'node:buffer'
import { afterEach, expect, it, vi } from 'vitest'
import { BrowserMedia } from './canvasMedia'

afterEach(()=>vi.unstubAllGlobals())
it('keeps browser-only media off the platform and binds all mentions to the same archive member',async()=>{
  vi.stubGlobal('Blob',NativeBlob)
  const url='data:image/png;base64,YQ=='
  const read=vi.fn().mockResolvedValue({ok:true,blob:async()=>new Blob(['a'],{type:'image/png'})})
  vi.stubGlobal('fetch',read)
  const browser=new BrowserMedia()
  const detached=browser.detach({url, prompt:'@{参考图片:'+encodeURIComponent(url)+'} 转身', notes:['文字']})
  expect(JSON.stringify(detached)).not.toContain('base64')
  const entries=[]
  for await (const file of browser.files(6,new AbortController().signal)) entries.push(file)
  expect(read).toHaveBeenCalledTimes(1)
  expect(entries[0]!.member).toBe('media/7.png')
  expect(browser.attach(detached)).toEqual({url:'novelvids:media/7.png',prompt:'@{参考图片:novelvids%3Amedia%2F7.png} 转身',notes:['文字']})
})
