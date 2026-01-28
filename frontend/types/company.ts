/**
 * Company configuration types
 * Validates: Requirements 2.1-2.7
 */

export interface Company {
  id: string;
  name: string;
  baseUrl: string;
  isConnected: boolean;
}

export interface CompanyFormData {
  name: string;
  apiKey: string;
  baseUrl: string;
}

export interface CompanyCreateRequest {
  name: string;
  api_key: string;
  base_url: string;
}

export interface CompanyUpdateRequest {
  name?: string;
  api_key?: string;
  base_url?: string;
}
