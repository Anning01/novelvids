import { Blob as NativeBlob } from 'node:buffer'
import { afterEach, expect, it, vi } from 'vitest'
import { request } from '@/api'
import { saveWorkbenchViewport } from '../workbench/viewport/workbenchViewportPersistence'
import { ProjectZip } from './projectZip'
import { exportProject } from './transfer'

vi.mock('@/api', async original => ({ ...await original<typeof import('@/api')>(), request: vi.fn() }))
afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

it('exports the latest viewport for edited, imported and view-only chapters, preserving the planned nodes and media', async () => {
  vi.stubGlobal('Blob', NativeBlob)
  const original = { version: 2, viewport: { x: 0, y: 0, zoom: 1 }, canvasSize: { width: 0, height: 0 }, nodes: {}, manualNodes: [], manualEdges: [] }
  const edited = { ...original, nodes: { note: { position: { x: 10, y: 50 } } } }
  const imported = { ...original, manualNodes: [{ kind: 'image_media', data: { url: 'novelvids:media/1.png' } }] }
  const size = { width: 900, height: 600 }
  const view = { x: -90, y: 30, zoom: 0.5 }
  for (const id of [1, 2, 3]) saveWorkbenchViewport(String(id), view, size)
  // Older personal view records lack canvas dimensions; keep the original archived viewport.
  localStorage.setItem('novel-workbench:viewport:v1:4', JSON.stringify({ centerX: 20, centerY: 20, zoom: 1 }))
  localStorage.setItem('novelvids:canvas:1:layout:v2', JSON.stringify(edited))
  const project = { chapters: [1, 2, 3, 4, 5].map(id => ({ id })), canvases: { '1': edited, '2': imported, '4': original } }
  vi.mocked(request).mockResolvedValue({ data: { project, files: [] } })
  const add = vi.spyOn(ProjectZip.prototype, 'add').mockResolvedValue({ member: 'project.json', byte_length: 0, sha256: '', hash_scheme: 'sha256-blocks-8m' })
  await exportProject(1, new AbortController().signal)
  const manifest = JSON.parse(await add.mock.calls[0]![1].text())
  expect(manifest.project.canvases).toEqual({
    '1': { ...edited, viewport: view, canvasSize: size },
    '2': { ...imported, viewport: view, canvasSize: size },
    '3': { ...original, viewport: view, canvasSize: size },
    '4': original,
  })
})
