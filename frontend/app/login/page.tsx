'use client';

/**
 * Login Page
 * Validates: Requirements 1.1, 1.2, 1.3
 */

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { LoginForm, RegisterForm, useAuth } from '@/components/auth';

export default function LoginPage() {
  const { isAuthenticated, isLoading } = useAuth();
  const router = useRouter();
  const [showRegister, setShowRegister] = useState(false);

  // Redirect to dashboard if already authenticated
  useEffect(() => {
    if (!isLoading && isAuthenticated) {
      router.push('/');
    }
  }, [isAuthenticated, isLoading, router]);

  // Show loading while checking auth state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
      </div>
    );
  }

  // Don't render login form if authenticated (will redirect)
  if (isAuthenticated) {
    return null;
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-4 bg-gray-50">
      <div className="mb-8 text-center">
        <h1 className="text-3xl font-bold text-gray-900">Auto Manager</h1>
        <p className="mt-2 text-gray-600">
          {showRegister ? 'Create your account' : 'Sign in to your account'}
        </p>
      </div>
      
      {showRegister ? (
        <RegisterForm 
          onSuccess={() => setShowRegister(false)}
          onSwitchToLogin={() => setShowRegister(false)}
        />
      ) : (
        <>
          <LoginForm />
          <p className="mt-4 text-center text-sm text-gray-600">
            Don&apos;t have an account?{' '}
            <button
              type="button"
              onClick={() => setShowRegister(true)}
              className="text-primary-600 hover:text-primary-500 font-medium"
            >
              Create one
            </button>
          </p>
        </>
      )}
    </main>
  );
}
