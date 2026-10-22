import { apiClient } from './client';
import {
  InvestigationCreateResponse,
  InvestigationJob,
} from '../types/investigation';

export async function requestInvestigation(incidentId: string): Promise<InvestigationCreateResponse> {
  const response = await apiClient.post<InvestigationCreateResponse>(
    `/api/v1/incidents/${incidentId}/investigate`
  );
  return response.data;
}

export async function getInvestigation(jobId: string): Promise<InvestigationJob> {
  const response = await apiClient.get<InvestigationJob>(`/api/v1/investigations/${jobId}`);
  return response.data;
}

export async function listIncidentInvestigations(incidentId: string): Promise<InvestigationJob[]> {
  const response = await apiClient.get<InvestigationJob[]>(
    `/api/v1/incidents/${incidentId}/investigations`
  );
  return response.data;
}
