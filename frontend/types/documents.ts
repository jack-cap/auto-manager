/**
 * Document processing types
 * Validates: Requirements 3.1-3.8, 4.1-4.9, 6.1-6.8, 11.1-11.6
 */

export type DocumentType = 'expense_receipt' | 'purchase_invoice';
export type DocumentStatus = 'pending' | 'reviewed' | 'submitted' | 'error';

export interface ProcessedDocument {
  id: string;
  fileName: string;
  documentType: DocumentType;
  extractedData: ExpenseClaimData | PurchaseInvoiceData;
  status: DocumentStatus;
  originalImageUrl?: string;
  errorMessage?: string;
}

// Manager.io data types
export interface Account {
  key: string;
  name: string;
  code?: string;
}

export interface Supplier {
  key: string;
  name: string;
}

export interface Customer {
  key: string;
  name: string;
}

// Expense Claim types
export interface ExpenseClaimLine {
  account: string; // Account key (UUID)
  line_description: string;
  qty: number;
  purchase_unit_price: number;
}

export interface ExpenseClaimData {
  date: string; // YYYY-MM-DD
  paid_by: string; // Employee key
  payee: string;
  description: string;
  lines: ExpenseClaimLine[];
  has_line_description: boolean;
}

// Purchase Invoice types
export interface PurchaseInvoiceLine {
  account: string; // Account key (UUID)
  line_description: string;
  purchase_unit_price: number;
}

export interface PurchaseInvoiceData {
  issue_date: string; // YYYY-MM-DD
  reference: string;
  description: string;
  supplier: string; // Supplier key
  lines: PurchaseInvoiceLine[];
  has_line_number: boolean;
  has_line_description: boolean;
}

// Submission types
export type SubmissionMode = 'combined' | 'individual';

export interface SubmitRequest {
  company_id: string;
  document_ids: string[];
  mode: SubmissionMode;
}

export interface SubmissionResult {
  success: boolean;
  message: string;
  key?: string;
  document_id?: string;
  document_ids?: string[];
}

export interface SubmitResponse {
  results: SubmissionResult[];
}
