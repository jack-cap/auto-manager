'use client';

/**
 * ThinkBlock Component
 * Parses and renders <think>, <canvas>, and regular content
 */

import React, { useState } from 'react';

interface ThinkBlockProps {
  content: string;
  defaultExpanded?: boolean;
}

export function ThinkBlock({ content, defaultExpanded = false }: ThinkBlockProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);

  return (
    <div className="my-2">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-700 transition-colors"
      >
        <span className={`transform transition-transform text-[10px] ${isExpanded ? 'rotate-90' : ''}`}>
          ▶
        </span>
        <span className="flex items-center gap-1">
          <span className="opacity-60">💭</span>
          <span>View reasoning</span>
        </span>
      </button>
      {isExpanded && (
        <div className="mt-2 pl-4 border-l-2 border-gray-200 text-sm text-gray-600 leading-relaxed">
          {content}
        </div>
      )}
    </div>
  );
}

export interface ParsedContent {
  type: 'text' | 'think' | 'canvas';
  content: string;
}

/**
 * Parse message content and extract think blocks and canvas blocks
 * Handles both proper <think>...</think> tags and malformed cases like "content</think>response"
 */
export function parseMessageContent(content: string): {
  parts: ParsedContent[];
  canvasContent: string | null;
} {
  const parts: ParsedContent[] = [];
  let canvasContent: string | null = null;
  let workingContent = content;
  
  // First, handle malformed case: content that ends with </think> without opening tag
  // Pattern: "thinking content</think>actual response"
  const malformedThinkMatch = /^([\s\S]*?)<\/think>([\s\S]*)$/i.exec(workingContent);
  if (malformedThinkMatch && !workingContent.toLowerCase().includes('<think>')) {
    const thinkContent = malformedThinkMatch[1].trim();
    const afterContent = malformedThinkMatch[2].trim();
    
    if (thinkContent) {
      parts.push({ type: 'think', content: thinkContent });
    }
    if (afterContent) {
      // Process remaining content for canvas tags
      workingContent = afterContent;
    } else {
      return { parts, canvasContent };
    }
  }
  
  // Combined regex for both think and canvas tags (proper format)
  const tagRegex = /<(think|canvas)>([\s\S]*?)<\/\1>/gi;
  
  let lastIndex = 0;
  let match;

  while ((match = tagRegex.exec(workingContent)) !== null) {
    // Add text before the tag
    if (match.index > lastIndex) {
      const textBefore = workingContent.slice(lastIndex, match.index).trim();
      if (textBefore) {
        parts.push({ type: 'text', content: textBefore });
      }
    }
    
    const tagType = match[1].toLowerCase() as 'think' | 'canvas';
    const tagContent = match[2].trim();
    
    if (tagType === 'canvas') {
      canvasContent = tagContent;
    } else if (tagContent) {
      parts.push({ type: tagType, content: tagContent });
    }
    
    lastIndex = match.index + match[0].length;
  }

  // Add remaining text
  if (lastIndex < workingContent.length) {
    const remainingText = workingContent.slice(lastIndex).trim();
    if (remainingText) {
      parts.push({ type: 'text', content: remainingText });
    }
  }

  // If no parts found, return original content
  if (parts.length === 0 && content.trim()) {
    parts.push({ type: 'text', content: content.trim() });
  }

  return { parts, canvasContent };
}

/**
 * Get only the display content (no think/canvas tags)
 * Handles malformed cases like "content</think>response"
 */
export function getDisplayContent(content: string): string {
  let result = content;
  
  // Handle malformed case: content</think>response (no opening tag)
  if (!result.toLowerCase().includes('<think>') && result.toLowerCase().includes('</think>')) {
    result = result.replace(/^[\s\S]*?<\/think>/i, '');
  }
  
  // Handle proper tags
  result = result
    .replace(/<think>[\s\S]*?<\/think>/gi, '')
    .replace(/<canvas>[\s\S]*?<\/canvas>/gi, '')
    .trim();
    
  return result;
}

/**
 * Extract canvas content from message
 */
export function extractCanvasContent(content: string): string | null {
  const match = /<canvas>([\s\S]*?)<\/canvas>/i.exec(content);
  return match ? match[1].trim() : null;
}

/**
 * MessageContent Component - Renders message with think blocks hidden (shown in left panel)
 */
export function MessageContent({ content, showThinkBlocks = false }: { content: string; showThinkBlocks?: boolean }) {
  const { parts } = parseMessageContent(content);

  // Filter out think blocks by default (they're shown in the left panel now)
  const displayParts = showThinkBlocks 
    ? parts.filter(p => p.type === 'text' || p.type === 'think')
    : parts.filter(p => p.type === 'text');

  if (displayParts.length === 0) {
    return null;
  }

  return (
    <div className="space-y-2">
      {displayParts.map((part, index) => (
        <React.Fragment key={index}>
          {part.type === 'think' ? (
            <ThinkBlock content={part.content} />
          ) : (
            <div className="whitespace-pre-wrap leading-relaxed">{part.content}</div>
          )}
        </React.Fragment>
      ))}
    </div>
  );
}
