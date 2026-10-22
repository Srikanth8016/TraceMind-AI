export interface TelemetryEvent {
  id: string;
  service_name: string;
  environment: string;
  level: string;
  message: string;
  timestamp: string;
  created_at: string;
  incident_id?: string | null;
}

export interface EventListResponse {
  items: TelemetryEvent[];
  limit: number;
  offset: number;
  total: number;
}

export interface EventFilterParams {
  service_name?: string;
  environment?: string;
  level?: string;
  limit?: number;
  offset?: number;
}

export interface EventCreatePayload {
  service_name: string;
  environment: string;
  level: string;
  message: string;
  timestamp: string;
}

export interface EventIngestResponse {
  message: string;
  event_id: string;
  job_id: string;
  status: string;
}
