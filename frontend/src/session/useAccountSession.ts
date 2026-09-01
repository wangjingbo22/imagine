import { useContext } from 'react'
import { AccountSessionContext, type AccountSessionValue } from './AccountSessionContext'

export function useAccountSession(): AccountSessionValue {
  const session = useContext(AccountSessionContext)
  if (!session) {
    throw new Error('useAccountSession must be used inside AccountSessionProvider')
  }
  return session
}
