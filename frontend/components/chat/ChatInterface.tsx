'use client';

/**
 * Chat Interface Component with Perplexity-style thinking UI
 * Shows agent reasoning and tool calls inline with messages
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Card, CardContent } from '@/components/ui/Card';
import { chatApi } from '@/lib/api/chat';
import { ChatMessage, ChatResponse, DocumentData, AgentEvent } from '@/types/chat';
import { DocumentReview } from './DocumentReview';
import {
  saveSessionState,
  getSessionState,
  clearSessionState,
  ChatMessageState,
} from '@/lib/utils/storage';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  documents?: DocumentData[];
  thinkingSteps?: ThinkingStep[];
  isStreaming?: boolean;
}

interface ThinkingStep {
  id: string;
  type: 'thinking' | 'tool_call' | 'tool_result' | 'ocr';
  status: 'started' | 'completed' | 'error';
  message: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

interface ChatInterfaceProps {
  companyId: string;
  companyName?: string;
}

/**
 * ThinkingSteps Component - Shows agent reasoning inline (Perplexity-style)
 */
function ThinkingSteps({ steps, isActive }: { steps: ThinkingStep[]; isActive: boolean }) {
  if (steps.length === 0 && !isActive) return null;

  return (
    <div className="mb-3 space-y-2">
      {steps.map((step) => (
        <div
          key={step.id}
          className={`flex items-start gap-2 text-sm ${
            step.status === 'error' ? 'text-red-600' : 'text-gray-600'
          }`}
        >
          <span className="flex-shrink-0 mt-0.5">
            {step.type === 'thinking' && (
              <span className={step.status === 'started' ? 'animate-pulse' : ''}>🧠</span>
            )}
            {step.type === 'tool_call' && (
              <span className={step.status === 'started' ? 'animate-spin' : ''}>🔧</span>
            )}
            {step.type === 'tool_result' && <span>✅</span>}
            {step.type === 'ocr' && (
              <span className={step.status === 'started' ? 'animate-pulse' : ''}>📄</span>
            )}
          </span>
          <div className="flex-1 min-w-0">
            <span className="font-medium">
              {step.type === 'thinking' && 'Thinking'}
              {step.type === 'tool_call' && `Using ${(step.data?.tool as string) || 'tool'}`}
              {step.type === 'tool_result' && `Got result from ${(step.data?.tool as string) || 'tool'}`}
              {step.type === 'ocr' && 'Processing document'}
            </span>
            <span className="text-gray-500 ml-1">— {step.message}</span>
            {step.data?.args !== undefined && (
              <div className="mt-1 text-xs bg-gray-100 rounded p-2 font-mono overflow-x-auto">
                <pre>{JSON.stringify(step.data.args, null, 2)}</pre>
              </div>
            )}
            {step.data?.result_preview !== undefined && (
              <div className="mt-1 text-xs bg-green-50 rounded p-2 font-mono overflow-x-auto max-h-20 overflow-y-auto">
                <span>{String(step.data.result_preview).slice(0, 200)}</span>
              </div>
            )}
          </div>
        </div>
      ))}
      {isActive && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <span className="animate-pulse">⏳</span>
          <span>Processing...</span>
        </div>
      )}
    </div>
  );
}

/**
 * Confirmation Dialog Component
 */
interface ConfirmationDialogProps {
  isOpen: boolean;
  documentCount: number;
  submissionMode: 'combined' | 'individual';
  onConfirm: () => void;
  onCancel: () => void;
  onModeChange: (mode: 'combined' | 'individual') => void;
}

function ConfirmationDialog({
  isOpen,
  documentCount,
  submissionMode,
  onConfirm,
  onCancel,
  onModeChange,
}: ConfirmationDialogProps) {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
      <div className="bg-white rounded-lg shadow-xl max-w-md w-full mx-4 p-6">
        <h3 className="text-lg font-semibold mb-4">Confirm Submission</h3>
        <p className="text-gray-600 mb-4">
          You are about to submit {documentCount} document(s) to Manager.io.
        </p>
        
        <div className="mb-6">
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Submission Mode
          </label>
          <div className="space-y-2">
            <label className="flex items-center">
              <input
                type="radio"
                name="submissionMode"
                value="individual"
                checked={submissionMode === 'individual'}
                onChange={() => onModeChange('individual')}
                className="mr-2"
              />
              <span className="text-sm">
                Individual - Create separate entries for each document
              </span>
            </label>
            <label className="flex items-center">
              <input
                type="radio"
                name="submissionMode"
                value="combined"
                checked={submissionMode === 'combined'}
                onChange={() => onModeChange('combined')}
                className="mr-2"
              />
              <span className="text-sm">
                Combined - Combine all documents into a single entry
              </span>
            </label>
          </div>
        </div>

        <div className="flex justify-end space-x-3">
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm}>
            Submit to Manager.io
          </Button>
        </div>
      </div>
    </div>
  );
}

