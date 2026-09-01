export interface CurrentUser {
  userId: string
  email: string
  displayName: string
  homeCity: string | null
  interests: string[]
}

export interface ModelSettingsView { configured: boolean; model: string | null; keyHint: string | null }

export interface RegisterInput {
  email: string
  password: string
  displayName: string
}

export interface LoginInput {
  email: string
  password: string
}

export interface ProfileUpdateInput {
  displayName: string
  homeCity: string | null
  interests: string[]
}

export interface LogoutResult {
  loggedOut: true
}
