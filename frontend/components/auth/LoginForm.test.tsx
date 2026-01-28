/**
 * LoginForm tests
 * Validates: Requirements 1.1, 1.2, 1.3
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LoginForm } from './LoginForm';
import { AuthProvider } from './AuthProvider';

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

// Wrapper component with AuthProvider
function renderWithAuth(ui: React.ReactElement) {
  return render(
    <AuthProvider>
      {ui}
    </AuthProvider>
  );
}

describe('LoginForm', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.getItem.mockReturnValue(null);
  });

  it('should render login form with email and password fields', async () => {
    renderWithAuth(<LoginForm />);
    
    // Wait for auth provider to initialize
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
  });

  it('should show validation error for empty email', async () => {
    renderWithAuth(<LoginForm />);
    
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    // Fill only password
    await userEvent.type(screen.getByLabelText(/password/i), 'password123');
    
    // Submit form
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    
    // Check for email validation error
    await waitFor(() => {
      expect(screen.getByText(/email is required/i)).toBeInTheDocument();
    });
  });

  it('should show validation error for invalid email format', async () => {
    renderWithAuth(<LoginForm />);
    
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    // Use an email that passes HTML5 validation but fails our custom validation
    // HTML5 accepts "a@b" but our regex requires a dot in the domain
    const emailInput = screen.getByLabelText(/email/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const submitButton = screen.getByRole('button', { name: /sign in/i });
    
    // Type email that passes HTML5 but fails our regex (no dot in domain)
    await userEvent.type(emailInput, 'test@nodot');
    await userEvent.type(passwordInput, 'password123');
    
    // Submit form by clicking button
    await userEvent.click(submitButton);
    
    // Check for email validation error
    await waitFor(() => {
      expect(screen.getByText(/please enter a valid email address/i)).toBeInTheDocument();
    }, { timeout: 3000 });
  });

  it('should show validation error for empty password', async () => {
    renderWithAuth(<LoginForm />);
    
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    // Fill only email
    await userEvent.type(screen.getByLabelText(/email/i), 'test@example.com');
    
    // Submit form
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    
    // Check for password validation error
    await waitFor(() => {
      expect(screen.getByText(/password is required/i)).toBeInTheDocument();
    });
  });

  it('should show validation error for short password', async () => {
    renderWithAuth(<LoginForm />);
    
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    // Fill short password
    await userEvent.type(screen.getByLabelText(/email/i), 'test@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), '12345');
    
    // Submit form
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    
    // Check for password validation error
    await waitFor(() => {
      expect(screen.getByText(/password must be at least 6 characters/i)).toBeInTheDocument();
    });
  });

  it('should call login with valid credentials', async () => {
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
    
    renderWithAuth(<LoginForm />);
    
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    // Fill valid credentials
    await userEvent.type(screen.getByLabelText(/email/i), 'test@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'password123');
    
    // Submit form
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    
    // Verify login was called with correct credentials
    await waitFor(() => {
      expect(authApi.login).toHaveBeenCalledWith({
        email: 'test@example.com',
        password: 'password123',
      });
    });
  });

  it('should show error message on login failure', async () => {
    (authApi.login as jest.Mock).mockResolvedValue({
      success: false,
      error: {
        error: 'Invalid credentials',
        error_code: 'INVALID_CREDENTIALS',
        message: 'Invalid email or password',
      },
    });
    
    renderWithAuth(<LoginForm />);
    
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    // Fill credentials
    await userEvent.type(screen.getByLabelText(/email/i), 'test@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'wrongpassword');
    
    // Submit form
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    
    // Check for error message
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/invalid email or password/i);
    });
  });

  it('should disable form while loading', async () => {
    // Make login take some time
    (authApi.login as jest.Mock).mockImplementation(() => 
      new Promise(resolve => setTimeout(() => resolve({
        success: true,
        data: {
          access_token: 'test',
          refresh_token: 'test',
          token_type: 'bearer',
          expires_in: 300,
        },
      }), 100))
    );
    
    (authApi.getCurrentUser as jest.Mock).mockResolvedValue({
      success: true,
      data: { id: '1', email: 'test@example.com', name: 'Test' },
    });
    
    renderWithAuth(<LoginForm />);
    
    await waitFor(() => {
      expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    });
    
    // Fill credentials
    await userEvent.type(screen.getByLabelText(/email/i), 'test@example.com');
    await userEvent.type(screen.getByLabelText(/password/i), 'password123');
    
    // Submit form
    await userEvent.click(screen.getByRole('button', { name: /sign in/i }));
    
    // Check that button shows loading state
    await waitFor(() => {
      expect(screen.getByRole('button')).toHaveTextContent(/signing in/i);
      expect(screen.getByRole('button')).toBeDisabled();
    });
  });
});
