export type ConfidenceLevel = 'HIGH' | 'MEDIUM' | 'LOW';
export type InvestigationStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'FAILED';

export interface RootCauseHypothesis {
  hypothesis: string;
  confidence: ConfidenceLevel;
  evidence_references: string[];
  reasoning: string;
}

export interface RecommendedAction {
  action: string;
  priority: 'P1' | 'P2' | 'P3' | string;
  rationale: string;
}

export interface RetrievedRunbookRef {
  chunk_id: string;
  document_title: string;
  similarity_score: number;
  snippet: string;
}

export interface InvestigationReport {
  executive_summary: string;
  hypotheses: RootCauseHypothesis[];
  recommended_actions: RecommendedAction[];
  retrieved_runbooks: RetrievedRunbookRef[];
  missing_evidence: string[];
  limitations: string[];
}

export interface InvestigationJob {
  id: string;
  incident_id: string;
  status: InvestigationStatus;
  attempt_count: number;
  error_message?: string | null;
  report?: InvestigationReport | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface InvestigationCreateResponse {
  id: string;
  incident_id: string;
  status: InvestigationStatus;
  message: string;
}
