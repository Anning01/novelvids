export interface ThemeRouteSnapshot {
  name?: string | symbol | null
  path: string
  view?: unknown
}

export function isWorkflowThemeSurface(route: ThemeRouteSnapshot) {
  return (
    (route.name === 'short-drama-storyboard' && route.view === 'workflow')
    || /^\/novel\/\d+\/chapter\/\d+\/step\/\d+$/.test(route.path)
  )
}
