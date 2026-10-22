export type IncidentSeverity = 'CRITICAL' | 'ERROR' | 'HIGH' | 'MEDIUM' | 'LOW' | 'WARNING' | 'INFO';

export type IncidentStatus = 'OPEN' | 'INVESTIGATING' | 'ACKNOWLEDGED' | 'RESOLVED' | 'CLOSED';

export interface Incident {
  id: string;
  service_name: string;
  environment: string;
  fingerprint: string;
  title: string;
  severity: IncidentSeverity | string;
  status: IncidentStatus;
  first_seen_at: string;
  last_seen_at: string;
  event_count: number;
  owner_id?: string | null;
  created_at: string;
  updated_at: string;
}

export interface IncidentListResponse {
  items: Incident[];
  limit: number;
  offset: number;
  total: number;
}

export interface IncidentFilterParams {
  skip?: number;
  limit?: number;
  service_name?: string;
  environment?: string;
  severity?: string;
  status?: string;
  search?: string;
  sort_by?: string;
  order?: 'asc' | 'desc';
}

export interface IncidentCreatePayload {
  title: string;
  description?: string;
  service_name: string;
  environment: string;
  severity: string;
  status?: IncidentStatus;
}

export interface IncidentStatusUpdatePayload {
  status: IncidentStatus;
}
