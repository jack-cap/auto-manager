/**
 * Chat and conversation types
 * Validates: Requirements 4.10, 4.11, 4.12
 */

import { ProcessedDocument } from './documents';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  created_at: string;
  attachments?: FileAttachment[];
  structuredData?: ProcessedDocument[];
}

export interface FileAttachment {
  id: string;
  name: string;
  type: string;
  size: number;
  previewUrl?: string;
}

export interface ChatRequest {
  message: string;
  company_id: string;
  conversation_id?: string;
  confirm_submission?: boolean;
  history?: Array<{ role: string; content: string }>;
}

export interface DocumentData {
  id: string;
  type: string;
  filename?: string;
  status: string;
  extracted_data?: Record<string, unknown>;
  data?: Record<string, unknown>;
  matched_supplier?: {
    key: string;
    name: string;
    confidence: number;
  };
  matched_account?: {
    key: string;
    name: string;
    confidence: number;
  };
  prepared_entry?: Record<string, unknown>;
  error?: string;
}

export interface AgentEvent {
  type: string;
  status: 'started' | 'completed' | 'error';
  message: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

export interface ChatResponse {
  message: string;
  conversation_id: string;
  documents: DocumentData[];
  events: AgentEvent[];
  requires_confirmation: boolean;
}

export interface SubmitRequest {
  company_id: string;
  conversation_id: string;
  confirmed: boolean;
  document_ids?: string[];
  mode?: 'combined' | 'individual';
}

export interface SubmitResponse {
  success: boolean;
  message: string;
  results: Array<{
    type: string;
    status: string;
    message: string;
  }>;
}
