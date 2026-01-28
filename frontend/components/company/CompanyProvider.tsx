'use client';

/**
 * Company Context Provider
 * Manages selected company state with localStorage persistence
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4
 */

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { Company } from '@/types/company';
import { companyApi } from '@/lib/api/company';
import { getStorageItem, setStorageItem, removeStorageItem, STORAGE_KEYS } from '@/lib/utils/storage';
import { useAuth } from '@/components/auth';

interface CompanyContextType {
  companies: Company[];
  selectedCompany: Company | null;
  isLoading: boolean;
  error: string | null;
  selectCompany: (company: Company | null) => void;
  refreshCompanies: () => Promise<void>;
  addCompany: (company: Company) => void;
  updateCompany: (company: Company) => void;
  removeCompany: (companyId: string) => void;
}

const CompanyContext = createContext<CompanyContextType | undefined>(undefined);

export function CompanyProvider({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const [companies, setCompanies] = useState<Company[]>([]);
  const [selectedCompany, setSelectedCompany] = useState<Company | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load companies from API
  const refreshCompanies = useCallback(async () => {
    // Don't fetch if not authenticated
    if (!isAuthenticated) {
      setCompanies([]);
      setSelectedCompany(null);
      setIsLoading(false);
      return;
    }
    
    setIsLoading(true);
    setError(null);
    
    try {
      const response = await companyApi.getCompanies();
      
      if (response.success && response.data) {
        setCompanies(response.data);
        
        // Restore selected company from localStorage
        const storedCompanyId = getStorageItem<string>(STORAGE_KEYS.SELECTED_COMPANY);
        if (storedCompanyId) {
          const storedCompany = response.data.find(c => c.id === storedCompanyId);
          if (storedCompany) {
            setSelectedCompany(storedCompany);
          } else {
            // Stored company no longer exists, clear it
            removeStorageItem(STORAGE_KEYS.SELECTED_COMPANY);
          }
        }
      } else {
        setError(response.error?.message || 'Failed to load companies');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load companies');
    } finally {
      setIsLoading(false);
    }
  }, [isAuthenticated]);

  // Select a company and persist to localStorage
  const selectCompany = useCallback((company: Company | null) => {
    setSelectedCompany(company);
    
    if (company) {
      setStorageItem(STORAGE_KEYS.SELECTED_COMPANY, company.id);
    } else {
      removeStorageItem(STORAGE_KEYS.SELECTED_COMPANY);
    }
  }, []);

  // Add a new company to the list
  const addCompany = useCallback((company: Company) => {
    setCompanies(prev => [...prev, company]);
  }, []);

  // Update an existing company in the list
  const updateCompany = useCallback((company: Company) => {
    setCompanies(prev => prev.map(c => c.id === company.id ? company : c));
    
    // Update selected company if it was the one updated
    if (selectedCompany?.id === company.id) {
      setSelectedCompany(company);
    }
  }, [selectedCompany]);

  // Remove a company from the list
  const removeCompany = useCallback((companyId: string) => {
    setCompanies(prev => prev.filter(c => c.id !== companyId));
    
    // Clear selection if the removed company was selected
    if (selectedCompany?.id === companyId) {
      selectCompany(null);
    }
  }, [selectedCompany, selectCompany]);

  // Load companies on mount and when auth state changes
  useEffect(() => {
    // Wait for auth to finish loading before fetching companies
    if (!authLoading) {
      refreshCompanies();
    }
  }, [authLoading, refreshCompanies]);

  const value: CompanyContextType = {
    companies,
    selectedCompany,
    isLoading,
    error,
    selectCompany,
    refreshCompanies,
    addCompany,
    updateCompany,
    removeCompany,
  };

  return (
    <CompanyContext.Provider value={value}>
      {children}
    </CompanyContext.Provider>
  );
}

export function useCompany(): CompanyContextType {
  const context = useContext(CompanyContext);
  if (context === undefined) {
    throw new Error('useCompany must be used within a CompanyProvider');
  }
  return context;
}
