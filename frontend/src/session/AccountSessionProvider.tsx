import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type PropsWithChildren,
} from 'react'
import { getCurrentUser, logoutAccount } from '../api/accountApi'
import { ApiError } from '../api/client'
import type { CurrentUser } from '../domain/account'
import { clearAccountBoundParentTripMemberSessions } from '../services/parentTripCollaboration'
import { clearUserLlmSettings } from '../services/userLlmSettings'
import { AccountSessionContext, type AccountSessionValue } from './AccountSessionContext'

function isSessionRequired(error: unknown): boolean {
  return error instanceof ApiError && (
    error.code === 'ACCOUNT_SESSION_REQUIRED' || error.status === 401
  )
}

function sessionErrorMessage(error: unknown): string {
  return error instanceof Error && error.message
    ? error.message
    : '账户状态读取失败，请刷新重试'
}

function clearAccountSessionArtifacts(): void {
  try {
    clearUserLlmSettings()
  } catch {
    // Storage may be unavailable, but a successful server logout must still clear memory.
  }
  clearAccountBoundParentTripMemberSessions()
}

export function AccountSessionProvider({ children }: PropsWithChildren) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [isInitializing, setIsInitializing] = useState(true)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const sessionVersionRef = useRef(0)
  const hasLoadedRef = useRef(false)

  const setCurrentUser = useCallback((nextUser: CurrentUser) => {
    sessionVersionRef.current += 1
    setUser(nextUser)
    setSessionError(null)
    setIsInitializing(false)
  }, [])

  const clearCurrentUser = useCallback(() => {
    sessionVersionRef.current += 1
    setUser(null)
    setSessionError(null)
    setIsInitializing(false)
    clearAccountSessionArtifacts()
  }, [])

  const refreshCurrentUser = useCallback(async () => {
    const requestVersion = ++sessionVersionRef.current
    setSessionError(null)
    setIsInitializing(true)

    try {
      const { data } = await getCurrentUser()
      if (requestVersion !== sessionVersionRef.current) return
      setUser(data)
    } catch (caught) {
      if (requestVersion !== sessionVersionRef.current) return
      if (isSessionRequired(caught)) {
        clearCurrentUser()
        return
      }
      setSessionError(sessionErrorMessage(caught))
    } finally {
      if (requestVersion === sessionVersionRef.current) {
        setIsInitializing(false)
      }
    }
  }, [clearCurrentUser])

  const logout = useCallback(async () => {
    await logoutAccount()
    clearCurrentUser()
  }, [clearCurrentUser])

  useEffect(() => {
    if (hasLoadedRef.current) return
    hasLoadedRef.current = true
    void refreshCurrentUser()
  }, [refreshCurrentUser])

  const value = useMemo<AccountSessionValue>(() => ({
    user,
    isInitializing,
    sessionError,
    refreshCurrentUser,
    setCurrentUser,
    logout,
  }), [isInitializing, logout, refreshCurrentUser, sessionError, setCurrentUser, user])

  return <AccountSessionContext.Provider value={value}>{children}</AccountSessionContext.Provider>
}
