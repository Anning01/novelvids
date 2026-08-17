import { describe, expect, it } from 'vitest'
import { hasRoleAccess, resolveAuthGuard } from './routeGuard'

const route = (overrides: Record<string, unknown> = {}) => ({
  meta: {},
  ...overrides,
}) as never

const auth = (overrides: Record<string, unknown> = {}) => ({
  enabled: null,
  isLoggedIn: false,
  role: null,
  ...overrides,
}) as never

describe('hasRoleAccess', () => {
  it('allows everyone when no roles required', () => {
    expect(hasRoleAccess(null, undefined)).toBe(true)
    expect(hasRoleAccess('viewer', [])).toBe(true)
  })
  it('always allows super admin', () => {
    expect(hasRoleAccess('super', ['admin'])).toBe(true)
    expect(hasRoleAccess('super', ['viewer'])).toBe(true)
  })
  it('rejects when not logged in and roles required', () => {
    expect(hasRoleAccess(null, ['viewer'])).toBe(false)
  })
  it('orders viewer < creator < admin', () => {
    expect(hasRoleAccess('viewer', ['viewer'])).toBe(true)
    expect(hasRoleAccess('viewer', ['creator'])).toBe(false)
    expect(hasRoleAccess('creator', ['viewer'])).toBe(true)
    expect(hasRoleAccess('creator', ['admin'])).toBe(false)
    expect(hasRoleAccess('admin', ['admin'])).toBe(true)
    expect(hasRoleAccess('admin', ['creator'])).toBe(true)
  })
})

describe('resolveAuthGuard', () => {
  it('allows everything before bootstrap completes', () => {
    expect(resolveAuthGuard(route(), auth({ enabled: null, ready: false }))).toEqual({})
  })
  it('allows everything when auth is disabled (vanilla)', () => {
    expect(resolveAuthGuard(route(), auth({ enabled: false }))).toEqual({})
  })
  it('allows public pages when auth is enabled', () => {
    const decision = resolveAuthGuard(route({ meta: { public: true } }), auth({ enabled: true, isLoggedIn: false }))
    expect(decision).toEqual({})
  })
  it('redirects anonymous users to login', () => {
    const decision = resolveAuthGuard(route(), auth({ enabled: true, isLoggedIn: false }))
    expect(decision.redirect).toBe('/login')
  })
  it('allows logged-in users on open pages', () => {
    const decision = resolveAuthGuard(route(), auth({ enabled: true, isLoggedIn: true, role: 'viewer' }))
    expect(decision).toEqual({})
  })
  it('redirects to home when role is insufficient', () => {
    const decision = resolveAuthGuard(
      route({ meta: { roles: ['admin'] } }),
      auth({ enabled: true, isLoggedIn: true, role: 'viewer' }),
    )
    expect(decision.redirect).toBe('/')
  })
  it('allows team admin into settings routes', () => {
    const decision = resolveAuthGuard(
      route({ meta: { roles: ['admin'] } }),
      auth({ enabled: true, isLoggedIn: true, role: 'admin' }),
    )
    expect(decision).toEqual({})
  })
  it('reserves super-only routes for super admin', () => {
    const teamAdmin = resolveAuthGuard(
      route({ meta: { roles: ['admin'], superOnly: true } }),
      auth({ enabled: true, isLoggedIn: true, role: 'admin' }),
    )
    expect(teamAdmin.redirect).toBe('/')

    const superAdmin = resolveAuthGuard(
      route({ meta: { roles: ['admin'], superOnly: true } }),
      auth({ enabled: true, isLoggedIn: true, role: 'super' }),
    )
    expect(superAdmin).toEqual({})
  })
})
