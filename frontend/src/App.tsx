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

function MotionController() {
  const location = useLocation()

  useEffect(() => {
    let observer: IntersectionObserver | undefined
    const frameId = window.requestAnimationFrame(() => {
      const revealItems = document.querySelectorAll<HTMLElement>('[data-reveal]')
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

      revealItems.forEach((item, index) => {
        item.style.setProperty('--reveal-delay', `${Math.min(index * 65, 260)}ms`)
        observer?.observe(item)
      })
    })

    return () => {
      window.cancelAnimationFrame(frameId)
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
        <Route path="/" element={<HomePage />} />
        <Route path="/plan" element={<ConversationPlannerPage />} />
        <Route path="/join" element={<MemberPageErrorBoundary><MemberConversationPage /></MemberPageErrorBoundary>} />
        <Route path="/join/:token" element={<MemberPageErrorBoundary><MemberConversationPage /></MemberPageErrorBoundary>} />
        <Route path="/recommendation/:tripId" element={<RecommendationPage />} />
        <Route path="/generating" element={<AgentProcessPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="/parent-trips/new" element={<ParentTripPage />} />
        <Route path="/parent-join" element={<ParentTripMemberPage />} />
        <Route path="/parent-join/:token" element={<ParentTripMemberPage />} />
        <Route path="/parent-trips/:parentTripId/member" element={<ParentTripMemberPage />} />
        <Route path="/parent-trips/:parentTripId" element={<ParentTripPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/budget-ledger" element={<BudgetLedgerPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}

export default App
