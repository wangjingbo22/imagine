import { createContext } from 'react'
import type { CurrentUser } from '../domain/account'

export interface AccountSessionValue {
  user: CurrentUser | null
  isInitializing: boolean
  sessionError: string | null
  refreshCurrentUser: () => Promise<void>
  setCurrentUser: (user: CurrentUser) => void
  logout: () => Promise<void>
}

export const AccountSessionContext = createContext<AccountSessionValue | null>(null)
