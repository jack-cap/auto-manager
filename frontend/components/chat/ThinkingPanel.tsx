'use client';

/**
 * Thinking Panel Component - Shows agent reasoning with streaming content
 */

import React, { useState } from 'react';

interface ThinkingStep {
  id: string;
  type: 'thinking' | 'tool_call' | 'tool_result' | 'ocr' | 'response' | 'routing';
  status: 'started' | 'completed' | 'error';
  message: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

interface ThinkingPanelProps {
  steps: ThinkingStep[];
  isProcessing: boolean;
  streamingContent?: string;
}

function StepItem({ step, isLast }: { step: ThinkingStep; isLast: boolean }) {
  const [isExpanded, setIsExpanded] = useState(step.type === 'thinking'); // Auto-expand thinking blocks
  const isActive = step.status === 'started';
  const hasDetails = Boolean(step.data?.args !== undefined || step.data?.result_preview !== undefined || step.data?.content);

  const getIcon = () => {
    switch (step.type) {
      case 'thinking': return '💭';
      case 'tool_call': return '⚡';
      case 'tool_result': return '✓';
      case 'ocr': return '📄';
      case 'response': return '💬';
      case 'routing': return '🔀';
      default: return '•';
    }
  };

  const getLabel = (): string => {
    switch (step.type) {
      case 'thinking': return 'Reasoning';
      case 'tool_call': return step.data?.tool ? String(step.data.tool) : 'Tool call';
      case 'tool_result': return 'Result';
      case 'ocr': return 'Reading document';
      case 'response': return 'Response';
      case 'routing': return 'Routing';
      default: return step.type;
    }
  };

  // Special styling for thinking blocks
  const isThinking = step.type === 'thinking';

  return (
    <div className="relative">
      {!isLast && (
        <div className="absolute left-[11px] top-6 bottom-0 w-px bg-gray-200" />
      )}
      
      <div className="flex gap-3">
        <div className={`
          w-6 h-6 rounded-full flex items-center justify-center text-xs flex-shrink-0
          ${isActive ? 'bg-blue-100 animate-pulse' : step.status === 'error' ? 'bg-red-100' : isThinking ? 'bg-purple-100' : 'bg-gray-100'}
        `}>
          {isActive ? <span className="animate-spin">◌</span> : <span>{getIcon()}</span>}
        </div>

        <div className="flex-1 min-w-0 pb-4">
          <div 
            className={`flex items-center gap-2 ${hasDetails ? 'cursor-pointer' : ''}`}
            onClick={() => hasDetails && setIsExpanded(!isExpanded)}
          >
            <span className={`text-sm font-medium ${
              step.status === 'error' ? 'text-red-600' : isThinking ? 'text-purple-700' : 'text-gray-700'
            }`}>
              {getLabel()}
            </span>
            {hasDetails && (
              <span className={`text-[10px] text-gray-400 transform transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
                ▶
              </span>
            )}
          </div>
          
          {/* For thinking blocks, show a preview of the message */}
          {isThinking ? (
            <p className="text-xs text-purple-600 mt-0.5 line-clamp-3 italic">
              {step.message}
            </p>
          ) : (
            <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">
              {step.message}
            </p>
          )}

          {isExpanded && hasDetails && (
            <div className="mt-2 space-y-2">
              {step.data?.args !== undefined && (
                <div className="text-xs bg-gray-50 rounded p-2 font-mono overflow-x-auto max-h-32 overflow-y-auto">
                  <pre className="text-gray-600">{JSON.stringify(step.data.args, null, 2)}</pre>
                </div>
              )}
              {step.data?.result_preview !== undefined && (
                <div className="text-xs bg-green-50 rounded p-2 font-mono overflow-x-auto max-h-32 overflow-y-auto">
                  <pre className="text-green-700">{String(step.data.result_preview).slice(0, 500)}</pre>
                </div>
              )}
              {step.data?.content !== undefined && (
                <div className={`text-xs rounded p-2 overflow-x-auto max-h-48 overflow-y-auto ${
                  isThinking ? 'bg-purple-50 border border-purple-100' : 'bg-blue-50'
                }`}>
                  <pre className={`whitespace-pre-wrap ${isThinking ? 'text-purple-800' : 'text-blue-700'}`}>
                    {String(step.data.content).slice(0, 2000)}
                    {String(step.data.content).length > 2000 && '...'}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ThinkingPanel({ steps, isProcessing, streamingContent }: ThinkingPanelProps) {
  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 flex items-center gap-2 flex-shrink-0">
        <span className="text-gray-400">🧠</span>
        <span className="text-sm font-medium text-gray-600">Process</span>
        {isProcessing && (
          <span className="ml-auto flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse" />
            <span className="text-xs text-gray-400">Active</span>
          </span>
        )}
      </div>

      {/* Steps */}
      <div className="flex-1 overflow-y-auto px-4 pb-4 min-h-0">
        {steps.length === 0 && !isProcessing && !streamingContent ? (
          <div className="text-center py-8">
            <p className="text-sm text-gray-400">Agent activity will appear here</p>
          </div>
        ) : (
          <div className="space-y-0">
            {steps.map((step, index) => (
              <StepItem 
                key={step.id} 
                step={step} 
                isLast={index === steps.length - 1 && !isProcessing}
              />
            ))}
            {isProcessing && (
              <div className="flex gap-3 items-center">
                <div className="w-6 h-6 rounded-full bg-blue-100 flex items-center justify-center">
                  <span className="animate-spin text-xs">◌</span>
                </div>
                <span className="text-sm text-gray-500">Processing...</span>
              </div>
            )}
          </div>
        )}

        {/* Streaming content preview */}
        {streamingContent && (
          <div className="mt-4 p-3 bg-blue-50 rounded-lg border border-blue-100">
            <div className="flex items-center gap-2 mb-2">
              <span className="text-blue-500">💬</span>
              <span className="text-xs font-medium text-blue-700">Generating response...</span>
            </div>
            <div className="text-xs text-blue-800 max-h-48 overflow-y-auto whitespace-pre-wrap">
              {streamingContent.slice(0, 1000)}
              {streamingContent.length > 1000 && '...'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
