'use client';

import { useRouter } from 'next/navigation';
import { useAuth, ProtectedRoute } from '@/components/auth';
import { useCompany } from '@/components/company';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/Card';

function DashboardContent() {
  const { user } = useAuth();
  const { selectedCompany } = useCompany();
  const router = useRouter();

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Main content */}
      <div className="max-w-7xl mx-auto px-4 py-8">
        <div className="mb-8">
          <h2 className="text-2xl font-bold text-gray-900">Welcome back, {user?.name}!</h2>
          <p className="text-gray-600">AI-powered bookkeeping automation for Manager.io</p>
        </div>

        {/* Quick actions */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <Card 
            className="cursor-pointer hover:shadow-lg transition-shadow"
            onClick={() => router.push('/chat')}
          >
            <CardHeader>
              <CardTitle className="flex items-center">
                <span className="text-2xl mr-2">💬</span>
                Chat Assistant
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-gray-600">
                Upload documents and chat with the AI assistant to process receipts and invoices.
              </p>
            </CardContent>
          </Card>

          <Card 
            className="cursor-pointer hover:shadow-lg transition-shadow"
            onClick={() => router.push('/companies')}
          >
            <CardHeader>
              <CardTitle className="flex items-center">
                <span className="text-2xl mr-2">🏢</span>
                Companies
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-gray-600">
                Manage your Manager.io company connections and API configurations.
              </p>
            </CardContent>
          </Card>

          <Card 
            className="cursor-pointer hover:shadow-lg transition-shadow"
            onClick={() => router.push('/dashboard')}
          >
            <CardHeader>
              <CardTitle className="flex items-center">
                <span className="text-2xl mr-2">📊</span>
                Dashboard
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-gray-600">
                View financial summaries, cash flow, and expense reports.
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Current company status */}
        {selectedCompany ? (
          <Card>
            <CardHeader>
              <CardTitle>Current Company</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="font-medium">{selectedCompany.name}</p>
              <p className="text-sm text-gray-500">{selectedCompany.base_url}</p>
              <Button 
                variant="primary" 
                className="mt-4"
                onClick={() => router.push('/chat')}
              >
                Start Processing Documents
              </Button>
            </CardContent>
          </Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Get Started</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-gray-600 mb-4">
                Connect your Manager.io instance to start automating your bookkeeping.
              </p>
              <Button 
                variant="primary"
                onClick={() => router.push('/companies')}
              >
                Add Company
              </Button>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

export default function Home() {
  return (
    <ProtectedRoute>
      <DashboardContent />
    </ProtectedRoute>
  );
}
