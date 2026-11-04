/** One audio graph per player; native volume remains available without Web Audio. */
export class MediaGain {
  private context: AudioContext | null = null
  private nodes = new Map<HTMLMediaElement, { source: MediaElementAudioSourceNode; gain: GainNode }>()
  set(element: HTMLMediaElement, volume: number) {
    if (!this.context && volume > 1 && typeof AudioContext !== 'undefined') this.context = new AudioContext()
    let node = this.nodes.get(element)
    if (this.context && !node) {
      const source = this.context.createMediaElementSource(element), gain = this.context.createGain()
      source.connect(gain); gain.connect(this.context.destination)
      node = { source, gain }; this.nodes.set(element, node)
    }
    element.volume = node ? 1 : Math.min(1, Math.max(0, volume))
    if (node) {
      node.gain.gain.value = Math.max(0, volume)
      if (this.context?.state === 'suspended') void this.context.resume().catch(() => {})
    }
  }
  release(element: HTMLMediaElement) {
    const node = this.nodes.get(element)
    if (!node) return
    node.source.disconnect()
    node.gain.disconnect()
    this.nodes.delete(element)
  }
  dispose() {
    for (const { source, gain } of this.nodes.values()) { source.disconnect(); gain.disconnect() }
    this.nodes.clear()
    if (this.context) void this.context.close().catch(() => {})
  }
}
