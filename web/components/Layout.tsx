import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  BookOpen, MonitorPlay, Settings, ChevronLeft, ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'

const navItems = [
  { path: '/', icon: BookOpen, label: '项目管理', match: (p: string) => p === '/' || p.startsWith('/novel') },
  { path: '/videos', icon: MonitorPlay, label: '视频库', match: (p: string) => p.startsWith('/videos') },
  { path: '/config', icon: Settings, label: '模型配置', match: (p: string) => p.startsWith('/config') },
]

export const Layout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation()
  const path = location.pathname
  const [collapsed, setCollapsed] = React.useState(false)

  return (
    <div className="grain flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className={cn(
          "glass flex flex-col transition-all duration-300 flex-shrink-0 relative z-20",
          collapsed ? "w-[68px]" : "w-60"
        )}
      >
        {/* Brand */}
        <div className="h-16 flex items-center gap-3 px-4 flex-shrink-0">
          <div className="relative flex-shrink-0">
            <img src="/logo.png" alt="猫影短剧" className="w-9 h-9 rounded-xl object-contain bg-transparent" />
            <div className="absolute inset-0 rounded-xl bg-primary/30 blur-md -z-10" />
          </div>
          {!collapsed && (
            <span className="gradient-text text-xl font-extrabold tracking-tight truncate">
              猫影短剧
            </span>
          )}
        </div>

        {/* Decorative line under brand */}
        <div className="mx-4 decorative-line" />

        {/* Nav */}
        <nav className="flex-1 p-3 space-y-1 mt-2">
          {navItems.map(item => {
            const active = item.match(path)
            return (
              <Link to={item.path} key={item.path}>
                <div
                  className={cn(
                    "flex items-center gap-3 px-3 py-2.5 rounded-lg transition-all duration-200 group relative overflow-hidden",
                    active
                      ? "bg-primary/10 text-primary border border-primary/20 shadow-sm shadow-primary/10"
                      : "text-sidebar-foreground hover:bg-white/[0.04] hover:text-foreground border border-transparent"
                  )}
                >
                  {active && (
                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-primary rounded-r-full" />
                  )}
                  <item.icon className={cn("w-5 h-5 flex-shrink-0 transition-colors", active && "text-primary")} />
                  {!collapsed && (
                    <span className="text-sm font-medium truncate">{item.label}</span>
                  )}
                </div>
              </Link>
            )
          })}
        </nav>

        {/* Collapse Toggle */}
        <div className="p-3">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="w-full flex items-center justify-center p-2 rounded-lg text-sidebar-foreground hover:bg-white/[0.06] hover:text-foreground transition-all"
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-auto bg-background relative">
        {/* Atmospheric background orbs */}
        <div className="glow-orb glow-orb-primary w-[500px] h-[500px] -top-40 -right-40" />
        <div className="glow-orb glow-orb-accent w-[300px] h-[300px] top-1/2 -left-20" />

        {/* Subtle top gradient */}
        <div className="absolute top-0 left-0 w-full h-96 bg-gradient-to-b from-primary/[0.04] to-transparent pointer-events-none" />

        <div className="relative z-10 h-full">
          {children}
        </div>
      </main>
    </div>
  )
}
