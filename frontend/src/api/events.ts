import { apiClient } from './client';
import {
  EventCreatePayload,
  EventFilterParams,
  EventIngestResponse,
  EventListResponse,
  TelemetryEvent,
} from '../types/event';

export async function getEvents(params?: EventFilterParams): Promise<EventListResponse> {
  const cleanParams: Record<string, unknown> = {};
  if (params) {
    Object.entries(params).forEach(([key, val]) => {
      if (val !== '' && val !== null && val !== undefined) {
        cleanParams[key] = val;
      }
    });
  }
  const response = await apiClient.get<EventListResponse>('/api/v1/events', { params: cleanParams });
  return response.data;
}

export async function getEvent(id: string): Promise<TelemetryEvent> {
  const response = await apiClient.get<TelemetryEvent>(`/api/v1/events/${id}`);
  return response.data;
}

export async function ingestEvent(payload: EventCreatePayload): Promise<EventIngestResponse> {
  const response = await apiClient.post<EventIngestResponse>('/api/v1/events', payload);
  return response.data;
}
