import { ArrowLeft, CircleHelp, SlidersHorizontal, UserRound } from 'lucide-react'
import type { PropsWithChildren } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { BrandMark } from './BrandMark'

interface AppShellProps extends PropsWithChildren {
  compact?: boolean
}

export function AppShell({ children, compact = false }: AppShellProps) {
  const location = useLocation()
  const isHome = location.pathname === '/'

  return (
    <div className={compact ? 'app-shell app-shell--compact' : 'app-shell'}>
      <header className="topbar">
        <div className="topbar__inner">
          {isHome ? (
            <BrandMark />
          ) : (
            <Link className="topbar__back" to="/">
              <ArrowLeft size={18} />
              <BrandMark />
            </Link>
          )}
          <nav className="topbar__nav" aria-label="主导航">
            <span className="topbar__status">
              <span className="status-dot" />
              Agent 在线
            </span>
            <button className="icon-button" type="button" aria-label="帮助">
              <CircleHelp size={19} />
            </button>
            <Link className="icon-button" to="/model-settings" aria-label="模型设置" title="模型设置"><SlidersHorizontal size={18} /></Link>
            <Link className="avatar" to="/account" aria-label="账户" title="账户">
              <UserRound size={16} />
            </Link>
          </nav>
        </div>
      </header>
      {children}
    </div>
  )
}
