import React from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  BookOpen, MonitorPlay, Settings, ChevronLeft, ChevronRight, Sparkles,
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
    <div className="app-shell flex h-screen overflow-hidden">
      {/* Sidebar */}
      <aside
        className={cn(
          "app-sidebar flex flex-col transition-all duration-300 flex-shrink-0 relative z-20",
          collapsed ? "w-[72px]" : "w-[232px]"
        )}
      >
        {/* Brand */}
        <div className="h-[72px] flex items-center gap-3 px-[18px] flex-shrink-0">
          <div className="app-brand-mark">
            <Sparkles className="h-[18px] w-[18px]" />
          </div>
          {!collapsed && (
            <span className="app-brand-copy"><strong>猫影</strong><small>NOVEL STUDIO</small></span>
          )}
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-2 space-y-1">
          {!collapsed && <p className="app-nav-label">创作空间</p>}
          {navItems.map(item => {
            const active = item.match(path)
            return (
              <Link to={item.path} key={item.path}>
                <div
                  className={cn(
                    "app-nav-item",
                    active
                      ? "is-active"
                      : ""
                  )}
                >
                  <item.icon className="w-[18px] h-[18px] flex-shrink-0" />
                  {!collapsed && (
                    <span className="text-sm font-medium truncate">{item.label}</span>
                  )}
                </div>
              </Link>
            )
          })}
        </nav>

        {/* Collapse Toggle */}
        <div className="p-3 border-t border-white/[0.05]">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="app-sidebar-toggle"
            aria-label={collapsed ? '展开侧边栏' : '收起侧边栏'}
          >
            {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="min-w-0 flex-1 overflow-auto bg-background relative">
        <div className="relative h-full">{children}</div>
      </main>
    </div>
  )
}
