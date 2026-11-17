import luteUrl from 'vditor/dist/js/lute/lute.min.js?url'
import chineseUrl from 'vditor/dist/js/i18n/zh_CN.js?url'
import englishUrl from 'vditor/dist/js/i18n/en_US.js?url'
import iconsUrl from 'vditor/dist/js/icons/ant.js?url'

const scripts = new Map<string, Promise<void>>()
function loadScript(id: string, url: string) {
  if (!document.getElementById(id)) scripts.delete(id)
  if (!scripts.has(id)) {
    scripts.set(id, new Promise<void>((resolve, reject) => {
      const script = document.createElement('script')
      script.src = url
      script.id = id
      script.onload = () => resolve()
      script.onerror = () => { script.remove(); scripts.delete(id); reject(new Error('editor_resource_unavailable')) }
      document.head.append(script)
    }))
  }
  return scripts.get(id)!
}
export async function loadVditor(language: 'zh_CN' | 'en_US') {
  const [{ default: Vditor }] = await Promise.all([
    import('vditor'), import('vditor/dist/index.css'),
    loadScript('vditorLuteScript', luteUrl),
    loadScript(`vditorI18nScript${language}`, language === 'zh_CN' ? chineseUrl : englishUrl),
    loadScript('vditorIconScript', iconsUrl),
  ])
  return Vditor
}
