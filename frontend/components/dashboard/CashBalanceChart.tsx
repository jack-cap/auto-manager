/**
 * Cash balance chart component.
 * Validates: Requirement 7.1 - Display current cash balance
 * Validates: Requirement 7.2 - Display cash balance over time chart
 */

'use client';

import React from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { CashBalanceHistoryItem } from '@/types/dashboard';

interface CashBalanceChartProps {
  data: CashBalanceHistoryItem[];
  currentBalance?: number;
  isLoading?: boolean;
  error?: string;
}

export function CashBalanceChart({
  data,
  currentBalance,
  isLoading,
  error,
}: CashBalanceChartProps) {
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
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Cash Balance</h3>
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

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  // Sample every nth point if there are too many data points
  const maxPoints = 30;
  const sampledData = data.length > maxPoints
    ? data.filter((_, i) => i % Math.ceil(data.length / maxPoints) === 0 || i === data.length - 1)
    : data;

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Cash Balance</h3>
        {currentBalance !== undefined && (
          <div className="text-right">
            <p className="text-sm text-gray-500">Current Balance</p>
            <p className={`text-2xl font-bold ${currentBalance >= 0 ? 'text-green-600' : 'text-red-600'}`}>
              {formatCurrency(currentBalance)}
            </p>
          </div>
        )}
      </div>

      {data.length === 0 ? (
        <div className="h-64 flex items-center justify-center text-gray-400">
          No data available
        </div>
      ) : (
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={sampledData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="date"
                tickFormatter={formatDate}
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
                formatter={(value) => [formatCurrency(value as number), 'Balance']}
                labelFormatter={(label) => new Date(label).toLocaleDateString('en-US', {
                  weekday: 'short',
                  year: 'numeric',
                  month: 'short',
                  day: 'numeric',
                })}
                contentStyle={{
                  backgroundColor: 'white',
                  border: '1px solid #e5e7eb',
                  borderRadius: '8px',
                  boxShadow: '0 2px 4px rgba(0,0,0,0.1)',
                }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="balance"
                name="Cash Balance"
                stroke="#3b82f6"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 6, fill: '#3b82f6' }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
