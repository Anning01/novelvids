import type { WatchSource } from 'vue'
import { useVueFlow } from '@vue-flow/core'
import { nextTick, onBeforeUnmount, watch } from 'vue'

export function useWorkbenchNodeDimensionSync(nodeId: string, source: WatchSource<unknown>) {
  const { updateNodeInternals } = useVueFlow()
  let active = true
  let pending = false

  async function syncNodeDimensions() {
    if (pending) return
    pending = true
    await nextTick()
    pending = false
    if (active) updateNodeInternals([nodeId])
  }

  watch(source, syncNodeDimensions, { flush: 'post' })
  onBeforeUnmount(() => {
    active = false
  })

  return syncNodeDimensions
}
