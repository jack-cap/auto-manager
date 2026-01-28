'use client';

/**
 * Company List Component
 * Displays list of companies with add/edit/delete actions
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4
 */

import React, { useState } from 'react';
import { Company } from '@/types/company';
import { companyApi } from '@/lib/api/company';
import { useCompany } from './CompanyProvider';
import { CompanyForm } from './CompanyForm';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';

interface CompanyListProps {
  onCompanySelect?: (company: Company) => void;
}

export function CompanyList({ onCompanySelect }: CompanyListProps) {
  const { 
    companies, 
    selectedCompany, 
    isLoading, 
    error, 
    selectCompany,
    addCompany,
    updateCompany,
    removeCompany,
    refreshCompanies,
  } = useCompany();
  
  const [showForm, setShowForm] = useState(false);
  const [editingCompany, setEditingCompany] = useState<Company | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  // Handle adding a new company
  const handleAddClick = () => {
    setEditingCompany(null);
    setShowForm(true);
  };

  // Handle editing a company
  const handleEditClick = (company: Company) => {
    setEditingCompany(company);
    setShowForm(true);
  };

  // Handle form success
  const handleFormSuccess = (company: Company) => {
    if (editingCompany) {
      updateCompany(company);
    } else {
      addCompany(company);
    }
    setShowForm(false);
    setEditingCompany(null);
  };

  // Handle form cancel
  const handleFormCancel = () => {
    setShowForm(false);
    setEditingCompany(null);
  };

  // Handle deleting a company
  const handleDeleteClick = async (company: Company) => {
    if (!confirm(`Are you sure you want to delete "${company.name}"? This action cannot be undone.`)) {
      return;
    }
    
    setDeletingId(company.id);
    setDeleteError(null);
    
    try {
      const response = await companyApi.deleteCompany(company.id);
      
      if (response.success) {
        removeCompany(company.id);
      } else {
        setDeleteError(response.error?.message || 'Failed to delete company');
      }
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Failed to delete company');
    } finally {
      setDeletingId(null);
    }
  };

  // Handle selecting a company
  const handleSelectClick = (company: Company) => {
    selectCompany(company);
    onCompanySelect?.(company);
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent>
          <div className="flex items-center justify-center py-8">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600"></div>
            <span className="ml-2 text-gray-600">Loading companies...</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (showForm) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>{editingCompany ? 'Edit Company' : 'Add Company'}</CardTitle>
        </CardHeader>
        <CardContent>
          <CompanyForm
            company={editingCompany}
            onSuccess={handleFormSuccess}
            onCancel={handleFormCancel}
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Companies</CardTitle>
          <Button variant="primary" size="sm" onClick={handleAddClick}>
            Add Company
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-600">{error}</p>
            <Button 
              variant="ghost" 
              size="sm" 
              onClick={refreshCompanies}
              className="mt-2"
            >
              Retry
            </Button>
          </div>
        )}
        
        {deleteError && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-md">
            <p className="text-sm text-red-600">{deleteError}</p>
          </div>
        )}
        
        {companies.length === 0 ? (
          <div className="text-center py-8">
            <p className="text-gray-500 mb-4">No companies configured yet.</p>
            <Button variant="primary" onClick={handleAddClick}>
              Add Your First Company
            </Button>
          </div>
        ) : (
          <ul className="divide-y divide-gray-200">
            {companies.map((company) => (
              <li 
                key={company.id} 
                className={`py-4 ${selectedCompany?.id === company.id ? 'bg-primary-50 -mx-4 px-4 rounded-md' : ''}`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h4 className="text-sm font-medium text-gray-900 truncate">
                        {company.name}
                      </h4>
                      {selectedCompany?.id === company.id && (
                        <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-primary-100 text-primary-800">
                          Selected
                        </span>
                      )}
                      <span 
                        className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                          company.isConnected 
                            ? 'bg-green-100 text-green-800' 
                            : 'bg-yellow-100 text-yellow-800'
                        }`}
                      >
                        {company.isConnected ? 'Connected' : 'Not Connected'}
                      </span>
                    </div>
                    <p className="text-sm text-gray-500 truncate">{company.baseUrl}</p>
                  </div>
                  
                  <div className="flex items-center gap-2 ml-4">
                    {selectedCompany?.id !== company.id && (
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => handleSelectClick(company)}
                      >
                        Select
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleEditClick(company)}
                    >
                      Edit
                    </Button>
                    <Button
                      variant="danger"
                      size="sm"
                      onClick={() => handleDeleteClick(company)}
                      isLoading={deletingId === company.id}
                      disabled={deletingId !== null}
                    >
                      Delete
                    </Button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
