/**
 * Tests for CompanySelector component
 * Validates: Requirements 2.2
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { CompanySelector } from './CompanySelector';
import { CompanyProvider } from './CompanyProvider';
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

const mockCompanies: Company[] = [
  { id: '1', name: 'Company A', baseUrl: 'http://a.com', isConnected: true },
  { id: '2', name: 'Company B', baseUrl: 'http://b.com', isConnected: false },
];

function renderWithProvider(ui: React.ReactElement) {
  return render(
    <CompanyProvider>
      {ui}
    </CompanyProvider>
  );
}

describe('CompanySelector', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.clear();
    (companyApi.getCompanies as jest.Mock).mockResolvedValue({
      success: true,
      data: mockCompanies,
    });
  });

  it('shows loading state initially', () => {
    renderWithProvider(<CompanySelector />);
    expect(screen.getByText('Loading companies...')).toBeInTheDocument();
  });

  it('shows placeholder when no company is selected', async () => {
    renderWithProvider(<CompanySelector />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('Select a company')).toBeInTheDocument();
  });

  it('shows message when no companies are configured', async () => {
    (companyApi.getCompanies as jest.Mock).mockResolvedValue({
      success: true,
      data: [],
    });

    renderWithProvider(<CompanySelector />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    expect(screen.getByText('No companies configured')).toBeInTheDocument();
  });

  it('opens dropdown when clicked', async () => {
    const user = userEvent.setup();
    renderWithProvider(<CompanySelector />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    // Click to open dropdown
    await user.click(screen.getByRole('button'));

    // Should show company options
    expect(screen.getByText('Company A')).toBeInTheDocument();
    expect(screen.getByText('Company B')).toBeInTheDocument();
  });

  it('selects a company when clicked', async () => {
    const user = userEvent.setup();
    const onCompanyChange = jest.fn();
    
    renderWithProvider(<CompanySelector onCompanyChange={onCompanyChange} />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole('button'));

    // Click on Company A
    await user.click(screen.getByText('Company A'));

    // Should call onCompanyChange
    expect(onCompanyChange).toHaveBeenCalledWith(mockCompanies[0]);

    // Dropdown should close and show selected company
    expect(screen.getByRole('button')).toHaveTextContent('Company A');
  });

  it('shows clear selection option when a company is selected', async () => {
    const user = userEvent.setup();
    localStorageMock.getItem.mockReturnValue('"1"');
    
    renderWithProvider(<CompanySelector />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    // Should show selected company
    expect(screen.getByRole('button')).toHaveTextContent('Company A');

    // Open dropdown
    await user.click(screen.getByRole('button'));

    // Should show clear selection option
    expect(screen.getByText('Clear selection')).toBeInTheDocument();
  });

  it('clears selection when clear option is clicked', async () => {
    const user = userEvent.setup();
    const onCompanyChange = jest.fn();
    localStorageMock.getItem.mockReturnValue('"1"');
    
    renderWithProvider(<CompanySelector onCompanyChange={onCompanyChange} />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole('button'));

    // Click clear selection
    await user.click(screen.getByText('Clear selection'));

    // Should call onCompanyChange with null
    expect(onCompanyChange).toHaveBeenCalledWith(null);

    // Should show placeholder
    expect(screen.getByText('Select a company')).toBeInTheDocument();
  });

  it('closes dropdown when clicking outside', async () => {
    const user = userEvent.setup();
    renderWithProvider(
      <div>
        <CompanySelector />
        <div data-testid="outside">Outside</div>
      </div>
    );

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole('button'));
    
    // Dropdown should be open (listbox should be visible)
    expect(screen.getByRole('listbox')).toBeInTheDocument();

    // Click outside
    await user.click(screen.getByTestId('outside'));

    // Dropdown should close
    await waitFor(() => {
      expect(screen.queryByRole('listbox')).not.toBeInTheDocument();
    });
  });

  it('shows connection status indicator', async () => {
    const user = userEvent.setup();
    renderWithProvider(<CompanySelector />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    // Open dropdown
    await user.click(screen.getByRole('button'));

    // Both companies should be visible with their URLs
    expect(screen.getByText('http://a.com')).toBeInTheDocument();
    expect(screen.getByText('http://b.com')).toBeInTheDocument();
  });

  it('applies custom className', async () => {
    renderWithProvider(<CompanySelector className="custom-class" />);

    await waitFor(() => {
      expect(screen.queryByText('Loading companies...')).not.toBeInTheDocument();
    });

    const container = screen.getByRole('button').parentElement;
    expect(container).toHaveClass('custom-class');
  });
});
