import { expect, it } from 'vitest'
import { focusToViewport, viewportToFocus } from './workbenchViewportPersistence'

it('preserves the flow-space center when the canvas resizes', () => {
  const focus = viewportToFocus(
    { x: -200, y: -100, zoom: 0.5 },
    { width: 1200, height: 800 },
  )
  const resized = focusToViewport(focus, { width: 1600, height: 900 })

  expect(viewportToFocus(resized, { width: 1600, height: 900 })).toEqual(focus)
})
