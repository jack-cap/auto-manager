/**
 * ProtectedRoute tests
 * Validates: Requirements 1.1, 1.4
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ProtectedRoute } from './ProtectedRoute';
import { AuthProvider } from './AuthProvider';

// Mock next/navigation
const mockPush = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({
    push: mockPush,
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
  }),
  usePathname: () => '/',
  useSearchParams: () => new URLSearchParams(),
}));

// Mock the API client
jest.mock('@/lib/api/client', () => ({
  apiClient: {
    setAuthToken: jest.fn(),
    post: jest.fn(),
    get: jest.fn(),
  },
}));

// Mock the auth API
jest.mock('@/lib/api/auth', () => ({
  authApi: {
    login: jest.fn(),
    logout: jest.fn(),
    refreshToken: jest.fn(),
    getCurrentUser: jest.fn(),
  },
}));

import { authApi } from '@/lib/api/auth';

describe('ProtectedRoute', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.getItem.mockReturnValue(null);
  });

  it('should show loading spinner while checking authentication', () => {
    // Don't resolve getCurrentUser to keep loading state
    (authApi.getCurrentUser as jest.Mock).mockImplementation(() => 
      new Promise(() => {}) // Never resolves
    );
    
    // Set up stored tokens to trigger auth check
    localStorage.getItem.mockReturnValue(JSON.stringify({
      access_token: 'test-token',
      refresh_token: 'test-refresh',
      expires_at: Date.now() + 300000,
    }));
    
    render(
      <AuthProvider>
        <ProtectedRoute>
          <div data-testid="protected-content">Protected Content</div>
        </ProtectedRoute>
      </AuthProvider>
    );
    
    // Should show loading spinner
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('should redirect to login when not authenticated', async () => {
    render(
      <AuthProvider>
        <ProtectedRoute>
          <div data-testid="protected-content">Protected Content</div>
        </ProtectedRoute>
      </AuthProvider>
    );
    
    // Wait for auth check to complete
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/login');
    });
    
    // Protected content should not be visible
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('should redirect to custom path when specified', async () => {
    render(
      <AuthProvider>
        <ProtectedRoute redirectTo="/custom-login">
          <div data-testid="protected-content">Protected Content</div>
        </ProtectedRoute>
      </AuthProvider>
    );
    
    // Wait for auth check to complete
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/custom-login');
    });
  });

  it('should render children when authenticated', async () => {
    const storedTokens = {
      access_token: 'valid-token',
      refresh_token: 'valid-refresh',
      expires_at: Date.now() + 300000,
    };
    
    const mockUser = {
      id: '123',
      email: 'test@example.com',
      name: 'Test User',
    };
    
    localStorage.getItem.mockReturnValue(JSON.stringify(storedTokens));
    
    (authApi.getCurrentUser as jest.Mock).mockResolvedValue({
      success: true,
      data: mockUser,
    });
    
    render(
      <AuthProvider>
        <ProtectedRoute>
          <div data-testid="protected-content">Protected Content</div>
        </ProtectedRoute>
      </AuthProvider>
    );
    
    // Wait for auth check to complete and content to render
    await waitFor(() => {
      expect(screen.getByTestId('protected-content')).toBeInTheDocument();
    });
    
    expect(screen.getByTestId('protected-content')).toHaveTextContent('Protected Content');
    
    // Should not redirect
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('should render fallback when not authenticated and fallback provided', async () => {
    render(
      <AuthProvider>
        <ProtectedRoute fallback={<div data-testid="fallback">Please login</div>}>
          <div data-testid="protected-content">Protected Content</div>
        </ProtectedRoute>
      </AuthProvider>
    );
    
    // Wait for auth check to complete
    await waitFor(() => {
      expect(screen.getByTestId('fallback')).toBeInTheDocument();
    });
    
    expect(screen.getByTestId('fallback')).toHaveTextContent('Please login');
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });

  it('should handle session expiration and redirect', async () => {
    const storedTokens = {
      access_token: 'expired-token',
      refresh_token: 'expired-refresh',
      expires_at: Date.now() - 1000, // Expired
    };
    
    localStorage.getItem.mockReturnValue(JSON.stringify(storedTokens));
    
    // Refresh token fails
    (authApi.refreshToken as jest.Mock).mockResolvedValue({
      success: false,
      error: {
        error: 'Token expired',
        error_code: 'TOKEN_EXPIRED',
        message: 'Refresh token has expired',
      },
    });
    
    render(
      <AuthProvider>
        <ProtectedRoute>
          <div data-testid="protected-content">Protected Content</div>
        </ProtectedRoute>
      </AuthProvider>
    );
    
    // Wait for auth check to complete and redirect
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith('/login');
    });
    
    // Protected content should not be visible
    expect(screen.queryByTestId('protected-content')).not.toBeInTheDocument();
  });
});
