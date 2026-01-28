'use client';

/**
 * Chat Page
 * Main page for interacting with the bookkeeping agent
 * Uses three-panel layout: Thinking | Chat | Files
 */

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/components/auth';
import { useCompany } from '@/components/company';
import { ChatInterfaceV2 } from '@/components/chat';
import { PageLoading } from '@/components/ui';

export default function ChatPage() {
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { selectedCompany, isLoading: companyLoading } = useCompany();
  const router = useRouter();

  useEffect(() => {
    if (!authLoading && !isAuthenticated) {
      router.push('/login');
    }
  }, [isAuthenticated, authLoading, router]);

  if (authLoading || companyLoading) {
    return <PageLoading message="Loading chat..." />;
  }

  if (!isAuthenticated) {
    return null;
  }

  if (!selectedCompany) {
    return (
      <div className="h-screen flex items-center justify-center bg-gray-100">
        <div className="bg-white rounded-lg shadow-lg p-8 text-center max-w-md">
          <h2 className="text-xl font-semibold mb-4">No Company Selected</h2>
          <p className="text-gray-600 mb-4">
            Please select or create a company to start using the bookkeeping assistant.
          </p>
          <button
            onClick={() => router.push('/companies')}
            className="px-4 py-2 bg-gray-900 text-white rounded-lg hover:bg-gray-800"
          >
            Manage Companies
          </button>
        </div>
      </div>
    );
  }

  return (
    <ChatInterfaceV2
      companyId={selectedCompany.id}
      companyName={selectedCompany.name}
    />
  );
}
