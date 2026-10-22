import { apiClient } from './client';
import {
  Incident,
  IncidentCreatePayload,
  IncidentFilterParams,
  IncidentListResponse,
  IncidentStatusUpdatePayload,
} from '../types/incident';
import { TelemetryEvent } from '../types/event';

export async function getIncidents(params?: IncidentFilterParams): Promise<IncidentListResponse> {
  const cleanParams: Record<string, unknown> = {};
  if (params) {
    Object.entries(params).forEach(([key, val]) => {
      if (val !== '' && val !== null && val !== undefined) {
        cleanParams[key] = val;
      }
    });
  }
  const response = await apiClient.get<IncidentListResponse>('/api/v1/incidents', { params: cleanParams });
  return response.data;
}

export async function getIncident(id: string): Promise<Incident> {
  const response = await apiClient.get<Incident>(`/api/v1/incidents/${id}`);
  return response.data;
}

export async function createIncident(payload: IncidentCreatePayload): Promise<Incident> {
  const response = await apiClient.post<Incident>('/api/v1/incidents', payload);
  return response.data;
}

export async function updateIncidentStatus(
  id: string,
  payload: IncidentStatusUpdatePayload
): Promise<Incident> {
  const response = await apiClient.patch<Incident>(`/api/v1/incidents/${id}/status`, payload);
  return response.data;
}

export async function deleteIncident(id: string): Promise<{ success: boolean; id: string }> {
  const response = await apiClient.delete<{ success: boolean; id: string }>(`/api/v1/incidents/${id}`);
  return response.data;
}

export async function getIncidentEvents(
  id: string,
  limit: number = 20,
  offset: number = 0
): Promise<{ items: TelemetryEvent[]; total: number; limit: number; offset: number }> {
  const response = await apiClient.get<{ items: TelemetryEvent[]; total: number; limit: number; offset: number }>(
    `/api/v1/incidents/${id}/events`,
    { params: { limit, offset } }
  );
  return response.data;
}
