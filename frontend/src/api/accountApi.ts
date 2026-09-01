import type {
  CurrentUser,
  LoginInput,
  LogoutResult,
  ProfileUpdateInput,
  RegisterInput,
} from '../domain/account'
import { request } from './client'

export function registerAccount(input: RegisterInput) {
  return request<CurrentUser>('/api/v1/account/register', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function loginAccount(input: LoginInput) {
  return request<CurrentUser>('/api/v1/account/login', {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function logoutAccount() {
  return request<LogoutResult>('/api/v1/account/logout', {
    method: 'POST',
  })
}

export function getCurrentUser() {
  return request<CurrentUser>('/api/v1/account/me')
}

export function updateAccountProfile(input: ProfileUpdateInput) {
  return request<CurrentUser>('/api/v1/account/me/profile', {
    method: 'PUT',
    body: JSON.stringify(input),
  })
}
