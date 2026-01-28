'use client';

/**
 * Files Panel Component - Sleek design
 * Top: File previews (scrollable thumbnails)
 * Bottom: Output canvas
 */

import React, { useState, useEffect } from 'react';
import { DocumentData } from '@/types/chat';

interface FileItem {
  id: string;
  name: string;
  type: string;
  size: number;
  previewUrl?: string;
  status: 'uploading' | 'processing' | 'ready' | 'error';
  uploadedAt: Date;
}

interface FilesPanelProps {
  uploadedFiles: FileItem[];
  pendingDocuments: DocumentData[];
  canvasContent: string;
  onRemoveFile: (id: string) => void;
}

function FilePreview({ file, onRemove }: { file: FileItem; onRemove: () => void }) {
  const isImage = file.type.startsWith('image/');
  
  return (
    <div className="relative group flex-shrink-0">
      <div className={`
        w-20 h-20 rounded-lg overflow-hidden border-2 transition-all
        ${file.status === 'processing' ? 'border-blue-300 animate-pulse' : 
          file.status === 'error' ? 'border-red-300' : 'border-gray-200'}
      `}>
        {isImage && file.previewUrl ? (
          <img 
            src={file.previewUrl} 
            alt={file.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <div className="w-full h-full bg-gray-100 flex items-center justify-center">
            <span className="text-2xl">
              {file.type === 'application/pdf' ? '📄' : '📎'}
            </span>
          </div>
        )}
        
        {/* Status overlay */}
        {file.status === 'processing' && (
          <div className="absolute inset-0 bg-blue-500/20 flex items-center justify-center">
            <span className="animate-spin text-blue-600">◌</span>
          </div>
        )}
      </div>
      
      {/* Remove button */}
      <button
        onClick={onRemove}
        className="absolute -top-1 -right-1 w-5 h-5 bg-gray-800 text-white rounded-full text-xs opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
      >
        ×
      </button>
      
      {/* File name tooltip */}
      <p className="text-[10px] text-gray-500 mt-1 truncate w-20 text-center">
        {file.name}
      </p>
    </div>
  );
}

function CanvasOutput({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!content) {
    return (
      <div className="h-full flex items-center justify-center text-gray-400">
        <div className="text-center">
          <span className="text-3xl opacity-50">📋</span>
          <p className="text-sm mt-2">Output canvas</p>
          <p className="text-xs mt-1">Generated content appears here</p>
        </div>
      </div>
    );
  }

  // Detect content type and render appropriately
  const renderContent = () => {
    const trimmed = content.trim();
    
    // Check for XML table format: <row><col>...</col></row>
    if (trimmed.includes('<row>') && trimmed.includes('<col>')) {
      return <XmlTableRenderer content={trimmed} />;
    }
    
    // Check for HTML table
    if (trimmed.includes('<table') || trimmed.includes('<tr>')) {
      return <HtmlRenderer content={trimmed} />;
    }
    
    // Check for Markdown table (lines with |)
    if (trimmed.split('\n').some(line => line.includes('|') && line.trim().startsWith('|'))) {
      return <MarkdownTableRenderer content={trimmed} />;
    }
    
    // Check for JSON
    if ((trimmed.startsWith('{') && trimmed.endsWith('}')) || 
        (trimmed.startsWith('[') && trimmed.endsWith(']'))) {
      try {
        const parsed = JSON.parse(trimmed);
        return <JsonRenderer data={parsed} />;
      } catch {
        // Not valid JSON, fall through
      }
    }
    
    // Default: plain text with code formatting
    return (
      <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono leading-relaxed">
        {trimmed}
      </pre>
    );
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between px-3 py-2 border-b bg-gray-50">
        <span className="text-xs font-medium text-gray-600">Output</span>
        <button
          onClick={handleCopy}
          className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
        >
          {copied ? '✓ Copied' : '📋 Copy'}
        </button>
      </div>
      <div className="flex-1 overflow-auto p-3">
        {renderContent()}
      </div>
    </div>
  );
}

// XML Table Renderer: <row><col>Name</col><col>Value</col></row>
function XmlTableRenderer({ content }: { content: string }) {
  const rows: string[][] = [];
  const rowRegex = /<row>([\s\S]*?)<\/row>/gi;
  const colRegex = /<col>([\s\S]*?)<\/col>/gi;
  
  let rowMatch;
  while ((rowMatch = rowRegex.exec(content)) !== null) {
    const rowContent = rowMatch[1];
    const cols: string[] = [];
    let colMatch;
    while ((colMatch = colRegex.exec(rowContent)) !== null) {
      cols.push(colMatch[1].trim());
    }
    if (cols.length > 0) {
      rows.push(cols);
    }
  }
  
  if (rows.length === 0) {
    return <pre className="text-sm text-gray-700 whitespace-pre-wrap">{content}</pre>;
  }
  
  // Determine if first row is header (usually has generic labels like "Name", "Value", etc.)
  const hasHeader = rows.length > 1 && rows[0].every(cell => 
    /^[A-Z]/.test(cell) && cell.length < 30 && !cell.includes('(')
  );
  
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        <tbody>
          {rows.map((row, rowIdx) => (
            <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-gray-50' : 'bg-white'}>
              {row.map((cell, colIdx) => {
                const isLabel = colIdx === 0 && row.length === 2;
                return (
                  <td 
                    key={colIdx} 
                    className={`
                      px-3 py-2 border border-gray-200
                      ${isLabel ? 'font-medium text-gray-600 bg-gray-100 w-1/3' : 'text-gray-800'}
                    `}
                  >
                    {cell}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// HTML Renderer (sanitized)
function HtmlRenderer({ content }: { content: string }) {
  // Basic sanitization - only allow table-related tags
  const sanitized = content
    .replace(/<script[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?<\/style>/gi, '')
    .replace(/on\w+="[^"]*"/gi, '');
  
  return (
    <div 
      className="prose prose-sm max-w-none [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-gray-200 [&_td]:px-3 [&_td]:py-2 [&_th]:border [&_th]:border-gray-200 [&_th]:px-3 [&_th]:py-2 [&_th]:bg-gray-100"
      dangerouslySetInnerHTML={{ __html: sanitized }}
    />
  );
}

// Markdown Table Renderer
function MarkdownTableRenderer({ content }: { content: string }) {
  const lines = content.split('\n').filter(line => line.trim());
  const rows: string[][] = [];
  
  for (const line of lines) {
    if (line.includes('|')) {
      // Skip separator lines (|---|---|)
      if (/^\|?[\s-:|]+\|?$/.test(line)) continue;
      
      const cells = line
        .split('|')
        .map(cell => cell.trim())
        .filter((cell, idx, arr) => idx > 0 && idx < arr.length - 1 || cell);
      
      if (cells.length > 0) {
        rows.push(cells);
      }
    }
  }
  
  if (rows.length === 0) {
    return <pre className="text-sm text-gray-700 whitespace-pre-wrap">{content}</pre>;
  }
  
  const [header, ...body] = rows;
  
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm border-collapse">
        {header && (
          <thead>
            <tr className="bg-gray-100">
              {header.map((cell, idx) => (
                <th key={idx} className="px-3 py-2 border border-gray-200 font-medium text-left">
                  {cell}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {body.map((row, rowIdx) => (
            <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
              {row.map((cell, colIdx) => (
                <td key={colIdx} className="px-3 py-2 border border-gray-200">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// JSON Renderer
function JsonRenderer({ data }: { data: unknown }) {
  if (Array.isArray(data) && data.length > 0 && typeof data[0] === 'object') {
    // Array of objects - render as table
    const keys = Object.keys(data[0] as Record<string, unknown>);
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-100">
              {keys.map(key => (
                <th key={key} className="px-3 py-2 border border-gray-200 font-medium text-left">
                  {key}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((item, idx) => (
              <tr key={idx} className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                {keys.map(key => (
                  <td key={key} className="px-3 py-2 border border-gray-200">
                    {String((item as Record<string, unknown>)[key] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  
  if (typeof data === 'object' && data !== null && !Array.isArray(data)) {
    // Single object - render as key-value table
    const entries = Object.entries(data as Record<string, unknown>);
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <tbody>
            {entries.map(([key, value], idx) => (
              <tr key={key} className={idx % 2 === 0 ? 'bg-gray-50' : 'bg-white'}>
                <td className="px-3 py-2 border border-gray-200 font-medium text-gray-600 bg-gray-100 w-1/3">
                  {key}
                </td>
                <td className="px-3 py-2 border border-gray-200 text-gray-800">
                  {typeof value === 'object' ? JSON.stringify(value) : String(value ?? '')}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  
  // Fallback: pretty print JSON
  return (
    <pre className="text-sm text-gray-700 whitespace-pre-wrap font-mono bg-gray-50 p-3 rounded">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export function FilesPanel({
  uploadedFiles,
  pendingDocuments,
  canvasContent,
  onRemoveFile,
}: FilesPanelProps) {
  const hasFiles = uploadedFiles.length > 0 || pendingDocuments.length > 0;

  return (
    <div className="h-full flex flex-col">
      {/* Files section - top half */}
      <div className={`${hasFiles ? 'h-1/3' : 'h-24'} flex-shrink-0 border-b`}>
        <div className="px-4 py-2 flex items-center gap-2">
          <span className="text-gray-400">📁</span>
          <span className="text-sm font-medium text-gray-600">Files</span>
          {uploadedFiles.length > 0 && (
            <span className="text-xs text-gray-400">({uploadedFiles.length})</span>
          )}
        </div>
        
        {hasFiles ? (
          <div className="px-4 pb-3 overflow-x-auto">
            <div className="flex gap-3">
              {uploadedFiles.map(file => (
                <FilePreview 
                  key={file.id} 
                  file={file} 
                  onRemove={() => onRemoveFile(file.id)}
                />
              ))}
              {pendingDocuments.map(doc => (
                <div key={doc.id} className="flex-shrink-0">
                  <div className="w-20 h-20 rounded-lg border-2 border-yellow-300 bg-yellow-50 flex flex-col items-center justify-center">
                    <span className="text-lg">✓</span>
                    <span className="text-[10px] text-yellow-700 mt-1">Processed</span>
                  </div>
                  <p className="text-[10px] text-gray-500 mt-1 truncate w-20 text-center">
                    {doc.filename || doc.type}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="px-4 pb-3 text-center">
            <p className="text-xs text-gray-400">Drop files or use 📎</p>
          </div>
        )}
      </div>

      {/* Canvas section - bottom */}
      <div className="flex-1 min-h-0">
        <CanvasOutput content={canvasContent} />
      </div>
    </div>
  );
}
