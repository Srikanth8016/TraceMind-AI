import { apiClient } from './client';
import { LoginPayload, RegisterPayload, TokenResponse, UserResponse } from '../types/auth';

export async function login(payload: LoginPayload): Promise<TokenResponse> {
  const response = await apiClient.post<TokenResponse>('/auth/login', payload);
  return response.data;
}

export async function register(payload: RegisterPayload): Promise<UserResponse> {
  const response = await apiClient.post<UserResponse>('/auth/register', payload);
  return response.data;
}

export async function getMe(): Promise<UserResponse> {
  const response = await apiClient.get<UserResponse>('/auth/me');
  return response.data;
}
