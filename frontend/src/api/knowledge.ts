import { apiClient } from './client';
import {
  KnowledgeDocument,
  KnowledgeIngestPayload,
  KnowledgeSearchPayload,
  RetrievedChunk,
} from '../types/knowledge';

export async function listRunbooks(
  limit: number = 50,
  offset: number = 0,
  serviceName?: string
): Promise<KnowledgeDocument[]> {
  const params: Record<string, unknown> = { limit, offset };
  if (serviceName) params.service_name = serviceName;
  const response = await apiClient.get<KnowledgeDocument[]>('/api/v1/runbooks', { params });
  return response.data;
}

export async function getRunbook(id: string): Promise<KnowledgeDocument> {
  const response = await apiClient.get<KnowledgeDocument>(`/api/v1/runbooks/${id}`);
  return response.data;
}

export async function ingestRunbookJson(payload: KnowledgeIngestPayload): Promise<KnowledgeDocument> {
  const response = await apiClient.post<KnowledgeDocument>('/api/v1/runbooks', payload);
  return response.data;
}

export async function uploadRunbookFile(
  file: File,
  title?: string,
  serviceName?: string,
  environment?: string
): Promise<KnowledgeDocument> {
  const formData = new FormData();
  formData.append('file', file);
  if (title) formData.append('title', title);
  if (serviceName) formData.append('service_name', serviceName);
  if (environment) formData.append('environment', environment);

  const response = await apiClient.post<KnowledgeDocument>('/api/v1/runbooks/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  });
  return response.data;
}

export async function searchKnowledge(payload: KnowledgeSearchPayload): Promise<RetrievedChunk[]> {
  const response = await apiClient.post<RetrievedChunk[]>('/api/v1/knowledge/search', payload);
  return response.data;
}
