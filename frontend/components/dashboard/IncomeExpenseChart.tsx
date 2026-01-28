/**
 * Income vs Expense comparison chart.
 * Validates: Requirement 7.4 - Display income vs expense comparison
 */

'use client';

import React from 'react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { IncomeExpenseData } from '@/types/dashboard';

interface IncomeExpenseChartProps {
  data: IncomeExpenseData[];
  totalIncome?: number;
  totalExpense?: number;
  netProfit?: number;
  isLoading?: boolean;
  error?: string;
}

export function IncomeExpenseChart({
  data,
  totalIncome,
  totalExpense,
  netProfit,
  isLoading,
  error,
}: IncomeExpenseChartProps) {
  if (isLoading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 rounded w-1/3 mb-4"></div>
          <div className="h-64 bg-gray-100 rounded"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Income vs Expense</h3>
        <div className="h-64 flex items-center justify-center text-red-500">
          {error}
        </div>
      </div>
    );
  }

  const formatCurrency = (value: number) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);
  };

  const formatPeriod = (period: string) => {
    const [year, month] = period.split('-');
    const date = new Date(parseInt(year), parseInt(month) - 1);
    return date.toLocaleDateString('en-US', { month: 'short', year: '2-digit' });
  };

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Income vs Expense</h3>
        <div className="flex gap-6 text-sm">
          {totalIncome !== undefined && (
            <div className="text-right">
              <p className="text-gray-500">Total Income</p>
              <p className="font-semibold text-green-600">{formatCurrency(totalIncome)}</p>
            </div>
          )}
          {totalExpense !== undefined && (
            <div className="text-right">
              <p className="text-gray-500">Total Expense</p>
              <p className="font-semibold text-red-600">{formatCurrency(totalExpense)}</p>
            </div>
          )}
          {netProfit !== undefined && (
            <div className="text-right">
              <p className="text-gray-500">Net Profit</p>
              <p className={`font-semibold ${netProfit >= 0 ? 'text-blue-600' : 'text-orange-600'}`}>
                {formatCurrency(netProfit)}
              </p>
            </div>
          )}
        </div>
      </div>

      {data.length === 0 ? (
        <div className="h-64 flex items-center justify-center text-gray-400">
          No data available
        </div>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="period"
                tickFormatter={formatPeriod}
                tick={{ fontSize: 12 }}
                stroke="#9ca3af"
              />
              <YAxis
                tickFormatter={(value) => formatCurrency(value)}
                tick={{ fontSize: 12 }}
                stroke="#9ca3af"
                width={80}
              />
              <Tooltip
                formatter={(value: number, name: string) => [
                  formatCurrency(value),
                  name === 'income' ? 'Income' : 'Expense',
                ]}
                labelFormatter={(label) => formatPeriod(label)}
                contentStyle={{
                  backgroundColor: 'white',
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
                }}
              />
              <Legend />
              <Bar
                dataKey="income"
                name="Income"
                fill="#22c55e"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="expense"
                name="Expense"
                fill="#ef4444"
                radius={[4, 4, 0, 0]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
