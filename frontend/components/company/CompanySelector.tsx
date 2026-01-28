'use client';

/**
 * Company Selector Component
 * Dropdown to select active company for API operations
 * Validates: Requirements 2.2
 */

import React, { useState, useRef, useEffect } from 'react';
import { Company } from '@/types/company';
import { useCompany } from './CompanyProvider';

interface CompanySelectorProps {
  onCompanyChange?: (company: Company | null) => void;
  className?: string;
}

export function CompanySelector({ onCompanyChange, className = '' }: CompanySelectorProps) {
  const { companies, selectedCompany, isLoading, selectCompany } = useCompany();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Handle company selection
  const handleSelect = (company: Company) => {
    selectCompany(company);
    onCompanyChange?.(company);
    setIsOpen(false);
  };

  // Handle clearing selection
  const handleClear = () => {
    selectCompany(null);
    onCompanyChange?.(null);
    setIsOpen(false);
  };

  if (isLoading) {
    return (
      <div className={`relative ${className}`}>
        <div className="flex items-center justify-between w-full px-3 py-2 text-sm bg-gray-100 border border-gray-300 rounded-md">
          <span className="text-gray-400">Loading companies...</span>
        </div>
      </div>
    );
  }

  if (companies.length === 0) {
    return (
      <div className={`relative ${className}`}>
        <div className="flex items-center justify-between w-full px-3 py-2 text-sm bg-gray-50 border border-gray-300 rounded-md">
          <span className="text-gray-500">No companies configured</span>
        </div>
      </div>
    );
  }

  return (
    <div className={`relative ${className}`} ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between w-full px-3 py-2 text-sm bg-white border border-gray-300 rounded-md shadow-sm hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500"
        aria-haspopup="listbox"
        aria-expanded={isOpen}
      >
        <div className="flex items-center gap-2 truncate">
          {selectedCompany ? (
            <>
              <span 
                className={`w-2 h-2 rounded-full ${
                  selectedCompany.isConnected ? 'bg-green-500' : 'bg-yellow-500'
                }`}
              />
              <span className="truncate">{selectedCompany.name}</span>
            </>
          ) : (
            <span className="text-gray-500">Select a company</span>
          )}
        </div>
        <svg
          className={`w-5 h-5 text-gray-400 transition-transform ${isOpen ? 'rotate-180' : ''}`}
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 20 20"
          fill="currentColor"
        >
          <path
            fillRule="evenodd"
            d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z"
            clipRule="evenodd"
          />
        </svg>
      </button>

      {isOpen && (
        <div className="absolute z-10 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-60 overflow-auto">
          <ul role="listbox" className="py-1">
            {selectedCompany && (
              <li
                role="option"
                aria-selected={false}
                className="px-3 py-2 text-sm text-gray-500 hover:bg-gray-100 cursor-pointer border-b border-gray-200"
                onClick={handleClear}
              >
                Clear selection
              </li>
            )}
            {companies.map((company) => (
              <li
                key={company.id}
                role="option"
                aria-selected={selectedCompany?.id === company.id}
                className={`px-3 py-2 text-sm cursor-pointer ${
                  selectedCompany?.id === company.id
                    ? 'bg-primary-50 text-primary-900'
                    : 'text-gray-900 hover:bg-gray-100'
                }`}
                onClick={() => handleSelect(company)}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 truncate">
                    <span 
                      className={`w-2 h-2 rounded-full flex-shrink-0 ${
                        company.isConnected ? 'bg-green-500' : 'bg-yellow-500'
                      }`}
                    />
                    <span className="truncate">{company.name}</span>
                  </div>
                  {selectedCompany?.id === company.id && (
                    <svg
                      className="w-4 h-4 text-primary-600 flex-shrink-0"
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 20 20"
                      fill="currentColor"
                    >
                      <path
                        fillRule="evenodd"
                        d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                        clipRule="evenodd"
                      />
                    </svg>
                  )}
                </div>
                <p className="text-xs text-gray-500 truncate mt-0.5 ml-4">
                  {company.baseUrl}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
