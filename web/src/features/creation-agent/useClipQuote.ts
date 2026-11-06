import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { tr } from '@/i18n'
import { clipApi, type ClipInput, type ClipQuote } from './clipApi'

export function useClipQuote(input: Ref<Omit<ClipInput, 'request_id'> | null>, scope: Ref<string>) {
  const quote = ref<ClipQuote | null>(null), loading = ref(false), error = ref('')
  const key = computed(() => JSON.stringify([scope.value, input.value]))
  const quotedKey = ref('')
  const allowed = computed(() => quotedKey.value === key.value && Boolean(quote.value?.allowed && quote.value.estimated_cost !== null) && !loading.value)
  let timer: ReturnType<typeof setTimeout> | undefined, polling: ReturnType<typeof setInterval> | undefined
  let controller: AbortController | null = null, sequence = 0
  async function refresh() {
    clearTimeout(timer)
    const current = ++sequence, currentKey = key.value, value = input.value
    controller?.abort()
    error.value = ''; quote.value = null; quotedKey.value = ''
    if (!value) { loading.value = false; return false }
    controller = new AbortController()
    loading.value = true
    try {
      const response = await clipApi.quote(value, controller.signal)
      if (sequence !== current || key.value !== currentKey) return false
      quote.value = response.data; quotedKey.value = currentKey
      return response.data.allowed
    } catch (caught) {
      if (sequence === current && !controller.signal.aborted) error.value = caught instanceof Error ? caught.message : tr('暂时无法获取预计价格')
      return false
    } finally { if (sequence === current) loading.value = false }
  }
  watch(key, () => {
    ++sequence; controller?.abort(); clearTimeout(timer)
    quote.value = null; quotedKey.value = ''; error.value = ''; loading.value = Boolean(input.value)
    if (input.value) timer = setTimeout(() => { void refresh() }, 250)
  }, {immediate:true, flush:'sync'})
  function onFocus() { if (!document.hidden) void refresh() }
  onMounted(() => { window.addEventListener('focus', onFocus); polling = setInterval(onFocus, 30000) })
  onBeforeUnmount(() => { ++sequence; controller?.abort(); clearTimeout(timer); clearInterval(polling); window.removeEventListener('focus', onFocus) })
  return {quote, loading, error, allowed, refresh}
}
