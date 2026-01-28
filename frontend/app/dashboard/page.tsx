/**
 * Dashboard page with financial visualizations.
 * Validates: Requirements 7.1-7.7
 */

'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useCompany } from '@/components/company';
import { ProtectedRoute } from '@/components/auth';
import {
  CashBalanceChart,
  CashFlowChart,
  IncomeExpenseChart,
  ExpenseBreakdownChart,
  DateRangeSelector,
} from '@/components/dashboard';
import { dashboardApi } from '@/lib/api';
import { PageLoading, CardSkeleton, ChartSkeleton } from '@/components/ui';
import {
  CashBalanceResponse,
  CashBalanceHistoryResponse,
  CashFlowResponse,
  IncomeExpenseResponse,
  ExpenseBreakdownResponse,
} from '@/types/dashboard';

function DashboardContent() {
  const { selectedCompany, isLoading: companyLoading } = useCompany();
  
  // Date range state
  const [startDate, setStartDate] = useState<string | undefined>();
  const [endDate, setEndDate] = useState<string | undefined>();
  
  // Data states
  const [cashBalance, setCashBalance] = useState<CashBalanceResponse | null>(null);
  const [cashBalanceHistory, setCashBalanceHistory] = useState<CashBalanceHistoryResponse | null>(null);
  const [cashFlow, setCashFlow] = useState<CashFlowResponse | null>(null);
  const [incomeExpense, setIncomeExpense] = useState<IncomeExpenseResponse | null>(null);
  const [expenseBreakdown, setExpenseBreakdown] = useState<ExpenseBreakdownResponse | null>(null);
  
  // Loading and error states
  const [isLoading, setIsLoading] = useState(true);
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Initialize with 30-day range
  useEffect(() => {
    const today = new Date();
    const thirtyDaysAgo = new Date(today);
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);
    
    setEndDate(today.toISOString().split('T')[0]);
    setStartDate(thirtyDaysAgo.toISOString().split('T')[0]);
  }, []);

  const fetchDashboardData = useCallback(async () => {
    if (!selectedCompany?.id) {
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setErrors({});

    const companyId = selectedCompany.id;

    // Fetch all data in parallel
    const results = await Promise.allSettled([
      dashboardApi.getCashBalance(companyId),
      dashboardApi.getCashBalanceHistory(companyId, startDate, endDate),
      dashboardApi.getCashFlow(companyId, startDate, endDate),
      dashboardApi.getIncomeExpense(companyId, startDate, endDate),
      dashboardApi.getExpenseBreakdown(companyId, startDate, endDate),
    ]);

    // Process results
    const newErrors: Record<string, string> = {};

    if (results[0].status === 'fulfilled' && results[0].value.success && results[0].value.data) {
      setCashBalance(results[0].value.data);
    } else {
      const err = results[0].status === 'rejected' 
        ? (results[0].reason?.message || 'Request failed')
        : (results[0].value.error?.message || 'Failed to load cash balance');
      newErrors.cashBalance = err;
      console.error('Cash balance error:', err);
    }

    if (results[1].status === 'fulfilled' && results[1].value.success && results[1].value.data) {
      setCashBalanceHistory(results[1].value.data);
    } else {
      const err = results[1].status === 'rejected'
        ? (results[1].reason?.message || 'Request failed')
        : (results[1].value.error?.message || 'Failed to load balance history');
      newErrors.cashBalanceHistory = err;
      console.error('Cash balance history error:', err);
    }

    if (results[2].status === 'fulfilled' && results[2].value.success && results[2].value.data) {
      setCashFlow(results[2].value.data);
    } else {
      const err = results[2].status === 'rejected'
        ? (results[2].reason?.message || 'Request failed')
        : (results[2].value.error?.message || 'Failed to load cash flow');
      newErrors.cashFlow = err;
      console.error('Cash flow error:', err);
    }

    if (results[3].status === 'fulfilled' && results[3].value.success && results[3].value.data) {
      setIncomeExpense(results[3].value.data);
    } else {
      const err = results[3].status === 'rejected'
        ? (results[3].reason?.message || 'Request failed')
        : (results[3].value.error?.message || 'Failed to load income/expense');
      newErrors.incomeExpense = err;
      console.error('Income/expense error:', err);
    }

    if (results[4].status === 'fulfilled' && results[4].value.success && results[4].value.data) {
      setExpenseBreakdown(results[4].value.data);
    } else {
      const err = results[4].status === 'rejected'
        ? (results[4].reason?.message || 'Request failed')
        : (results[4].value.error?.message || 'Failed to load expense breakdown');
      newErrors.expenseBreakdown = err;
      console.error('Expense breakdown error:', err);
    }

    setErrors(newErrors);
    setIsLoading(false);
  }, [selectedCompany?.id, startDate, endDate]);

  useEffect(() => {
    if (startDate && endDate) {
      fetchDashboardData();
    }
  }, [fetchDashboardData, startDate, endDate]);

  const handleDateChange = useCallback((newStart: string | undefined, newEnd: string | undefined) => {
    setStartDate(newStart);
    setEndDate(newEnd);
  }, []);

  if (companyLoading) {
    return <PageLoading message="Loading dashboard..." />;
  }

  if (!selectedCompany) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <h2 className="text-xl font-semibold text-gray-900 mb-2">No Company Selected</h2>
          <p className="text-gray-600">Please select a company to view the dashboard.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="mb-8">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
              <p className="text-gray-600 mt-1">{selectedCompany.name}</p>
            </div>
            <DateRangeSelector
              startDate={startDate}
              endDate={endDate}
              onDateChange={handleDateChange}
            />
          </div>
        </div>

        {/* Error Banner */}
        {Object.keys(errors).length > 0 && !isLoading && (
          <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg">
            <h3 className="text-red-800 font-medium mb-2">Some data failed to load:</h3>
            <ul className="text-sm text-red-700 list-disc list-inside">
              {Object.entries(errors).map(([key, error]) => (
                <li key={key}>{key}: {error}</li>
              ))}
            </ul>
          </div>
        )}

        {/* Summary Cards */}
        {isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
            <CardSkeleton lines={2} />
            <CardSkeleton lines={2} />
            <CardSkeleton lines={2} />
          </div>
        ) : cashBalance && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
            <div className="bg-white rounded-lg shadow p-6">
              <p className="text-sm text-gray-500">Total Cash Balance</p>
              <p className={`text-2xl font-bold ${cashBalance.total >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                {new Intl.NumberFormat('en-US', {
                  style: 'currency',
                  currency: 'USD',
                }).format(cashBalance.total)}
              </p>
              <p className="text-xs text-gray-400 mt-1">As of {cashBalance.as_of_date}</p>
            </div>
            
            {cashFlow && (
              <>
                <div className="bg-white rounded-lg shadow p-6">
                  <p className="text-sm text-gray-500">Net Cash Flow</p>
                  <p className={`text-2xl font-bold ${cashFlow.net_change >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                    {new Intl.NumberFormat('en-US', {
                      style: 'currency',
                      currency: 'USD',
                    }).format(cashFlow.net_change)}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">Selected period</p>
                </div>
                
                <div className="bg-white rounded-lg shadow p-6">
                  <p className="text-sm text-gray-500">Total Expenses</p>
                  <p className="text-2xl font-bold text-gray-900">
                    {new Intl.NumberFormat('en-US', {
                      style: 'currency',
                      currency: 'USD',
                    }).format(cashFlow.total_outflow)}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">Selected period</p>
                </div>
              </>
            )}
          </div>
        )}

        {/* Charts Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Cash Balance History */}
          <div className="lg:col-span-2">
            {isLoading ? (
              <ChartSkeleton height={300} />
            ) : (
              <CashBalanceChart
                data={cashBalanceHistory?.items || []}
                currentBalance={cashBalance?.total}
                isLoading={isLoading}
                error={errors.cashBalanceHistory}
              />
            )}
          </div>

          {/* Cash Flow */}
          {isLoading ? (
            <ChartSkeleton height={250} />
          ) : (
            <CashFlowChart
              data={cashFlow?.items || []}
              totalInflow={cashFlow?.total_inflow}
              totalOutflow={cashFlow?.total_outflow}
              netChange={cashFlow?.net_change}
              isLoading={isLoading}
              error={errors.cashFlow}
            />
          )}

          {/* Income vs Expense */}
          {isLoading ? (
            <ChartSkeleton height={250} />
          ) : (
            <IncomeExpenseChart
              data={incomeExpense?.items || []}
              totalIncome={incomeExpense?.total_income}
              totalExpense={incomeExpense?.total_expense}
              netProfit={incomeExpense?.net_profit}
              isLoading={isLoading}
              error={errors.incomeExpense}
            />
          )}

          {/* Expense Breakdown */}
          <div className="lg:col-span-2">
            {isLoading ? (
              <ChartSkeleton height={300} />
            ) : (
              <ExpenseBreakdownChart
                data={expenseBreakdown?.categories || []}
                total={expenseBreakdown?.total}
                isLoading={isLoading}
                error={errors.expenseBreakdown}
              />
            )}
          </div>
        </div>

        {/* Refresh Button */}
        <div className="mt-8 text-center">
          <button
            onClick={fetchDashboardData}
            disabled={isLoading}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {isLoading ? 'Loading...' : 'Refresh Data'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <ProtectedRoute>
      <DashboardContent />
    </ProtectedRoute>
  );
}
