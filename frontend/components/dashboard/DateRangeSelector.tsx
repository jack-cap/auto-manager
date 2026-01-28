/**
 * Date range selector component for dashboard filtering.
 * Validates: Requirement 7.7 - Allow date range filtering on all dashboard charts
 */

'use client';

import React, { useState, useCallback } from 'react';

interface DateRangeSelectorProps {
  startDate?: string;
  endDate?: string;
  onDateChange: (startDate: string | undefined, endDate: string | undefined) => void;
  className?: string;
}

type PresetRange = '7d' | '30d' | '90d' | '1y' | 'ytd' | 'custom';

export function DateRangeSelector({
  startDate,
  endDate,
  onDateChange,
  className = '',
}: DateRangeSelectorProps) {
  const [activePreset, setActivePreset] = useState<PresetRange>('30d');
  const [showCustom, setShowCustom] = useState(false);

  const getPresetDates = useCallback((preset: PresetRange): { start: string; end: string } => {
    const today = new Date();
    const end = today.toISOString().split('T')[0];
    let start: Date;

    switch (preset) {
      case '7d':
        start = new Date(today);
        start.setDate(start.getDate() - 7);
        break;
      case '30d':
        start = new Date(today);
        start.setDate(start.getDate() - 30);
        break;
      case '90d':
        start = new Date(today);
        start.setDate(start.getDate() - 90);
        break;
      case '1y':
        start = new Date(today);
        start.setFullYear(start.getFullYear() - 1);
        break;
      case 'ytd':
        start = new Date(today.getFullYear(), 0, 1);
        break;
      default:
        start = new Date(today);
        start.setDate(start.getDate() - 30);
    }

    return {
      start: start.toISOString().split('T')[0],
      end,
    };
  }, []);

  const handlePresetClick = useCallback((preset: PresetRange) => {
    setActivePreset(preset);
    if (preset === 'custom') {
      setShowCustom(true);
    } else {
      setShowCustom(false);
      const { start, end } = getPresetDates(preset);
      onDateChange(start, end);
    }
  }, [getPresetDates, onDateChange]);

  const handleCustomDateChange = useCallback((type: 'start' | 'end', value: string) => {
    if (type === 'start') {
      onDateChange(value || undefined, endDate);
    } else {
      onDateChange(startDate, value || undefined);
    }
  }, [startDate, endDate, onDateChange]);

  const presets: { key: PresetRange; label: string }[] = [
    { key: '7d', label: '7 Days' },
    { key: '30d', label: '30 Days' },
    { key: '90d', label: '90 Days' },
    { key: '1y', label: '1 Year' },
    { key: 'ytd', label: 'YTD' },
    { key: 'custom', label: 'Custom' },
  ];

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <div className="flex rounded-lg border border-gray-200 bg-white overflow-hidden">
        {presets.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => handlePresetClick(key)}
            className={`px-3 py-1.5 text-sm font-medium transition-colors ${
              activePreset === key
                ? 'bg-blue-600 text-white'
                : 'text-gray-600 hover:bg-gray-50'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {showCustom && (
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={startDate || ''}
            onChange={(e) => handleCustomDateChange('start', e.target.value)}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="Start date"
          />
          <span className="text-gray-400">to</span>
          <input
            type="date"
            value={endDate || ''}
            onChange={(e) => handleCustomDateChange('end', e.target.value)}
            className="px-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            aria-label="End date"
          />
        </div>
      )}
    </div>
  );
}
