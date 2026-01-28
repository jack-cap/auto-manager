'use client';

/**
 * Connection Status Component
 * Displays the status of backend services (LMStudio, Ollama)
 * Validates: Requirements 12.1, 12.2, 12.3
 */

import React, { useState, useEffect, useCallback } from 'react';
import { healthApi, HealthResponse, ServiceStatus } from '@/lib/api/health';

interface ConnectionStatusProps {
  /** How often to check health (ms). Default: 30000 (30s) */
  pollInterval?: number;
  /** Whether to show detailed status. Default: false */
  showDetails?: boolean;
  /** Callback when health status changes */
  onStatusChange?: (health: HealthResponse) => void;
}

type StatusIndicator = 'connected' | 'disconnected' | 'checking';

function StatusDot({ status }: { status: StatusIndicator }) {
  const colors = {
    connected: 'bg-green-500',
    disconnected: 'bg-red-500',
    checking: 'bg-yellow-500 animate-pulse',
  };

  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${colors[status]}`}
      aria-label={status}
    />
  );
}

function ServiceStatusItem({
  name,
  status,
  showDetails,
}: {
  name: string;
  status: ServiceStatus | null;
  showDetails: boolean;
}) {
  const indicator: StatusIndicator = status === null
    ? 'checking'
    : status.available
    ? 'connected'
    : 'disconnected';

  return (
    <div className="flex items-center gap-2">
      <StatusDot status={indicator} />
      <span className="text-sm text-gray-600">{name}</span>
      {showDetails && status && (
        <span className="text-xs text-gray-400">
          {status.available
            ? status.latency_ms
              ? `${Math.round(status.latency_ms)}ms`
              : 'OK'
            : status.message || 'Unavailable'}
        </span>
      )}
    </div>
  );
}

export function ConnectionStatus({
  pollInterval = 30000,
  showDetails = false,
  onStatusChange,
}: ConnectionStatusProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [isChecking, setIsChecking] = useState(true);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const checkHealth = useCallback(async () => {
    setIsChecking(true);
    try {
      const response = await healthApi.getHealth();
      if (response.success && response.data) {
        setHealth(response.data);
        onStatusChange?.(response.data);
      }
    } catch (error) {
      console.error('Health check failed:', error);
    } finally {
      setIsChecking(false);
      setLastChecked(new Date());
    }
  }, [onStatusChange]);

  useEffect(() => {
    // Initial check
    checkHealth();

    // Set up polling
    const interval = setInterval(checkHealth, pollInterval);

    return () => clearInterval(interval);
  }, [checkHealth, pollInterval]);

  const overallStatus: StatusIndicator = isChecking
    ? 'checking'
    : health?.status === 'healthy'
    ? 'connected'
    : health?.status === 'degraded'
    ? 'checking' // Use yellow for degraded
    : 'disconnected';

  return (
    <div className="flex flex-col gap-2">
      {/* Overall status */}
      <div className="flex items-center gap-2">
        <StatusDot status={overallStatus} />
        <span className="text-sm font-medium">
          {isChecking
            ? 'Checking...'
            : health?.status === 'healthy'
            ? 'All services connected'
            : health?.status === 'degraded'
            ? 'Some services unavailable'
            : 'Services unavailable'}
        </span>
      </div>

      {/* Detailed status */}
      {showDetails && health && (
        <div className="ml-4 space-y-1">
          <ServiceStatusItem
            name="Database"
            status={health.services.database}
            showDetails={showDetails}
          />
          <ServiceStatusItem
            name="LMStudio (OCR)"
            status={health.services.lmstudio}
            showDetails={showDetails}
          />
          <ServiceStatusItem
            name="Ollama (LLM)"
            status={health.services.ollama}
            showDetails={showDetails}
          />
          {lastChecked && (
            <p className="text-xs text-gray-400 mt-2">
              Last checked: {lastChecked.toLocaleTimeString()}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Compact connection indicator for headers/toolbars
 */
export function ConnectionIndicator({
  pollInterval = 30000,
}: {
  pollInterval?: number;
}) {
  const [status, setStatus] = useState<'healthy' | 'degraded' | 'unhealthy' | 'checking'>('checking');

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const response = await healthApi.getHealth();
        if (response.success && response.data) {
          setStatus(response.data.status);
        } else {
          setStatus('unhealthy');
        }
      } catch {
        setStatus('unhealthy');
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, pollInterval);
    return () => clearInterval(interval);
  }, [pollInterval]);

  const colors = {
    healthy: 'bg-green-500',
    degraded: 'bg-yellow-500',
    unhealthy: 'bg-red-500',
    checking: 'bg-gray-400 animate-pulse',
  };

  const titles = {
    healthy: 'All services connected',
    degraded: 'Some services unavailable',
    unhealthy: 'Services unavailable',
    checking: 'Checking connection...',
  };

  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full ${colors[status]}`}
      title={titles[status]}
      aria-label={titles[status]}
    />
  );
}
