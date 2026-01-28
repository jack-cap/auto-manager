'use client';

/**
 * Error Alert Component
 * Displays errors with suggested actions and retry capability
 * Validates: Requirements 12.1, 12.2, 12.3
 */

import React from 'react';
import { ApiError } from '@/types/api';
import { formatErrorForDisplay, DisplayError } from '@/lib/utils/errors';
import { Button } from './Button';

interface ErrorAlertProps {
  /** The API error to display */
  error: ApiError;
  /** Callback when retry button is clicked */
  onRetry?: () => void;
  /** Callback when dismiss button is clicked */
  onDismiss?: () => void;
  /** Whether a retry is in progress */
  isRetrying?: boolean;
  /** Custom class name */
  className?: string;
}

export function ErrorAlert({
  error,
  onRetry,
  onDismiss,
  isRetrying = false,
  className = '',
}: ErrorAlertProps) {
  const displayError = formatErrorForDisplay(error);

  return (
    <div
      className={`rounded-lg border p-4 ${className}`}
      style={{
        backgroundColor: '#FEF2F2',
        borderColor: '#FECACA',
      }}
      role="alert"
    >
      <div className="flex items-start">
        {/* Error icon */}
        <div className="flex-shrink-0">
          <svg
            className="h-5 w-5 text-red-400"
            viewBox="0 0 20 20"
            fill="currentColor"
            aria-hidden="true"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
              clipRule="evenodd"
            />
          </svg>
        </div>

        {/* Error content */}
        <div className="ml-3 flex-1">
          <h3 className="text-sm font-medium text-red-800">
            {displayError.title}
          </h3>
          <div className="mt-1 text-sm text-red-700">
            <p>{displayError.message}</p>
          </div>
          
          {/* Suggested action */}
          {displayError.action && (
            <div className="mt-2 text-sm text-red-600">
              <p className="font-medium">Suggested action:</p>
              <p>{displayError.action}</p>
            </div>
          )}

          {/* Retry info */}
          {displayError.retryAfter && (
            <p className="mt-2 text-xs text-red-500">
              You can retry in {displayError.retryAfter} seconds
            </p>
          )}

          {/* Action buttons */}
          <div className="mt-3 flex gap-2">
            {displayError.isRetryable && onRetry && (
              <Button
                variant="outline"
                size="sm"
                onClick={onRetry}
                disabled={isRetrying}
              >
                {isRetrying ? 'Retrying...' : 'Retry'}
              </Button>
            )}
            {onDismiss && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onDismiss}
              >
                Dismiss
              </Button>
            )}
          </div>
        </div>

        {/* Dismiss button (X) */}
        {onDismiss && (
          <div className="ml-auto pl-3">
            <button
              type="button"
              className="inline-flex rounded-md p-1.5 text-red-500 hover:bg-red-100 focus:outline-none focus:ring-2 focus:ring-red-600 focus:ring-offset-2"
              onClick={onDismiss}
            >
              <span className="sr-only">Dismiss</span>
              <svg
                className="h-5 w-5"
                viewBox="0 0 20 20"
                fill="currentColor"
                aria-hidden="true"
              >
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Inline error message for form fields
 */
export function InlineError({
  message,
  className = '',
}: {
  message: string;
  className?: string;
}) {
  return (
    <p className={`text-sm text-red-600 mt-1 ${className}`} role="alert">
      {message}
    </p>
  );
}

/**
 * Toast-style error notification
 */
interface ErrorToastProps {
  error: ApiError;
  onDismiss: () => void;
  autoHideDuration?: number;
}

export function ErrorToast({
  error,
  onDismiss,
  autoHideDuration = 5000,
}: ErrorToastProps) {
  const displayError = formatErrorForDisplay(error);

  React.useEffect(() => {
    if (autoHideDuration > 0) {
      const timer = setTimeout(onDismiss, autoHideDuration);
      return () => clearTimeout(timer);
    }
  }, [autoHideDuration, onDismiss]);

  return (
    <div
      className="fixed bottom-4 right-4 max-w-sm bg-white rounded-lg shadow-lg border border-red-200 p-4 z-50"
      role="alert"
    >
      <div className="flex items-start">
        <div className="flex-shrink-0">
          <svg
            className="h-5 w-5 text-red-400"
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z"
              clipRule="evenodd"
            />
          </svg>
        </div>
        <div className="ml-3 flex-1">
          <p className="text-sm font-medium text-gray-900">
            {displayError.title}
          </p>
          <p className="mt-1 text-sm text-gray-500">
            {displayError.message}
          </p>
        </div>
        <button
          type="button"
          className="ml-4 inline-flex text-gray-400 hover:text-gray-500"
          onClick={onDismiss}
        >
          <span className="sr-only">Close</span>
          <svg className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
            <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
          </svg>
        </button>
      </div>
    </div>
  );
}
