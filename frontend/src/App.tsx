import { Component, useEffect, type ErrorInfo, type ReactNode } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useLocation } from 'react-router-dom'
import { AgentProcessPage } from './pages/AgentProcessPage'
import { HomePage } from './pages/HomePage'
import { ConversationPlannerPage } from './pages/ConversationPlannerPage'
import { MemberConversationPage } from './pages/MemberConversationPage'
import { RecommendationPage } from './pages/RecommendationPage'
import { WorkspacePage } from './pages/WorkspacePage'
import { ParentTripPage } from './pages/ParentTripPage'
import { AccountPage } from './pages/AccountPage'
import { ParentTripMemberPage } from './pages/ParentTripMemberPage'
import { BudgetLedgerPage } from './pages/BudgetLedgerPage'
import { ModelSettingsPage } from './pages/ModelSettingsPage'
import { useAccountSession } from './session/useAccountSession'

function RequireAccount({ children }: { children: ReactNode }) {
  const location = useLocation()
  const { user, isInitializing } = useAccountSession()

  if (isInitializing) return null
  if (user) return children
  const returnTo = `${location.pathname}${location.search}`
  return <Navigate replace to={`/account?returnTo=${encodeURIComponent(returnTo)}`} />
}

function MotionController() {
  const location = useLocation()

  useEffect(() => {
    let observer: IntersectionObserver | undefined
    let mutationObserver: MutationObserver | undefined
    const frameId = window.requestAnimationFrame(() => {
      const observedItems = new WeakSet<HTMLElement>()
      let revealIndex = 0
      observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              entry.target.classList.add('is-revealed')
              observer?.unobserve(entry.target)
            }
          })
        },
        { threshold: 0.12, rootMargin: '0px 0px -6% 0px' },
      )

      const observeItem = (item: HTMLElement) => {
        if (observedItems.has(item) || item.classList.contains('is-revealed')) return
        observedItems.add(item)
        item.style.setProperty('--reveal-delay', `${Math.min(revealIndex * 65, 260)}ms`)
        revealIndex += 1
        observer?.observe(item)
      }
      const observeTree = (node: Node) => {
        if (!(node instanceof Element)) return
        if (node instanceof HTMLElement && node.matches('[data-reveal]')) observeItem(node)
        node.querySelectorAll<HTMLElement>('[data-reveal]').forEach(observeItem)
      }

      document.querySelectorAll<HTMLElement>('[data-reveal]').forEach(observeItem)
      mutationObserver = new MutationObserver((records) => {
        records.forEach((record) => record.addedNodes.forEach(observeTree))
      })
      mutationObserver.observe(document.body, { childList: true, subtree: true })
    })

    return () => {
      window.cancelAnimationFrame(frameId)
      mutationObserver?.disconnect()
      observer?.disconnect()
    }
  }, [location.pathname])

  return null
}

class MemberPageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('member conversation render failed', error, info.componentStack)
  }

  render() {
    if (this.state.failed) {
      return <main className="member-render-error" role="alert"><h1>成员页面加载失败</h1><p>请重新打开成员邀请链接；同一链接可以重复使用。</p><a className="button button--soft" href="/plan">返回行程创建页</a></main>
    }
    return this.props.children
  }
}

function App() {
  return (
    <>
      <MotionController />
      <Routes>
        <Route path="/" element={<RequireAccount><HomePage /></RequireAccount>} />
        <Route path="/plan" element={<RequireAccount><ConversationPlannerPage /></RequireAccount>} />
        <Route path="/join" element={<MemberPageErrorBoundary><MemberConversationPage /></MemberPageErrorBoundary>} />
        <Route path="/join/:token" element={<MemberPageErrorBoundary><MemberConversationPage /></MemberPageErrorBoundary>} />
        <Route path="/recommendation/:tripId" element={<RequireAccount><RecommendationPage /></RequireAccount>} />
        <Route path="/generating" element={<RequireAccount><AgentProcessPage /></RequireAccount>} />
        <Route path="/workspace" element={<RequireAccount><WorkspacePage /></RequireAccount>} />
        <Route path="/parent-trips/new" element={<RequireAccount><ParentTripPage /></RequireAccount>} />
        <Route path="/parent-join" element={<ParentTripMemberPage />} />
        <Route path="/parent-join/:token" element={<ParentTripMemberPage />} />
        <Route path="/parent-trips/:parentTripId/member" element={<ParentTripMemberPage />} />
        <Route path="/parent-trips/:parentTripId" element={<RequireAccount><ParentTripPage /></RequireAccount>} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/model-settings" element={<RequireAccount><ModelSettingsPage /></RequireAccount>} />
        <Route path="/budget-ledger" element={<RequireAccount><BudgetLedgerPage /></RequireAccount>} />
        <Route path="*" element={<Navigate to="/account" replace />} />
      </Routes>
    </>
  )
}

export default App
