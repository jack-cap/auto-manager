/**
 * API response and error types
 * Validates: Requirements 12.1-12.6
 */

export interface ApiResponse<T> {
  data?: T;
  error?: ApiError;
  success: boolean;
}

export interface ApiError {
  error: string;
  error_code: string;
  message: string;
  details?: Record<string, unknown>;
  retry_after?: number; // seconds
  suggested_action?: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  skip: number;
  take: number;
  has_more: boolean;
}

// HTTP method types for the API client
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';

export interface RequestConfig {
  method?: HttpMethod;
  headers?: Record<string, string>;
  body?: unknown;
  params?: Record<string, string | number | boolean | undefined>;
  timeout?: number;
}

// Health check types
export interface HealthStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  services: {
    database: ServiceStatus;
    redis?: ServiceStatus;
    lmstudio?: ServiceStatus;
    ollama?: ServiceStatus;
  };
  timestamp: string;
  version: string;
}

export interface ServiceStatus {
  available: boolean;
  message?: string;
  latency_ms?: number;
}
