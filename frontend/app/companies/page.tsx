'use client';

/**
 * Companies Management Page
 * Page for managing company configurations
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4
 */

import React from 'react';
import { CompanyList } from '@/components/company';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';

function CompaniesPageContent() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Main Content */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-6">
          <h1 className="text-2xl font-bold text-gray-900">Company Management</h1>
          <p className="text-sm text-gray-500 mt-1">
            Manage your Manager.io company configurations
          </p>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
          {/* Company List - Main Content */}
          <div className="lg:col-span-2">
            <CompanyList />
          </div>

          {/* Sidebar - Help & Info */}
          <div className="lg:col-span-1">
            <div className="bg-white rounded-lg shadow p-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Getting Started
              </h2>
              <div className="space-y-4 text-sm text-gray-600">
                <div>
                  <h3 className="font-medium text-gray-900">1. Add a Company</h3>
                  <p>
                    Click &quot;Add Company&quot; to configure a new Manager.io instance.
                    You&apos;ll need your API key and the base URL of your Manager.io server.
                  </p>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900">2. Get Your API Key</h3>
                  <p>
                    In Manager.io, go to Settings → Access Tokens to create a new API key.
                    Make sure to copy it before closing the dialog.
                  </p>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900">3. Select a Company</h3>
                  <p>
                    Use the dropdown in the header or click &quot;Select&quot; on a company
                    to make it active. All API operations will use the selected company.
                  </p>
                </div>
                <div>
                  <h3 className="font-medium text-gray-900">4. Test Connection</h3>
                  <p>
                    After adding a company, click &quot;Edit&quot; and then &quot;Test Connection&quot;
                    to verify your API key and URL are correct.
                  </p>
                </div>
              </div>
            </div>

            {/* Quick Links */}
            <div className="bg-white rounded-lg shadow p-6 mt-6">
              <h2 className="text-lg font-semibold text-gray-900 mb-4">
                Quick Links
              </h2>
              <ul className="space-y-2 text-sm">
                <li>
                  <a 
                    href="https://manager.readme.io/reference" 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-primary-600 hover:text-primary-800 hover:underline"
                  >
                    Manager.io API Documentation →
                  </a>
                </li>
                <li>
                  <a 
                    href="/" 
                    className="text-primary-600 hover:text-primary-800 hover:underline"
                  >
                    Back to Dashboard →
                  </a>
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function CompaniesPage() {
  return (
    <ProtectedRoute>
      <CompaniesPageContent />
    </ProtectedRoute>
  );
}
