import { computed, ref, watch } from 'vue'
import { API_BASE, authHeaders, mediaUrl } from '@/api'
import type { Scene } from '@/types'
import { fetchFileBlob } from '@/shared/downloadFile'

export function useSceneBlockingMap(scene: () => Scene | undefined) {
  const archived = computed(() => {
    const media = scene()?.metadata?.imported_media
    const file = Array.isArray(media) && media.find(item => item?.role === 'blocking' && typeof item.url === 'string')
    return file ? mediaUrl(file.url) : ''
  })
  const plan = computed(() => {
    const data = scene()?.prompt_params
    return scene()?.blocking_reference || (Array.isArray(data?.segments) && data.segments.length > 1) ? data?.blocking_map : null
  })
  const rendered = ref('')
  const error = ref('')
  watch([() => scene()?.id, archived, plan], async ([id, archive, layout], _, cleanup) => {
    let active = true
    let url = ''
    cleanup(() => { active = false; if (url) URL.revokeObjectURL(url) })
    rendered.value = ''
    error.value = ''
    if (archive || !layout || !id) return
    try {
      const blob = await fetchFileBlob(`${API_BASE}/scene/${id}/blocking-map.svg`, authHeaders())
      if (active) rendered.value = url = URL.createObjectURL(blob)
    } catch (e) {
      if (active) error.value = (e as Error).message
    }
  }, {immediate: true})
  return { image: computed(() => archived.value || rendered.value), error }
}
