/**
 * Cash flow chart component showing inflow, outflow, and net.
 * Validates: Requirement 7.3 - Display monthly cash flow (inflow/outflow/net)
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
  ReferenceLine,
} from 'recharts';
import { CashFlowData } from '@/types/dashboard';

interface CashFlowChartProps {
  data: CashFlowData[];
  totalInflow?: number;
  totalOutflow?: number;
  netChange?: number;
  isLoading?: boolean;
  error?: string;
}

export function CashFlowChart({
  data,
  totalInflow,
  totalOutflow,
  netChange,
  isLoading,
  error,
}: CashFlowChartProps) {
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
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Cash Flow</h3>
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

  // Transform data to show outflow as negative for visual clarity
  const chartData = data.map(item => ({
    ...item,
    outflow: -item.outflow, // Make outflow negative for chart
  }));

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Cash Flow</h3>
        <div className="flex gap-6 text-sm">
          {totalInflow !== undefined && (
            <div className="text-right">
              <p className="text-gray-500">Inflow</p>
              <p className="font-semibold text-green-600">{formatCurrency(totalInflow)}</p>
            </div>
          )}
          {totalOutflow !== undefined && (
            <div className="text-right">
              <p className="text-gray-500">Outflow</p>
              <p className="font-semibold text-red-600">{formatCurrency(totalOutflow)}</p>
            </div>
          )}
          {netChange !== undefined && (
            <div className="text-right">
              <p className="text-gray-500">Net</p>
              <p className={`font-semibold ${netChange >= 0 ? 'text-blue-600' : 'text-orange-600'}`}>
                {formatCurrency(netChange)}
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
            <BarChart data={chartData} margin={{ top: 5, right: 20, left: 10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis
                dataKey="period"
                tickFormatter={formatPeriod}
                tick={{ fontSize: 12 }}
                stroke="#9ca3af"
              />
              <YAxis
                tickFormatter={(value) => formatCurrency(Math.abs(value))}
                tick={{ fontSize: 12 }}
                stroke="#9ca3af"
                width={80}
              />
              <Tooltip
                formatter={(value: number, name: string) => [
                  formatCurrency(Math.abs(value)),
                  name === 'outflow' ? 'Outflow' : name === 'inflow' ? 'Inflow' : 'Net',
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
              <ReferenceLine y={0} stroke="#9ca3af" />
              <Bar
                dataKey="inflow"
                name="Inflow"
                fill="#22c55e"
                radius={[4, 4, 0, 0]}
              />
              <Bar
                dataKey="outflow"
                name="Outflow"
                fill="#ef4444"
                radius={[0, 0, 4, 4]}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
