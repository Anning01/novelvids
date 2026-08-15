const EXCLUSIVE_POPOVER_OPEN_EVENT = 'novelvids:exclusive-popover-open'

export function claimExclusivePopover(source: symbol, close: () => void) {
  const closeForCompetingPopover = (event: Event) => {
    if ((event as CustomEvent<symbol>).detail !== source) close()
  }

  window.dispatchEvent(new CustomEvent<symbol>(EXCLUSIVE_POPOVER_OPEN_EVENT, { detail: source }))
  window.addEventListener(EXCLUSIVE_POPOVER_OPEN_EVENT, closeForCompetingPopover)

  return () => window.removeEventListener(EXCLUSIVE_POPOVER_OPEN_EVENT, closeForCompetingPopover)
}
