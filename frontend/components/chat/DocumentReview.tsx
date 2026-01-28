'use client';

/**
 * Document Review Component
 * Displays extracted document data with edit capability
 * Validates: Requirements 11.1, 11.2, 11.3, 11.4, 11.6
 */

import React, { useState, useEffect } from 'react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';
import { DocumentData } from '@/types/chat';
import { validateDocumentJson, ValidationResult } from '@/lib/utils/validation';

interface DocumentReviewProps {
  document: DocumentData;
  onUpdate: (id: string, data: Record<string, unknown>) => void;
  onRemove: (id: string) => void;
  onReprocess?: (id: string) => void;
  showOriginalImage?: boolean;
}

export function DocumentReview({ 
  document, 
  onUpdate, 
  onRemove,
  onReprocess,
  showOriginalImage = false,
}: DocumentReviewProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [editedData, setEditedData] = useState<Record<string, unknown>>(document.data || {});
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [jsonText, setJsonText] = useState(JSON.stringify(document.data || {}, null, 2));
  const [validationResult, setValidationResult] = useState<ValidationResult | null>(null);

  // Sync with document prop changes
  useEffect(() => {
    setEditedData(document.data || {});
    setJsonText(JSON.stringify(document.data || {}, null, 2));
  }, [document.data]);

  const handleSave = () => {
    try {
      const parsed = JSON.parse(jsonText);
      
      // Validate the JSON structure
      const validation = validateDocumentJson(parsed, document.type);
      setValidationResult(validation);
      
      if (!validation.isValid) {
        setJsonError(validation.errors.join(', '));
        return;
      }
      
      setEditedData(parsed);
      onUpdate(document.id, parsed);
      setIsEditing(false);
      setJsonError(null);
    } catch (e) {
      setJsonError('Invalid JSON format: ' + (e instanceof Error ? e.message : 'Parse error'));
    }
  };

  const handleCancel = () => {
    setJsonText(JSON.stringify(editedData, null, 2));
    setIsEditing(false);
    setJsonError(null);
    setValidationResult(null);
  };

  const handleFieldChange = (field: string, value: string | number) => {
    const updated = { ...editedData, [field]: value };
    setEditedData(updated);
    setJsonText(JSON.stringify(updated, null, 2));
  };

  const handleJsonChange = (newJsonText: string) => {
    setJsonText(newJsonText);
    // Clear previous errors when user starts typing
    setJsonError(null);
    setValidationResult(null);
  };

  const data = editedData as {
    vendor_name?: string;
    total_amount?: number;
    date?: string;
    description?: string;
    reference?: string;
    currency?: string;
    issue_date?: string;
    supplier?: string;
    payee?: string;
    paid_by?: string;
  };

  return (
    <Card className="mb-4" padding="none">
      <CardHeader className="pb-2 p-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">
            <span className={`px-2 py-1 rounded text-xs mr-2 ${
              document.type === 'expense_receipt' 
                ? 'bg-green-100 text-green-700' 
                : 'bg-blue-100 text-blue-700'
            }`}>
              {document.type === 'expense_receipt' ? 'EXPENSE' : 'INVOICE'}
            </span>
            {document.filename || 'Document'}
          </CardTitle>
          <div className="flex space-x-2">
            {onReprocess && (
              <Button 
                variant="outline" 
                size="sm" 
                onClick={() => onReprocess(document.id)}
                title="Re-analyze this document"
              >
                🔄 Reprocess
              </Button>
            )}
            <Button 
              variant="outline" 
              size="sm" 
              onClick={() => setIsEditing(!isEditing)}
            >
              {isEditing ? 'Simple View' : '✏️ Edit'}
            </Button>
            <Button 
              variant="outline" 
              size="sm" 
              onClick={() => onRemove(document.id)}
              className="text-red-600 hover:bg-red-50"
              title="Remove this document from submission"
            >
              ✕ Remove
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-4 pt-0">
        {isEditing ? (
          <div className="space-y-4">
            {/* Form fields for common document data */}
            <div className="grid grid-cols-2 gap-4">
              <Input
                label="Vendor/Payee Name"
                value={data.vendor_name || data.payee || ''}
                onChange={(e) => handleFieldChange(
                  document.type === 'expense_receipt' ? 'payee' : 'vendor_name', 
                  e.target.value
                )}
              />
              <Input
                label="Date"
                type="date"
                value={data.date || data.issue_date || ''}
                onChange={(e) => handleFieldChange(
                  document.type === 'expense_receipt' ? 'date' : 'issue_date',
                  e.target.value
                )}
              />
              <Input
                label="Total Amount"
                type="number"
                step="0.01"
                value={data.total_amount ?? ''}
                onChange={(e) => handleFieldChange('total_amount', parseFloat(e.target.value) || 0)}
              />
              <Input
                label="Currency"
                value={data.currency || 'USD'}
                onChange={(e) => handleFieldChange('currency', e.target.value)}
              />
              <Input
                label="Reference"
                value={data.reference || ''}
                onChange={(e) => handleFieldChange('reference', e.target.value)}
                className="col-span-2"
              />
              <Input
                label="Description"
                value={data.description || ''}
                onChange={(e) => handleFieldChange('description', e.target.value)}
                className="col-span-2"
              />
            </div>
            
            {/* Raw JSON editor for advanced editing */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Raw JSON (Advanced)
              </label>
              <textarea
                value={jsonText}
                onChange={(e) => handleJsonChange(e.target.value)}
                className={`w-full h-40 p-2 border rounded font-mono text-sm ${
                  jsonError ? 'border-red-300 bg-red-50' : 'border-gray-300'
                }`}
                spellCheck={false}
              />
              {jsonError && (
                <p className="text-red-600 text-sm mt-1">{jsonError}</p>
              )}
              {validationResult && !validationResult.isValid && (
                <div className="mt-2 p-2 bg-yellow-50 border border-yellow-200 rounded">
                  <p className="text-yellow-800 text-sm font-medium">Validation warnings:</p>
                  <ul className="text-yellow-700 text-sm list-disc list-inside">
                    {validationResult.errors.map((err, i) => (
                      <li key={i}>{err}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            
            <div className="flex justify-end space-x-2">
              <Button variant="outline" onClick={handleCancel}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleSave}>
                Save Changes
              </Button>
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2 text-sm">
            {(data.vendor_name || data.payee) && (
              <div>
                <span className="text-gray-500">Vendor:</span>{' '}
                <span className="font-medium">{data.vendor_name || data.payee}</span>
              </div>
            )}
            {(data.date || data.issue_date) && (
              <div>
                <span className="text-gray-500">Date:</span>{' '}
                <span className="font-medium">{data.date || data.issue_date}</span>
              </div>
            )}
            {data.total_amount !== undefined && (
              <div>
                <span className="text-gray-500">Amount:</span>{' '}
                <span className="font-medium">
                  {data.currency || '$'}{data.total_amount.toFixed(2)}
                </span>
              </div>
            )}
            {data.reference && (
              <div>
                <span className="text-gray-500">Reference:</span>{' '}
                <span className="font-medium">{data.reference}</span>
              </div>
            )}
            {data.description && (
              <div className="col-span-2">
                <span className="text-gray-500">Description:</span>{' '}
                <span className="font-medium">{data.description}</span>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
