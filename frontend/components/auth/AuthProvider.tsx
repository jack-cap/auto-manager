'use client';

/**
 * Authentication Provider and Context
 * Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5
 */

import React, { createContext, useContext, useEffect, useState, useCallback } from 'react';
import { User, LoginCredentials, RegisterCredentials, AuthContext as AuthContextType, TokenResponse } from '@/types/auth';
import { authApi } from '@/lib/api/auth';
import { apiClient } from '@/lib/api/client';

const TOKEN_KEY = 'auth_tokens';
const TOKEN_REFRESH_INTERVAL = 4 * 60 * 1000; // 4 minutes (before 5 min expiry)

interface StoredTokens {
  access_token: string;
  refresh_token: string;
  expires_at: number;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [refreshTimer, setRefreshTimer] = useState<NodeJS.Timeout | null>(null);

  // Get stored tokens from localStorage
  const getStoredTokens = useCallback((): StoredTokens | null => {
    if (typeof window === 'undefined') return null;
    try {
      const stored = localStorage.getItem(TOKEN_KEY);
      return stored ? JSON.parse(stored) : null;
    } catch {
      return null;
    }
  }, []);

  // Store tokens in localStorage
  const storeTokens = useCallback((tokens: TokenResponse) => {
    if (typeof window === 'undefined') return;
    const storedTokens: StoredTokens = {
      access_token: tokens.access_token,
      refresh_token: tokens.refresh_token,
      expires_at: Date.now() + tokens.expires_in * 1000,
    };
    localStorage.setItem(TOKEN_KEY, JSON.stringify(storedTokens));
    apiClient.setAuthToken(tokens.access_token);
  }, []);

  // Clear stored tokens
  const clearTokens = useCallback(() => {
    if (typeof window === 'undefined') return;
    localStorage.removeItem(TOKEN_KEY);
    apiClient.setAuthToken(null);
  }, []);

  // Refresh the access token
  const refreshToken = useCallback(async () => {
    const tokens = getStoredTokens();
    if (!tokens?.refresh_token) {
      throw new Error('No refresh token available');
    }

    const response = await authApi.refreshToken();
    if (!response.success || !response.data) {
      clearTokens();
      setUser(null);
      throw new Error(response.error?.message || 'Failed to refresh token');
    }

    storeTokens(response.data);
    return response.data;
  }, [getStoredTokens, storeTokens, clearTokens]);

  // Setup automatic token refresh
  const setupTokenRefresh = useCallback(() => {
    if (refreshTimer) {
      clearInterval(refreshTimer);
    }

    const timer = setInterval(async () => {
      try {
        await refreshToken();
      } catch (error) {
        console.error('Token refresh failed:', error);
        setUser(null);
        clearTokens();
      }
    }, TOKEN_REFRESH_INTERVAL);

    setRefreshTimer(timer);
    return timer;
  }, [refreshTimer, refreshToken, clearTokens]);

  // Login function
  const login = useCallback(async (credentials: LoginCredentials) => {
    const response = await authApi.login(credentials);
    
    if (!response.success || !response.data) {
      throw new Error(response.error?.message || 'Login failed');
    }

    storeTokens(response.data);

    // Fetch user profile
    const userResponse = await authApi.getCurrentUser();
    if (!userResponse.success || !userResponse.data) {
      clearTokens();
      throw new Error(userResponse.error?.message || 'Failed to get user profile');
    }

    setUser(userResponse.data);
    setupTokenRefresh();
  }, [storeTokens, clearTokens, setupTokenRefresh]);

  // Register function
  const register = useCallback(async (credentials: RegisterCredentials) => {
    const response = await authApi.register(credentials);
    
    if (!response.success || !response.data) {
      throw new Error(response.error?.message || 'Registration failed');
    }

    // Auto-login after registration
    await login({ email: credentials.email, password: credentials.password });
  }, [login]);

  // Logout function
  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch (error) {
      console.error('Logout API call failed:', error);
    } finally {
      if (refreshTimer) {
        clearInterval(refreshTimer);
        setRefreshTimer(null);
      }
      clearTokens();
      setUser(null);
    }
  }, [refreshTimer, clearTokens]);

  // Initialize auth state on mount
  useEffect(() => {
    const initAuth = async () => {
      const tokens = getStoredTokens();
      
      if (!tokens?.access_token) {
        setIsLoading(false);
        return;
      }

      // Check if token is expired
      if (tokens.expires_at < Date.now()) {
        try {
          await refreshToken();
        } catch {
          clearTokens();
          setIsLoading(false);
          return;
        }
      } else {
        apiClient.setAuthToken(tokens.access_token);
      }

      // Fetch current user
      try {
        const userResponse = await authApi.getCurrentUser();
        if (userResponse.success && userResponse.data) {
          setUser(userResponse.data);
          setupTokenRefresh();
        } else {
          clearTokens();
        }
      } catch {
        clearTokens();
      }

      setIsLoading(false);
    };

    initAuth();

    // Cleanup on unmount
    return () => {
      if (refreshTimer) {
        clearInterval(refreshTimer);
      }
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const value: AuthContextType = {
    user,
    isAuthenticated: !!user,
    isLoading,
    login,
    register,
    logout,
    refreshToken,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
