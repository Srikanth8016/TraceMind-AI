import { apiClient } from './client';
import {
  DbHealthResponse,
  HealthResponse,
  MetricsSnapshot,
  ReadinessResponse,
} from '../types/ops';

export async function getHealth(): Promise<HealthResponse> {
  const response = await apiClient.get<HealthResponse>('/health');
  return response.data;
}

export async function getDbHealth(): Promise<DbHealthResponse> {
  const response = await apiClient.get<DbHealthResponse>('/health/db');
  return response.data;
}

export async function getReadiness(): Promise<ReadinessResponse> {
  const response = await apiClient.get<ReadinessResponse>('/ready', {
    validateStatus: (status) => status < 600,
  });
  return response.data;
}

export async function getMetrics(): Promise<MetricsSnapshot> {
  const response = await apiClient.get<MetricsSnapshot>('/metrics');
  return response.data;
}
