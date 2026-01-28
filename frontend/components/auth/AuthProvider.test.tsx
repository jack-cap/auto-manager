/**
 * AuthProvider tests
 * Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
 */

import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthProvider, useAuth } from './AuthProvider';

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

import { apiClient } from '@/lib/api/client';
import { authApi } from '@/lib/api/auth';

// Test component that uses the auth context
function TestComponent() {
  const { user, isAuthenticated, isLoading, login, logout } = useAuth();
  
  return (
    <div>
      <div data-testid="loading">{isLoading ? 'loading' : 'not-loading'}</div>
      <div data-testid="authenticated">{isAuthenticated ? 'authenticated' : 'not-authenticated'}</div>
      <div data-testid="user">{user ? user.email : 'no-user'}</div>
      <button onClick={() => login({ email: 'test@example.com', password: 'password123' })}>
        Login
      </button>
      <button onClick={logout}>Logout</button>
    </div>
  );
}

describe('AuthProvider', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.getItem.mockReturnValue(null);
  });

  it('should render children', () => {
    render(
      <AuthProvider>
        <div data-testid="child">Child content</div>
      </AuthProvider>
    );
    
    expect(screen.getByTestId('child')).toHaveTextContent('Child content');
  });

  it('should start with loading state and no user', async () => {
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    // Wait for initial auth check to complete
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('not-loading');
    });
    
    expect(screen.getByTestId('authenticated')).toHaveTextContent('not-authenticated');
    expect(screen.getByTestId('user')).toHaveTextContent('no-user');
  });

  it('should login successfully with valid credentials', async () => {
    const mockTokenResponse = {
      access_token: 'test-access-token',
      refresh_token: 'test-refresh-token',
      token_type: 'bearer',
      expires_in: 300,
    };
    
    const mockUser = {
      id: '123',
      email: 'test@example.com',
      name: 'Test User',
    };
    
    (authApi.login as jest.Mock).mockResolvedValue({
      success: true,
      data: mockTokenResponse,
    });
    
    (authApi.getCurrentUser as jest.Mock).mockResolvedValue({
      success: true,
      data: mockUser,
    });
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('not-loading');
    });
    
    // Click login button
    const loginButton = screen.getByText('Login');
    await act(async () => {
      await userEvent.click(loginButton);
    });
    
    // Verify login was called
    expect(authApi.login).toHaveBeenCalledWith({
      email: 'test@example.com',
      password: 'password123',
    });
    
    // Verify user is now authenticated
    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('user')).toHaveTextContent('test@example.com');
    });
    
    // Verify token was stored
    expect(apiClient.setAuthToken).toHaveBeenCalledWith('test-access-token');
  });

  it('should throw error on login with invalid credentials', async () => {
    (authApi.login as jest.Mock).mockResolvedValue({
      success: false,
      error: {
        error: 'Invalid credentials',
        error_code: 'INVALID_CREDENTIALS',
        message: 'Invalid email or password',
      },
    });
    
    // Create a component that catches the error
    let loginError: Error | null = null;
    function TestLoginComponent() {
      const { login } = useAuth();
      
      const handleLogin = async () => {
        try {
          await login({ email: 'test@example.com', password: 'password123' });
        } catch (error) {
          loginError = error as Error;
        }
      };
      
      return <button onClick={handleLogin}>Login</button>;
    }
    
    render(
      <AuthProvider>
        <TestLoginComponent />
      </AuthProvider>
    );
    
    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByText('Login')).toBeInTheDocument();
    });
    
    // Click login button
    const loginButton = screen.getByText('Login');
    await act(async () => {
      await userEvent.click(loginButton);
    });
    
    // Verify error was thrown
    expect(loginError).not.toBeNull();
    expect(loginError?.message).toBe('Invalid email or password');
  });

  it('should logout and clear user state', async () => {
    const mockTokenResponse = {
      access_token: 'test-access-token',
      refresh_token: 'test-refresh-token',
      token_type: 'bearer',
      expires_in: 300,
    };
    
    const mockUser = {
      id: '123',
      email: 'test@example.com',
      name: 'Test User',
    };
    
    (authApi.login as jest.Mock).mockResolvedValue({
      success: true,
      data: mockTokenResponse,
    });
    
    (authApi.getCurrentUser as jest.Mock).mockResolvedValue({
      success: true,
      data: mockUser,
    });
    
    (authApi.logout as jest.Mock).mockResolvedValue({
      success: true,
    });
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('not-loading');
    });
    
    // Login first
    const loginButton = screen.getByText('Login');
    await act(async () => {
      await userEvent.click(loginButton);
    });
    
    // Verify logged in
    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('authenticated');
    });
    
    // Now logout
    const logoutButton = screen.getByText('Logout');
    await act(async () => {
      await userEvent.click(logoutButton);
    });
    
    // Verify logged out
    await waitFor(() => {
      expect(screen.getByTestId('authenticated')).toHaveTextContent('not-authenticated');
      expect(screen.getByTestId('user')).toHaveTextContent('no-user');
    });
    
    // Verify token was cleared
    expect(apiClient.setAuthToken).toHaveBeenCalledWith(null);
  });

  it('should restore session from localStorage on mount', async () => {
    const storedTokens = {
      access_token: 'stored-access-token',
      refresh_token: 'stored-refresh-token',
      expires_at: Date.now() + 300000, // 5 minutes from now
    };
    
    const mockUser = {
      id: '123',
      email: 'stored@example.com',
      name: 'Stored User',
    };
    
    localStorage.getItem.mockReturnValue(JSON.stringify(storedTokens));
    
    (authApi.getCurrentUser as jest.Mock).mockResolvedValue({
      success: true,
      data: mockUser,
    });
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    // Wait for session restoration
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('not-loading');
      expect(screen.getByTestId('authenticated')).toHaveTextContent('authenticated');
      expect(screen.getByTestId('user')).toHaveTextContent('stored@example.com');
    });
    
    // Verify token was set
    expect(apiClient.setAuthToken).toHaveBeenCalledWith('stored-access-token');
  });

  it('should refresh expired token on mount', async () => {
    const storedTokens = {
      access_token: 'expired-access-token',
      refresh_token: 'valid-refresh-token',
      expires_at: Date.now() - 1000, // Expired 1 second ago
    };
    
    const newTokenResponse = {
      access_token: 'new-access-token',
      refresh_token: 'new-refresh-token',
      token_type: 'bearer',
      expires_in: 300,
    };
    
    const mockUser = {
      id: '123',
      email: 'refreshed@example.com',
      name: 'Refreshed User',
    };
    
    localStorage.getItem.mockReturnValue(JSON.stringify(storedTokens));
    
    (authApi.refreshToken as jest.Mock).mockResolvedValue({
      success: true,
      data: newTokenResponse,
    });
    
    (authApi.getCurrentUser as jest.Mock).mockResolvedValue({
      success: true,
      data: mockUser,
    });
    
    render(
      <AuthProvider>
        <TestComponent />
      </AuthProvider>
    );
    
    // Wait for token refresh and session restoration
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('not-loading');
      expect(screen.getByTestId('authenticated')).toHaveTextContent('authenticated');
    });
    
    // Verify refresh was called
    expect(authApi.refreshToken).toHaveBeenCalled();
    
    // Verify new token was set
    expect(apiClient.setAuthToken).toHaveBeenCalledWith('new-access-token');
  });
});

describe('useAuth hook', () => {
  it('should throw error when used outside AuthProvider', () => {
    // Suppress console.error for this test
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
    
    expect(() => {
      render(<TestComponent />);
    }).toThrow('useAuth must be used within an AuthProvider');
    
    consoleSpy.mockRestore();
  });
});
