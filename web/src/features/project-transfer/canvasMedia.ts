import { tr } from '@/i18n'

const SUFFIX: Record<string,string> = {
  'image/png':'png','image/jpeg':'jpg','image/webp':'webp','image/gif':'gif','image/svg+xml':'svg','image/bmp':'bmp',
  'video/mp4':'mp4','video/webm':'webm','video/quicktime':'mov','audio/wav':'wav','audio/mpeg':'mp3',
  'audio/ogg':'ogg','audio/mp4':'m4a','audio/flac':'flac','audio/aac':'aac',
}

function mapStrings(value: unknown, fn: (text:string)=>string): unknown {
  if (Array.isArray(value)) return value.map(v=>mapStrings(v,fn))
  if (value && typeof value==='object') return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,mapStrings(v,fn)]))
  if (typeof value!=='string') return value
  const changed=fn(value)
  if (changed!==value) return changed
  return value.replace(/(@\{参考(?:图片|视频):)([^}]+)(\})/g,(match, start:string, ref:string, end:string)=>{
    const url=decodeURIComponent(ref), target=fn(url)
    return target===url ? match : start+encodeURIComponent(target)+end
  })
}

export class BrowserMedia {
  private sources = new Map<string,string>()
  private refs = new Map<string,string>()

  detach(value:unknown) {
    return mapStrings(value, source=>{
      if (!source.startsWith('blob:') && !source.startsWith('data:')) return source
      let marker=this.sources.get(source)
      if (!marker) {
        marker='novelvids-browser:'+crypto.randomUUID()
        this.sources.set(source,marker)
      }
      return marker
    })
  }

  async *files(start:number, signal:AbortSignal) {
    for (const [url,marker] of this.sources) {
      if (url.startsWith('blob:') && new URL(url).origin!==location.origin) throw new Error(tr('本地画布素材无法读取'))
      const response=await fetch(url,{signal,credentials:'omit'})
      if (!response.ok) throw new Error(tr('本地画布素材无法读取'))
      const blob=await response.blob()
      const suffix=SUFFIX[blob.type.split(';')[0]!.toLowerCase()]
      if (!suffix) throw new Error(tr('不支持的画布素材格式'))
      const member=`media/${++start}.${suffix}`
      this.refs.set(marker,'novelvids:'+member)
      yield {member,blob}
    }
  }

  attach(value:unknown) { return mapStrings(value, text=>this.refs.get(text) ?? text) }
}
