export interface HealthResponse {
  status: string;
  service?: string;
}

export interface DbHealthResponse {
  status: string;
  database: string;
}

export interface ReadinessResponse {
  status: 'ready' | 'unhealthy' | string;
  database: 'healthy' | 'unreachable' | string;
  redis: 'healthy' | 'unreachable' | string;
}

export interface MetricsSnapshot {
  uptime_seconds: number;
  total_requests: number;
  total_errors_4xx: number;
  total_errors_5xx: number;
  error_rate_pct: number;
  avg_latency_ms: number;
  status_counts: Record<string, number>;
}