export function ChatInterface({ companyId, companyName }: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [pendingDocuments, setPendingDocuments] = useState<DocumentData[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [submissionMode, setSubmissionMode] = useState<'combined' | 'individual'>('individual');
  const [isRestored, setIsRestored] = useState(false);
  const [currentThinkingSteps, setCurrentThinkingSteps] = useState<ThinkingStep[]>([]);
  const [useStreaming, setUseStreaming] = useState(true);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<(() => void) | null>(null);

  // Restore session state on mount
  useEffect(() => {
    const sessionState = getSessionState();
    
    if (sessionState.selectedCompanyId === companyId) {
      if (sessionState.conversationId) {
        setConversationId(sessionState.conversationId);
      }
      
      if (sessionState.chatMessages && sessionState.chatMessages.length > 0) {
        const restoredMessages: Message[] = sessionState.chatMessages.map(msg => ({
          id: msg.id,
          role: msg.role,
          content: msg.content,
          timestamp: new Date(msg.timestamp),
          documents: msg.documents as DocumentData[] | undefined,
          thinkingSteps: msg.thinkingSteps as ThinkingStep[] | undefined,
        }));
        setMessages(restoredMessages);
      }
      
      if (sessionState.processedDocuments && sessionState.processedDocuments.length > 0) {
        setPendingDocuments(sessionState.processedDocuments as DocumentData[]);
      }
    } else {
      clearSessionState();
      saveSessionState({ selectedCompanyId: companyId });
    }
    
    setIsRestored(true);
  }, [companyId]);

  // Save session state when messages change
  useEffect(() => {
    if (!isRestored) return;
    
    const chatMessages: ChatMessageState[] = messages.map(msg => ({
      id: msg.id,
      role: msg.role,
      content: msg.content,
      timestamp: msg.timestamp.toISOString(),
      documents: msg.documents,
      thinkingSteps: msg.thinkingSteps,
    }));
    
    saveSessionState({
      selectedCompanyId: companyId,
      chatMessages,
    });
  }, [messages, companyId, isRestored]);

  useEffect(() => {
    if (!isRestored) return;
    saveSessionState({ conversationId });
  }, [conversationId, isRestored]);

  useEffect(() => {
    if (!isRestored) return;
    saveSessionState({ processedDocuments: pendingDocuments });
  }, [pendingDocuments, isRestored]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, currentThinkingSteps, scrollToBottom]);

  // Drag and drop handlers
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.currentTarget === dropZoneRef.current && !dropZoneRef.current?.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const files = Array.from(e.dataTransfer.files).filter(
      file => file.type.startsWith('image/') || file.type === 'application/pdf'
    );
    
    if (files.length > 0) {
      setSelectedFiles(prev => [...prev, ...files]);
    }
  }, []);

  // Convert AgentEvent to ThinkingStep
  const eventToThinkingStep = (event: AgentEvent): ThinkingStep => ({
    id: `${event.type}-${event.timestamp}-${Math.random()}`,
    type: event.type as ThinkingStep['type'],
    status: event.status,
    message: event.message,
    data: event.data,
    timestamp: event.timestamp,
  });

  // Handle streaming message
  const handleStreamingMessage = async (userMessageContent: string, files?: File[]) => {
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: userMessageContent,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);
    setCurrentThinkingSteps([]);

    // Create placeholder for assistant message
    const assistantMessageId = (Date.now() + 1).toString();
    const assistantMessage: Message = {
      id: assistantMessageId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      thinkingSteps: [],
      isStreaming: true,
    };
    setMessages(prev => [...prev, assistantMessage]);

    const thinkingSteps: ThinkingStep[] = [];
    let finalContent = '';

    const handleEvent = (event: AgentEvent) => {
      // Skip 'done' events
      if (event.type === 'done') return;

      const step = eventToThinkingStep(event);
      thinkingSteps.push(step);
      setCurrentThinkingSteps([...thinkingSteps]);

      // Update assistant message with thinking steps
      setMessages(prev => prev.map(msg => 
        msg.id === assistantMessageId 
          ? { ...msg, thinkingSteps: [...thinkingSteps] }
          : msg
      ));

      // If it's a response event, extract content
      if (event.type === 'response' && event.data?.content) {
        finalContent = String(event.data.content);
      }
    };

    const handleComplete = () => {
      setIsLoading(false);
      setCurrentThinkingSteps([]);
      
      // Finalize the assistant message
      setMessages(prev => prev.map(msg => 
        msg.id === assistantMessageId 
          ? { ...msg, content: finalContent || 'Processing complete.', isStreaming: false }
          : msg
      ));
    };

    const handleError = (error: string) => {
      setIsLoading(false);
      setCurrentThinkingSteps([]);
      
      setMessages(prev => prev.map(msg => 
        msg.id === assistantMessageId 
          ? { ...msg, content: `Error: ${error}`, isStreaming: false }
          : msg
      ));
    };

    try {
      if (files && files.length > 0) {
        abortControllerRef.current = chatApi.streamUpload(
          companyId,
          files,
          handleEvent,
          handleComplete,
          handleError,
          userMessageContent,
          conversationId || undefined,
        );
      } else {
        abortControllerRef.current = chatApi.streamMessage(
          {
            message: userMessageContent,
            company_id: companyId,
            conversation_id: conversationId || undefined,
          },
          handleEvent,
          handleComplete,
          handleError,
        );
      }
    } catch (error) {
      handleError(error instanceof Error ? error.message : 'Unknown error');
    }
  };

  // Handle non-streaming message (fallback)
  const handleNonStreamingMessage = async (userMessageContent: string, files?: File[]) => {
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: userMessageContent,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      let response;
      
      if (files && files.length > 0) {
        response = await chatApi.uploadDocuments(
          companyId,
          files,
          userMessageContent || 'Please process these documents',
          conversationId || undefined,
        );
      } else {
        response = await chatApi.sendMessage({
          message: userMessageContent,
          company_id: companyId,
          conversation_id: conversationId || undefined,
        });
      }

      if (response.success && response.data) {
        const data = response.data;
        
        if (data.conversation_id) {
          setConversationId(data.conversation_id);
        }

        // Convert events to thinking steps
        const thinkingSteps: ThinkingStep[] = (data.events || [])
          .filter(e => e.type !== 'done' && e.type !== 'response')
          .map(eventToThinkingStep);

        const assistantMessage: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: data.message,
          timestamp: new Date(),
          documents: data.documents,
          thinkingSteps,
        };

        setMessages(prev => [...prev, assistantMessage]);

        if (data.documents && data.documents.length > 0) {
          setPendingDocuments(prev => [...prev, ...data.documents]);
        }
      } else {
        const errorMessage: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: `Error: ${response.error?.message || 'Failed to get response'}`,
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, errorMessage]);
      }
    } catch (error) {
      const errorMessage: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: `Error: ${error instanceof Error ? error.message : 'An unexpected error occurred'}`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSendMessage = async () => {
    if (!inputValue.trim() && selectedFiles.length === 0) return;

    const messageContent = inputValue || `Uploaded ${selectedFiles.length} file(s)`;
    const files = selectedFiles.length > 0 ? [...selectedFiles] : undefined;
    
    setInputValue('');
    setSelectedFiles([]);

    if (useStreaming) {
      await handleStreamingMessage(messageContent, files);
    } else {
      await handleNonStreamingMessage(messageContent, files);
    }
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setSelectedFiles(prev => [...prev, ...files]);
  };

  const removeFile = (index: number) => {
    setSelectedFiles(prev => prev.filter((_, i) => i !== index));
  };

  const handleSubmitDocuments = async () => {
    if (pendingDocuments.length === 0) return;
    setShowConfirmation(false);
    setIsLoading(true);

    try {
      const response = await chatApi.submitDocuments({
        company_id: companyId,
        conversation_id: conversationId || '',
        confirmed: true,
      });

      if (response.success && response.data) {
        const resultMessage: Message = {
          id: Date.now().toString(),
          role: 'assistant',
          content: response.data.message || 'Documents submitted successfully.',
          timestamp: new Date(),
        };
        setMessages(prev => [...prev, resultMessage]);
        setPendingDocuments([]);
      }
    } catch (error) {
      const errorMessage: Message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: `Error submitting documents: ${error instanceof Error ? error.message : 'Unknown error'}`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleUpdateDocument = (id: string, data: Record<string, unknown>) => {
    setPendingDocuments(prev =>
      prev.map(doc => (doc.id === id ? { ...doc, data } : doc))
    );
  };

  const handleRemoveDocument = (id: string) => {
    setPendingDocuments(prev => prev.filter(doc => doc.id !== id));
  };

  const handleReprocessDocument = async (id: string) => {
    const doc = pendingDocuments.find(d => d.id === id);
    if (!doc) return;

    setIsLoading(true);
    try {
      const response = await chatApi.sendMessage({
        message: `Please reprocess the document: ${doc.filename || id}`,
        company_id: companyId,
        conversation_id: conversationId || undefined,
      });

      if (response.success && response.data) {
        const assistantMessage: Message = {
          id: Date.now().toString(),
          role: 'assistant',
          content: response.data.message,
          timestamp: new Date(),
          documents: response.data.documents,
        };
        setMessages(prev => [...prev, assistantMessage]);

        if (response.data.documents) {
          const reprocessedDoc = response.data.documents.find(d => d.id === id);
          if (reprocessedDoc) {
            setPendingDocuments(prev =>
              prev.map(d => (d.id === id ? reprocessedDoc : d))
            );
          }
        }
      }
    } catch (error) {
      const errorMessage: Message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: `Error reprocessing document: ${error instanceof Error ? error.message : 'Unknown error'}`,
        timestamp: new Date(),
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleClearChat = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current();
    }
    setMessages([]);
    setPendingDocuments([]);
    setConversationId(null);
    setCurrentThinkingSteps([]);
    clearSessionState();
    saveSessionState({ selectedCompanyId: companyId });
  };

  return (
    <div 
      ref={dropZoneRef}
      className={`flex flex-col h-full max-h-[calc(100vh-200px)] relative ${
        isDragging ? 'ring-2 ring-primary-500 ring-inset' : ''
      }`}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      {/* Drag overlay */}
      {isDragging && (
        <div className="absolute inset-0 bg-primary-50 bg-opacity-90 z-10 flex items-center justify-center">
          <div className="text-center">
            <div className="text-4xl mb-2">📄</div>
            <p className="text-lg font-medium text-primary-700">
              Drop files here to upload
            </p>
            <p className="text-sm text-primary-600">
              Supports images (PNG, JPG) and PDFs
            </p>
          </div>
        </div>
      )}

      {/* Header */}
      <div className="p-4 border-b bg-white">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Bookkeeping Assistant</h2>
            {companyName && (
              <p className="text-sm text-gray-500">Company: {companyName}</p>
            )}
          </div>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1 text-sm text-gray-600">
              <input
                type="checkbox"
                checked={useStreaming}
                onChange={(e) => setUseStreaming(e.target.checked)}
                className="rounded"
              />
              Live updates
            </label>
            {(messages.length > 0 || pendingDocuments.length > 0) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={handleClearChat}
                title="Clear chat history"
              >
                Clear Chat
              </Button>
            )}
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-gray-50">
        {messages.length === 0 && (
          <div className="text-center text-gray-500 py-8">
            <p className="text-lg mb-2">Welcome to Auto Manager!</p>
            <p className="text-sm mb-4">
              Upload receipts or invoices, or ask me questions about your bookkeeping.
            </p>
            <p className="text-xs text-gray-400">
              Tip: You can drag and drop files directly into this chat
            </p>
          </div>
        )}
        
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-lg p-4 ${
                message.role === 'user'
                  ? 'bg-primary-600 text-white'
                  : 'bg-white border shadow-sm'
              }`}
            >
              {/* Thinking steps (Perplexity-style) */}
              {message.role === 'assistant' && message.thinkingSteps && message.thinkingSteps.length > 0 && (
                <div className="mb-3 pb-3 border-b border-gray-100">
                  <button
                    className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
                    onClick={(e) => {
                      const target = e.currentTarget.nextElementSibling;
                      if (target) {
                        target.classList.toggle('hidden');
                      }
                    }}
                  >
                    <span>🔍</span>
                    <span>{message.thinkingSteps.length} reasoning step(s)</span>
                    <span className="text-xs">▼</span>
                  </button>
                  <div className="mt-2">
                    <ThinkingSteps steps={message.thinkingSteps} isActive={message.isStreaming || false} />
                  </div>
                </div>
              )}
              
              {/* Message content */}
              {message.content ? (
                <p className="whitespace-pre-wrap">{message.content}</p>
              ) : message.isStreaming ? (
                <div className="flex items-center gap-2 text-gray-500">
                  <span className="animate-pulse">Thinking...</span>
                </div>
              ) : null}
              
              {/* Processed documents */}
              {message.documents && message.documents.length > 0 && (
                <div className="mt-3 space-y-2">
                  {message.documents.map((doc) => (
                    <Card key={doc.id} className="bg-gray-50">
                      <CardContent className="p-3">
                        <p className="font-medium text-sm">
                          {doc.type.toUpperCase()}: {doc.filename}
                        </p>
                        {doc.matched_supplier && (
                          <p className="text-xs text-gray-600 mt-1">
                            Supplier: {doc.matched_supplier.name} ({Math.round((doc.matched_supplier.confidence || 0) * 100)}% match)
                          </p>
                        )}
                        {doc.matched_account && (
                          <p className="text-xs text-gray-600">
                            Account: {doc.matched_account.name}
                          </p>
                        )}
                      </CardContent>
                    </Card>
                  ))}
                </div>
              )}
              
              <p className="text-xs mt-2 opacity-70">
                {message.timestamp.toLocaleTimeString()}
              </p>
            </div>
          </div>
        ))}
        
        {/* Current thinking steps while streaming */}
        {isLoading && currentThinkingSteps.length > 0 && (
          <div className="flex justify-start">
            <div className="max-w-[85%] bg-white border rounded-lg p-4 shadow-sm">
              <ThinkingSteps steps={currentThinkingSteps} isActive={true} />
            </div>
          </div>
        )}
        
        {/* Simple loading indicator */}
        {isLoading && currentThinkingSteps.length === 0 && (
          <div className="flex justify-start">
            <div className="bg-white border rounded-lg p-3 shadow-sm">
              <div className="flex space-x-2">
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-100" />
                <div className="w-2 h-2 bg-gray-400 rounded-full animate-bounce delay-200" />
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* Pending documents for review */}
      {pendingDocuments.length > 0 && (
        <div className="p-4 bg-yellow-50 border-t border-yellow-200 max-h-[40%] overflow-y-auto">
          <div className="flex items-center justify-between mb-3">
            <h3 className="font-medium text-yellow-800">
              {pendingDocuments.length} document(s) ready for review
            </h3>
            <Button
              variant="primary"
              size="sm"
              onClick={() => setShowConfirmation(true)}
              disabled={isLoading}
            >
              Submit to Manager.io
            </Button>
          </div>
          <div className="space-y-3">
            {pendingDocuments.map((doc) => (
              <DocumentReview
                key={doc.id}
                document={doc}
                onUpdate={handleUpdateDocument}
                onRemove={handleRemoveDocument}
                onReprocess={handleReprocessDocument}
              />
            ))}
          </div>
        </div>
      )}

      {/* Selected files preview */}
      {selectedFiles.length > 0 && (
        <div className="p-3 bg-gray-100 border-t">
          <div className="flex flex-wrap gap-2">
            {selectedFiles.map((file, index) => (
              <div
                key={index}
                className="flex items-center bg-white rounded px-2 py-1 text-sm"
              >
                <span className="truncate max-w-[150px]">{file.name}</span>
                <button
                  onClick={() => removeFile(index)}
                  className="ml-2 text-gray-500 hover:text-red-500"
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="p-4 border-t bg-white">
        <div className="flex space-x-2">
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileSelect}
            multiple
            accept="image/*,.pdf"
            className="hidden"
          />
          <Button
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={isLoading}
            title="Upload documents"
          >
            📎
          </Button>
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyPress={handleKeyPress}
            placeholder="Type a message or drag & drop documents..."
            disabled={isLoading}
            className="flex-1"
          />
          <Button
            variant="primary"
            onClick={handleSendMessage}
            disabled={isLoading || (!inputValue.trim() && selectedFiles.length === 0)}
          >
            Send
          </Button>
        </div>
      </div>

      {/* Confirmation Dialog */}
      <ConfirmationDialog
        isOpen={showConfirmation}
        documentCount={pendingDocuments.length}
        submissionMode={submissionMode}
        onConfirm={handleSubmitDocuments}
        onCancel={() => setShowConfirmation(false)}
        onModeChange={setSubmissionMode}
      />
    </div>
  );
}
