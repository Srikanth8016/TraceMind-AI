import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

// Base URL: reads from VITE_API_URL or defaults to empty string (using Vite proxy in dev)
const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 15000,
});

// Helper to generate compliant request ID (^[a-zA-Z0-9_\-\.]{1,64}$)
function generateRequestId(): string {
  return 'req-' + Math.random().toString(36).substring(2, 10) + '-' + Date.now().toString(36);
}

// Request interceptor: inject token, X-API-Key, and X-Request-ID
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    // 1. JWT Bearer token from localStorage
    const token = localStorage.getItem('tracemind_token');
    if (token && config.headers) {
      config.headers['Authorization'] = `Bearer ${token}`;
    }

    // 2. Default API Key if configured (required for /api/v1/events, /api/v1/investigations, /api/v1/knowledge)
    const apiKey = import.meta.env.VITE_TRACEMIND_API_KEY || localStorage.getItem('tracemind_api_key') || 'local-dev-api-key-tracemind-32bytes';
    if (apiKey && config.headers && !config.headers['X-API-Key']) {
      config.headers['X-API-Key'] = apiKey;
    }

    // 3. Traceability Request ID
    if (config.headers && !config.headers['X-Request-ID']) {
      config.headers['X-Request-ID'] = generateRequestId();
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// Response interceptor: handle 401 Unauthorized safely
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response && error.response.status === 401) {
      // Token is invalid or expired
      const isAuthEndpoint = error.config?.url?.includes('/auth/login') || error.config?.url?.includes('/auth/register');
      if (!isAuthEndpoint) {
        localStorage.removeItem('tracemind_token');
        // Dispatch custom event so AuthContext can handle logout without page hard reload
        window.dispatchEvent(new Event('tracemind:unauthorized'));
      }
    }
    return Promise.reject(error);
  }
);

export function getErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data;
    if (data && typeof data === 'object') {
      if ('detail' in data && typeof data.detail === 'string') {
        return data.detail;
      }
      if ('detail' in data && Array.isArray(data.detail)) {
        // Pydantic validation error array
        return data.detail.map((err: { msg?: string; loc?: string[] }) => err.msg || JSON.stringify(err)).join(', ');
      }
      if ('message' in data && typeof data.message === 'string') {
        return data.message;
      }
    }
    return error.message || 'Network request failed';
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'An unexpected error occurred';
}
