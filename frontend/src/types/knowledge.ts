export interface KnowledgeDocument {
  id: string;
  title: string;
  source: string;
  service_name?: string | null;
  environment?: string | null;
  content_hash: string;
  chunk_count: number;
  created_at: string;
  updated_at: string;
  is_duplicate?: boolean;
}

export interface RetrievedChunk {
  chunk_id: string;
  document_id: string;
  document_title: string;
  source: string;
  service_name?: string | null;
  similarity_score: number;
  content: string;
}

export interface KnowledgeSearchPayload {
  query: string;
  top_k?: number;
  min_similarity?: number;
  service_name?: string;
}

export interface KnowledgeIngestPayload {
  title: string;
  content: string;
  source?: string;
  service_name?: string;
  environment?: string;
}
