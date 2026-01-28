'use client';

/**
 * Company Form Component
 * Form for adding/editing company configurations with validation
 * Validates: Requirements 2.1, 2.3, 2.5
 */

import React, { useState, useEffect } from 'react';
import { Company, CompanyFormData, CompanyCreateRequest, CompanyUpdateRequest } from '@/types/company';
import { companyApi } from '@/lib/api/company';
import { isValidUrl } from '@/lib/utils/validation';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';

interface CompanyFormProps {
  company?: Company | null;
  onSuccess: (company: Company) => void;
  onCancel: () => void;
}

interface FormErrors {
  name?: string;
  apiKey?: string;
  baseUrl?: string;
  general?: string;
}

export function CompanyForm({ company, onSuccess, onCancel }: CompanyFormProps) {
  const isEditing = !!company;
  
  const [formData, setFormData] = useState<CompanyFormData>({
    name: company?.name || '',
    apiKey: '',
    baseUrl: company?.baseUrl || '',
  });
  
  const [errors, setErrors] = useState<FormErrors>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // Reset form when company changes
  useEffect(() => {
    if (company) {
      setFormData({
        name: company.name,
        apiKey: '',
        baseUrl: company.baseUrl,
      });
    } else {
      setFormData({
        name: '',
        apiKey: '',
        baseUrl: '',
      });
    }
    setErrors({});
    setTestResult(null);
  }, [company]);

  // Validate form fields
  const validateForm = (): boolean => {
    const newErrors: FormErrors = {};
    
    if (!formData.name.trim()) {
      newErrors.name = 'Company name is required';
    } else if (formData.name.trim().length < 2) {
      newErrors.name = 'Company name must be at least 2 characters';
    }
    
    if (!isEditing && !formData.apiKey.trim()) {
      newErrors.apiKey = 'API key is required';
    } else if (formData.apiKey && formData.apiKey.trim().length < 10) {
      newErrors.apiKey = 'API key seems too short';
    }
    
    if (!formData.baseUrl.trim()) {
      newErrors.baseUrl = 'Base URL is required';
    } else if (!isValidUrl(formData.baseUrl)) {
      newErrors.baseUrl = 'Please enter a valid URL';
    }
    
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  // Handle input changes
  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    
    // Clear error for this field when user starts typing
    if (errors[name as keyof FormErrors]) {
      setErrors(prev => ({ ...prev, [name]: undefined }));
    }
    
    // Clear test result when form changes
    setTestResult(null);
  };

  // Handle form submission
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    if (!validateForm()) {
      return;
    }
    
    setIsSubmitting(true);
    setErrors({});
    
    try {
      let response;
      
      if (isEditing && company) {
        // Update existing company
        const updateData: CompanyUpdateRequest = {
          name: formData.name.trim(),
          base_url: formData.baseUrl.trim(),
        };
        
        // Only include API key if provided
        if (formData.apiKey.trim()) {
          updateData.api_key = formData.apiKey.trim();
        }
        
        response = await companyApi.updateCompany(company.id, updateData);
      } else {
        // Create new company
        const createData: CompanyCreateRequest = {
          name: formData.name.trim(),
          api_key: formData.apiKey.trim(),
          base_url: formData.baseUrl.trim(),
        };
        
        response = await companyApi.createCompany(createData);
      }
      
      if (response.success && response.data) {
        onSuccess(response.data);
      } else {
        setErrors({ general: response.error?.message || 'Failed to save company' });
      }
    } catch (err) {
      setErrors({ general: err instanceof Error ? err.message : 'An error occurred' });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Test connection to Manager.io
  const handleTestConnection = async () => {
    if (!company) {
      setTestResult({ success: false, message: 'Save the company first to test connection' });
      return;
    }
    
    setIsTesting(true);
    setTestResult(null);
    
    try {
      const response = await companyApi.testConnection(company.id);
      
      if (response.success && response.data) {
        setTestResult({
          success: response.data.connected,
          message: response.data.message,
        });
      } else {
        setTestResult({
          success: false,
          message: response.error?.message || 'Connection test failed',
        });
      }
    } catch (err) {
      setTestResult({
        success: false,
        message: err instanceof Error ? err.message : 'Connection test failed',
      });
    } finally {
      setIsTesting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {errors.general && (
        <div className="p-3 bg-red-50 border border-red-200 rounded-md">
          <p className="text-sm text-red-600">{errors.general}</p>
        </div>
      )}
      
      <Input
        label="Company Name"
        name="name"
        type="text"
        value={formData.name}
        onChange={handleChange}
        error={errors.name}
        placeholder="My Company"
        required
      />
      
      <Input
        label={isEditing ? "API Key (leave blank to keep current)" : "API Key"}
        name="apiKey"
        type="password"
        value={formData.apiKey}
        onChange={handleChange}
        error={errors.apiKey}
        placeholder={isEditing ? "••••••••" : "Enter your Manager.io API key"}
        helperText="Get your API key from Manager.io Settings → Access Tokens"
        required={!isEditing}
      />
      
      <Input
        label="Base URL"
        name="baseUrl"
        type="url"
        value={formData.baseUrl}
        onChange={handleChange}
        error={errors.baseUrl}
        placeholder="https://your-manager-io-instance.com"
        helperText="The URL of your Manager.io instance"
        required
      />
      
      {testResult && (
        <div className={`p-3 rounded-md ${testResult.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200'}`}>
          <p className={`text-sm ${testResult.success ? 'text-green-600' : 'text-red-600'}`}>
            {testResult.message}
          </p>
        </div>
      )}
      
      <div className="flex justify-between pt-4">
        <div>
          {isEditing && (
            <Button
              type="button"
              variant="outline"
              onClick={handleTestConnection}
              isLoading={isTesting}
              disabled={isSubmitting}
            >
              Test Connection
            </Button>
          )}
        </div>
        
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          
          <Button
            type="submit"
            variant="primary"
            isLoading={isSubmitting}
          >
            {isEditing ? 'Update Company' : 'Add Company'}
          </Button>
        </div>
      </div>
    </form>
  );
}
