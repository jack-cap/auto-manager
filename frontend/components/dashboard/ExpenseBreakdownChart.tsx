/**
 * Expense breakdown pie chart by category.
 * Validates: Requirement 7.5 - Display expense breakdown by category
 */

'use client';

import React from 'react';
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { CategoryBreakdown } from '@/types/dashboard';

interface ExpenseBreakdownChartProps {
  data: CategoryBreakdown[];
  total?: number;
  isLoading?: boolean;
  error?: string;
}

// Color palette for pie chart segments
const COLORS = [
  '#3b82f6', // blue
  '#22c55e', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#8b5cf6', // violet
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#f97316', // orange
  '#84cc16', // lime
  '#6366f1', // indigo
];

export function ExpenseBreakdownChart({
  data,
  total,
  isLoading,
  error,
}: ExpenseBreakdownChartProps) {
  if (isLoading) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-gray-200 rounded w-1/3 mb-4"></div>
          <div className="h-64 bg-gray-100 rounded-full mx-auto w-64"></div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">Expense Breakdown</h3>
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

  // Prepare data for pie chart
  const chartData = data.map((item, index) => ({
    ...item,
    fill: COLORS[index % COLORS.length],
  }));

  const CustomTooltip = ({ active, payload }: any) => {
    if (active && payload && payload.length) {
      const item = payload[0].payload;
      return (
        <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3">
          <p className="font-medium text-gray-900">{item.category}</p>
          <p className="text-gray-600">{formatCurrency(item.amount)}</p>
          <p className="text-gray-500 text-sm">{item.percentage.toFixed(1)}%</p>
        </div>
      );
    }
    return null;
  };

  const renderLegend = (props: any) => {
    const { payload } = props;
    return (
      <ul className="flex flex-wrap justify-center gap-x-4 gap-y-1 mt-4">
        {payload.map((entry: any, index: number) => (
          <li key={`legend-${index}`} className="flex items-center text-sm">
            <span
              className="w-3 h-3 rounded-full mr-1.5"
              style={{ backgroundColor: entry.color }}
            />
            <span className="text-gray-600 truncate max-w-[120px]" title={entry.value}>
              {entry.value}
            </span>
          </li>
        ))}
      </ul>
    );
  };

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-900">Expense Breakdown</h3>
        {total !== undefined && (
          <div className="text-right">
            <p className="text-sm text-gray-500">Total Expenses</p>
            <p className="text-xl font-bold text-gray-900">{formatCurrency(total)}</p>
          </div>
        )}
      </div>

      {data.length === 0 ? (
        <div className="h-64 flex items-center justify-center text-gray-400">
          No data available
        </div>
      ) : (
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="45%"
                innerRadius={60}
                outerRadius={90}
                paddingAngle={2}
                dataKey="amount"
                nameKey="category"
                label={({ percentage }) => `${percentage.toFixed(0)}%`}
                labelLine={false}
              >
                {chartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend content={renderLegend} />
            </PieChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
