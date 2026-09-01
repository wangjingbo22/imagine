import { ArrowLeft, SlidersHorizontal, UserRound } from 'lucide-react'
import type { PropsWithChildren } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAccountSession } from '../session/useAccountSession'
import { userFacingErrorMessage } from '../utils/userFacingError'
import { BrandMark } from './BrandMark'

interface AppShellProps extends PropsWithChildren {
  compact?: boolean
  showBackButton?: boolean
}

export function AppShell({
  children,
  compact = false,
  showBackButton = true,
}: AppShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const isHome = location.pathname === '/'
  const { user, isInitializing, sessionError } = useAccountSession()
  const modelSettingsPath = user ? '/model-settings' : '/account?returnTo=%2Fmodel-settings'
  const currentPath = `${location.pathname}${location.search}`
  const accountPath = location.pathname.startsWith('/recommendation/') || location.pathname === '/plan'
    ? `/account?returnTo=${encodeURIComponent(currentPath)}`
    : '/account'

  /**
   * 返回按钮应恢复用户刚才所在的业务页面，而不是把所有流程都强制送回首页。
   * 浏览器没有站内历史（例如用户直接粘贴邀请链接打开）时，才退回首页，避免
   * `navigate(-1)` 把用户带到站外页面或产生看起来“没有反应”的空历史返回。
   */
  const goBack = () => {
    const hasInAppHistory = window.history.length > 1 && location.key !== 'default'
    if (hasInAppHistory) {
      navigate(-1)
      return
    }
    navigate('/', { replace: true })
  }

  return (
    <div className={compact ? 'app-shell app-shell--compact' : 'app-shell'}>
      <header className="topbar">
        <div className="topbar__inner">
          {isHome || !showBackButton ? (
            <BrandMark />
          ) : (
            <button
              aria-label="返回上一个页面"
              className="topbar__back"
              onClick={goBack}
              title="返回上一个页面"
              type="button"
            >
              <ArrowLeft size={18} />
              <BrandMark />
            </button>
          )}
          <nav className="topbar__nav" aria-label="主导航">
            {!sessionError && (
              <span className="topbar__status">
                <span className="status-dot" />
                {isInitializing ? '正在读取账户' : user ? `你好，${user.displayName}` : '请登录'}
              </span>
            )}
            <Link className="topbar__model-link" to={modelSettingsPath} aria-label="绑定模型" title="绑定模型"><SlidersHorizontal size={21} /><span>绑定模型</span></Link>
            <Link className="avatar" to={accountPath} aria-label={user ? `${user.displayName}的账户` : '账户'} title={user?.displayName ?? '账户'}>
              {user ? user.displayName.slice(0, 1).toUpperCase() : <UserRound size={21} />}
            </Link>
          </nav>
        </div>
      </header>
      {sessionError && (
        <div className="app-shell__session-error" role="alert">
          <div>{userFacingErrorMessage(sessionError, '账户状态读取失败，请刷新重试。')}</div>
        </div>
      )}
      {children}
    </div>
  )
}
