'use client';

/**
 * Loading Components
 * Provides consistent loading states across the application
 * Validates: Requirements All (Final Integration)
 */

import React from 'react';

interface SpinnerProps {
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

export function Spinner({ size = 'md', className = '' }: SpinnerProps) {
  const sizeClasses = {
    sm: 'h-4 w-4',
    md: 'h-8 w-8',
    lg: 'h-12 w-12',
  };

  return (
    <svg
      className={`animate-spin ${sizeClasses[size]} ${className}`}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

interface LoadingOverlayProps {
  message?: string;
}

export function LoadingOverlay({ message = 'Loading...' }: LoadingOverlayProps) {
  return (
    <div className="fixed inset-0 bg-white/80 backdrop-blur-sm flex items-center justify-center z-50">
      <div className="flex flex-col items-center gap-4">
        <Spinner size="lg" className="text-primary-600" />
        <p className="text-gray-600 font-medium">{message}</p>
      </div>
    </div>
  );
}

interface PageLoadingProps {
  message?: string;
}

export function PageLoading({ message = 'Loading...' }: PageLoadingProps) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="flex flex-col items-center gap-4">
        <Spinner size="lg" className="text-primary-600" />
        <p className="text-gray-600">{message}</p>
      </div>
    </div>
  );
}

interface InlineLoadingProps {
  message?: string;
  className?: string;
}

export function InlineLoading({ message, className = '' }: InlineLoadingProps) {
  return (
    <div className={`flex items-center gap-2 ${className}`}>
      <Spinner size="sm" className="text-primary-600" />
      {message && <span className="text-sm text-gray-600">{message}</span>}
    </div>
  );
}

interface SkeletonProps {
  className?: string;
  variant?: 'text' | 'circular' | 'rectangular';
  width?: string | number;
  height?: string | number;
}

export function Skeleton({
  className = '',
  variant = 'text',
  width,
  height,
}: SkeletonProps) {
  const baseClasses = 'animate-pulse bg-gray-200';
  
  const variantClasses = {
    text: 'rounded',
    circular: 'rounded-full',
    rectangular: 'rounded-md',
  };

  const style: React.CSSProperties = {};
  if (width) style.width = typeof width === 'number' ? `${width}px` : width;
  if (height) style.height = typeof height === 'number' ? `${height}px` : height;

  return (
    <div
      className={`${baseClasses} ${variantClasses[variant]} ${className}`}
      style={style}
    />
  );
}

interface CardSkeletonProps {
  lines?: number;
}

export function CardSkeleton({ lines = 3 }: CardSkeletonProps) {
  return (
    <div className="bg-white rounded-lg shadow p-6 space-y-4">
      <Skeleton variant="text" className="h-6 w-1/3" />
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton key={i} variant="text" className="h-4 w-full" />
      ))}
    </div>
  );
}

interface ChartSkeletonProps {
  height?: number;
}

export function ChartSkeleton({ height = 300 }: ChartSkeletonProps) {
  return (
    <div className="bg-white rounded-lg shadow p-6">
      <Skeleton variant="text" className="h-6 w-1/4 mb-4" />
      <Skeleton variant="rectangular" height={height} className="w-full" />
    </div>
  );
}

export default {
  Spinner,
  LoadingOverlay,
  PageLoading,
  InlineLoading,
  Skeleton,
  CardSkeleton,
  ChartSkeleton,
};
