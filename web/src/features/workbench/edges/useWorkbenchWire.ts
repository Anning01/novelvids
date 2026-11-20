import { computed, inject, type ComputedRef, type InjectionKey } from 'vue'
import { getBezierPath, Position, type EdgeProps } from '@vue-flow/core'
import { routeWorkbenchWire, type WireObstacles } from './edgeRouting'

export const wireObstaclesKey: InjectionKey<ComputedRef<WireObstacles>> = Symbol('workbench-wire-obstacles')

export function useWorkbenchWire(props: EdgeProps) {
  const obstacles = inject(wireObstaclesKey, null)
  return computed(() => {
    if (!obstacles || props.sourcePosition !== Position.Right || props.targetPosition !== Position.Left)
      return getBezierPath(props)[0]
    return routeWorkbenchWire({ x: props.sourceX, y: props.sourceY }, { x: props.targetX, y: props.targetY },
      props.source, props.target, props.id, obstacles.value)
  })
}
