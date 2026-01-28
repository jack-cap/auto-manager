/**
 * Tests for CompanyProvider component
 * Validates: Requirements 2.1, 2.2, 2.3, 2.4
 */

import React from 'react';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CompanyProvider, useCompany } from './CompanyProvider';
import { companyApi } from '@/lib/api/company';
import { Company } from '@/types/company';

// Mock the company API
jest.mock('@/lib/api/company', () => ({
  companyApi: {
    getCompanies: jest.fn(),
    getCompany: jest.fn(),
    createCompany: jest.fn(),
    updateCompany: jest.fn(),
    deleteCompany: jest.fn(),
    testConnection: jest.fn(),
  },
}));

// Mock localStorage
const localStorageMock = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: jest.fn((key: string) => store[key] || null),
    setItem: jest.fn((key: string, value: string) => {
      store[key] = value;
    }),
    removeItem: jest.fn((key: string) => {
      delete store[key];
    }),
    clear: jest.fn(() => {
      store = {};
    }),
  };
})();

Object.defineProperty(window, 'localStorage', { value: localStorageMock });

// Test component that uses the context
function TestConsumer() {
  const { 
    companies, 
    selectedCompany, 
    isLoading, 
    error,
    selectCompany,
    addCompany,
    updateCompany,
    removeCompany,
  } = useCompany();

  return (
    <div>
      <div data-testid="loading">{isLoading ? 'loading' : 'loaded'}</div>
      <div data-testid="error">{error || 'no-error'}</div>
      <div data-testid="companies-count">{companies.length}</div>
      <div data-testid="selected-company">{selectedCompany?.name || 'none'}</div>
      <ul data-testid="companies-list">
        {companies.map(c => (
          <li key={c.id} data-testid={`company-${c.id}`}>
            {c.name}
            <button onClick={() => selectCompany(c)}>Select</button>
          </li>
        ))}
      </ul>
      <button 
        data-testid="add-company"
        onClick={() => addCompany({ id: 'new', name: 'New Company', baseUrl: 'http://new.com', isConnected: false })}
      >
        Add
      </button>
      <button 
        data-testid="clear-selection"
        onClick={() => selectCompany(null)}
      >
        Clear
      </button>
    </div>
  );
}

const mockCompanies: Company[] = [
  { id: '1', name: 'Company A', baseUrl: 'http://a.com', isConnected: true },
  { id: '2', name: 'Company B', baseUrl: 'http://b.com', isConnected: false },
];

describe('CompanyProvider', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.clear();
    (companyApi.getCompanies as jest.Mock).mockResolvedValue({
      success: true,
      data: mockCompanies,
    });
  });

  it('loads companies on mount', async () => {
    render(
      <CompanyProvider>
        <TestConsumer />
      </CompanyProvider>
    );

    // Initially loading
    expect(screen.getByTestId('loading')).toHaveTextContent('loading');

    // Wait for companies to load
    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });

    expect(screen.getByTestId('companies-count')).toHaveTextContent('2');
    expect(companyApi.getCompanies).toHaveBeenCalledTimes(1);
  });

  it('handles API error gracefully', async () => {
    (companyApi.getCompanies as jest.Mock).mockResolvedValue({
      success: false,
      error: { message: 'Failed to fetch' },
    });

    render(
      <CompanyProvider>
        <TestConsumer />
      </CompanyProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });

    expect(screen.getByTestId('error')).toHaveTextContent('Failed to fetch');
    expect(screen.getByTestId('companies-count')).toHaveTextContent('0');
  });

  it('allows selecting a company', async () => {
    const user = userEvent.setup();

    render(
      <CompanyProvider>
        <TestConsumer />
      </CompanyProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });

    // Initially no company selected
    expect(screen.getByTestId('selected-company')).toHaveTextContent('none');

    // Select first company
    const selectButtons = screen.getAllByText('Select');
    await user.click(selectButtons[0]);

    expect(screen.getByTestId('selected-company')).toHaveTextContent('Company A');
    expect(localStorageMock.setItem).toHaveBeenCalledWith(
      'bookkeeper_selected_company',
      '"1"'
    );
  });

  it('allows clearing company selection', async () => {
    const user = userEvent.setup();

    render(
      <CompanyProvider>
        <TestConsumer />
      </CompanyProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });

    // Select a company first
    const selectButtons = screen.getAllByText('Select');
    await user.click(selectButtons[0]);
    expect(screen.getByTestId('selected-company')).toHaveTextContent('Company A');

    // Clear selection
    await user.click(screen.getByTestId('clear-selection'));
    expect(screen.getByTestId('selected-company')).toHaveTextContent('none');
    expect(localStorageMock.removeItem).toHaveBeenCalledWith('bookkeeper_selected_company');
  });

  it('restores selected company from localStorage', async () => {
    localStorageMock.getItem.mockReturnValue('"1"');

    render(
      <CompanyProvider>
        <TestConsumer />
      </CompanyProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });

    expect(screen.getByTestId('selected-company')).toHaveTextContent('Company A');
  });

  it('clears stored company if it no longer exists', async () => {
    localStorageMock.getItem.mockReturnValue('"nonexistent"');

    render(
      <CompanyProvider>
        <TestConsumer />
      </CompanyProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });

    expect(screen.getByTestId('selected-company')).toHaveTextContent('none');
    expect(localStorageMock.removeItem).toHaveBeenCalledWith('bookkeeper_selected_company');
  });

  it('allows adding a company to the list', async () => {
    const user = userEvent.setup();

    render(
      <CompanyProvider>
        <TestConsumer />
      </CompanyProvider>
    );

    await waitFor(() => {
      expect(screen.getByTestId('loading')).toHaveTextContent('loaded');
    });

    expect(screen.getByTestId('companies-count')).toHaveTextContent('2');

    await user.click(screen.getByTestId('add-company'));

    expect(screen.getByTestId('companies-count')).toHaveTextContent('3');
  });

  it('throws error when useCompany is used outside provider', () => {
    // Suppress console.error for this test
    const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

    expect(() => {
      render(<TestConsumer />);
    }).toThrow('useCompany must be used within a CompanyProvider');

    consoleSpy.mockRestore();
  });
});
