import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useLocation } from 'react-router-dom'
import { AgentProcessPage } from './pages/AgentProcessPage'
import { HomePage } from './pages/HomePage'
import { ConversationPlannerPage } from './pages/ConversationPlannerPage'
import { MemberConversationPage } from './pages/MemberConversationPage'
import { RecommendationPage } from './pages/RecommendationPage'
import { WorkspacePage } from './pages/WorkspacePage'

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

function App() {
  return (
    <>
      <MotionController />
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/plan" element={<ConversationPlannerPage />} />
        <Route path="/join" element={<MemberConversationPage />} />
        <Route path="/join/:token" element={<MemberConversationPage />} />
        <Route path="/recommendation/:tripId" element={<RecommendationPage />} />
        <Route path="/generating" element={<AgentProcessPage />} />
        <Route path="/workspace" element={<WorkspacePage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}

export default App
