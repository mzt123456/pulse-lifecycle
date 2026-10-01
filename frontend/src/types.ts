export interface ApiEnvelope<T = unknown> {
  code: number
  message: string
  data: T
}

export interface UserInfo {
  id: number
  username: string
  real_name: string | null
  department: string | null
  roles: string[]
  permissions: string[]
}

export interface TokenPayload {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user: UserInfo
}
