# NovelVids Studio Frontend

Vue 3 + TypeScript frontend for NovelVids. The chapter creation workspace uses
Vue Flow and shares the interaction architecture of the Shengshi Media infinite
canvas: pan/select modes, minimap, zoom controls, layered auto-layout, node
selection tools, copy/paste, undo/redo, pinning, collapsing, markers, and
viewport persistence.

## Development

```bash
npm install
npm run dev
```

The development server runs at `http://localhost:3000` and proxies `/api` and
`/media` to `http://127.0.0.1:8000`.

## Checks

```bash
npm run typecheck
npm run build
```
