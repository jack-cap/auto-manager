'use client';

/**
 * Chat Interface V2 - Robust Three Panel Layout
 * Auto-creates sessions, proper state management
 */

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { chatApi } from '@/lib/api/chat';
import { DocumentData, AgentEvent } from '@/types/chat';
import { ChatSession, ChatFolder, ChatHistoryState } from '@/types/chatHistory';
import { ChatHistorySidebar } from './ChatHistorySidebar';
import { ThinkingPanel } from './ThinkingPanel';
import { FilesPanel } from './FilesPanel';
import { MessageContent, extractCanvasContent, getDisplayContent, parseMessageContent } from './ThinkBlock';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  documents?: DocumentData[];
  isStreaming?: boolean;
}

interface ThinkingStep {
  id: string;
  type: 'thinking' | 'tool_call' | 'tool_result' | 'ocr' | 'response' | 'routing';
  status: 'started' | 'completed' | 'error';
  message: string;
  data?: Record<string, unknown>;
  timestamp: string;
}

interface FileItem {
  id: string;
  name: string;
  type: string;
  size: number;
  previewUrl?: string;
  status: 'uploading' | 'processing' | 'ready' | 'error';
  uploadedAt: Date;
}

interface SessionData {
  messages: Message[];
  thinkingSteps: ThinkingStep[];
  canvasContent: string;
  uploadedFiles: FileItem[];
  conversationId: string | null;
}

interface ChatInterfaceV2Props {
  companyId: string;
  companyName?: string;
}

// Storage
const CHAT_HISTORY_KEY = 'automanager_chat_history';
const SESSION_DATA_PREFIX = 'automanager_session_';

function loadChatHistory(): ChatHistoryState {
  if (typeof window === 'undefined') return { sessions: [], folders: [], activeSessionId: null };
  try {
    const stored = localStorage.getItem(CHAT_HISTORY_KEY);
    return stored ? JSON.parse(stored) : { sessions: [], folders: [], activeSessionId: null };
  } catch {
    return { sessions: [], folders: [], activeSessionId: null };
  }
}

function saveChatHistory(state: ChatHistoryState) {
  if (typeof window === 'undefined') return;
  localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(state));
}

function loadSessionData(sessionId: string): SessionData | null {
  if (typeof window === 'undefined') return null;
  try {
    const stored = localStorage.getItem(SESSION_DATA_PREFIX + sessionId);
    if (!stored) return null;
    const parsed = JSON.parse(stored);
    return {
      ...parsed,
      messages: (parsed.messages || []).map((m: Message & { timestamp: string }) => ({
        ...m,
        timestamp: new Date(m.timestamp)
      })),
      uploadedFiles: (parsed.uploadedFiles || []).map((f: FileItem & { uploadedAt: string }) => ({
        ...f,
        uploadedAt: new Date(f.uploadedAt)
      })),
      thinkingSteps: parsed.thinkingSteps || [],
      canvasContent: parsed.canvasContent || '',
      conversationId: parsed.conversationId || null,
    };
  } catch {
    return null;
  }
}

function saveSessionData(sessionId: string, data: SessionData) {
  if (typeof window === 'undefined') return;
  localStorage.setItem(SESSION_DATA_PREFIX + sessionId, JSON.stringify(data));
}

export function ChatInterfaceV2({ companyId, companyName }: ChatInterfaceV2Props) {
  const [chatHistory, setChatHistory] = useState<ChatHistoryState>(() => loadChatHistory());
  const [messages, setMessages] = useState<Message[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [uploadedFiles, setUploadedFiles] = useState<FileItem[]>([]);
  const [pendingDocuments, setPendingDocuments] = useState<DocumentData[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [thinkingSteps, setThinkingSteps] = useState<ThinkingStep[]>([]);
  const [canvasContent, setCanvasContent] = useState('');
  const [showSidebar, setShowSidebar] = useState(true);
  const [streamingContent, setStreamingContent] = useState('');
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null);
  const [isGeneratingTitle, setIsGeneratingTitle] = useState(false);
  
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dropZoneRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<(() => void) | null>(null);
  const prevCompanyIdRef = useRef<string>(companyId);

  // Reset when company changes
  useEffect(() => {
    if (prevCompanyIdRef.current !== companyId) {
      prevCompanyIdRef.current = companyId;
      resetState();
      setChatHistory(prev => ({ ...prev, activeSessionId: null }));
    }
  }, [companyId]);

  // Save chat history
  useEffect(() => {
    saveChatHistory(chatHistory);
  }, [chatHistory]);

  // Save session data when state changes (debounced)
  useEffect(() => {
    if (currentSessionId && messages.length > 0) {
      const timeoutId = setTimeout(() => {
        saveSessionData(currentSessionId, {
          messages,
          thinkingSteps,
          canvasContent,
          uploadedFiles,
          conversationId
        });
      }, 500);
      return () => clearTimeout(timeoutId);
    }
  }, [messages, thinkingSteps, canvasContent, uploadedFiles, conversationId, currentSessionId]);

  // Load session when activeSessionId changes
  useEffect(() => {
    const activeId = chatHistory.activeSessionId;
    if (activeId && activeId !== currentSessionId) {
      const data = loadSessionData(activeId);
      if (data) {
        setMessages(data.messages);
        setThinkingSteps(data.thinkingSteps);
        setCanvasContent(data.canvasContent);
        setUploadedFiles(data.uploadedFiles);
        setConversationId(data.conversationId);
      } else {
        resetState();
      }
      setCurrentSessionId(activeId);
      setSelectedFiles([]);
      setStreamingContent('');
    } else if (!activeId) {
      setCurrentSessionId(null);
    }
  }, [chatHistory.activeSessionId]);

  // Auto-resize textarea
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = Math.min(textareaRef.current.scrollHeight, 150) + 'px';
    }
  }, [inputValue]);

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamingContent, scrollToBottom]);

  const resetState = () => {
    setMessages([]);
    setThinkingSteps([]);
    setCanvasContent('');
    setUploadedFiles([]);
    setSelectedFiles([]);
    setConversationId(null);
    setPendingDocuments([]);
    setStreamingContent('');
  };

  // Create session and return its ID
  const ensureSession = useCallback((firstMessage?: string): string => {
    // If we have an active session for this company, use it
    if (currentSessionId) {
      const session = chatHistory.sessions.find(s => s.id === currentSessionId);
      if (session && session.companyId === companyId) {
        return currentSessionId;
      }
    }

    // Create new session
    const sessionId = `session-${Date.now()}`;
    const title = firstMessage ? firstMessage.slice(0, 40) : 'New Chat';
    
    const newSession: ChatSession = {
      id: sessionId,
      title,
      folderId: null,
      companyId,
      conversationId: null,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messageCount: 0,
    };

    setChatHistory(prev => ({
      ...prev,
      sessions: [newSession, ...prev.sessions],
      activeSessionId: sessionId,
    }));
    
    setCurrentSessionId(sessionId);
    return sessionId;
  }, [currentSessionId, chatHistory.sessions, companyId]);

  // Drag handlers
  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (!dropZoneRef.current?.contains(e.relatedTarget as Node)) {
      setIsDragging(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const files = Array.from(e.dataTransfer.files).filter(
      f => f.type.startsWith('image/') || f.type === 'application/pdf'
    );
    if (files.length > 0) addFiles(files);
  }, []);

  const addFiles = (files: File[]) => {
    const newFiles: FileItem[] = files.map(file => ({
      id: `file-${Date.now()}-${Math.random().toString(36).substring(2, 11)}`,
      name: file.name,
      type: file.type,
      size: file.size,
      previewUrl: file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined,
      status: 'ready',
      uploadedAt: new Date(),
    }));
    setUploadedFiles(prev => [...prev, ...newFiles]);
    setSelectedFiles(prev => [...prev, ...files]);
  };

  const eventToStep = (event: AgentEvent): ThinkingStep => ({
    id: `${event.type}-${Date.now()}-${Math.random()}`,
    type: event.type as ThinkingStep['type'],
    status: event.status,
    message: event.message,
    data: event.data,
    timestamp: event.timestamp,
  });

  const handleStop = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current();
      abortControllerRef.current = null;
      setIsLoading(false);
      setMessages(prev => prev.map(msg => 
        msg.isStreaming ? { ...msg, content: streamingContent || 'Stopped.', isStreaming: false } : msg
      ));
      setStreamingContent('');
    }
  };

  const handleSendMessage = async () => {
    const content = inputValue.trim();
    const files = selectedFiles.length > 0 ? [...selectedFiles] : undefined;
    
    if (!content && !files?.length) return;

    const messageContent = content || `Uploaded ${files!.length} file(s)`;
    
    // Ensure we have a session (creates one if needed)
    const sessionId = ensureSession(content);
    
    // Clear input immediately
    setInputValue('');
    setSelectedFiles([]);

    // Add user message
    const userMessage: Message = {
      id: Date.now().toString(),
      role: 'user',
      content: messageContent,
      timestamp: new Date(),
    };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);
    setThinkingSteps([]);
    setStreamingContent('');

    if (files?.length) {
      setUploadedFiles(prev => prev.map(f => ({ ...f, status: 'processing' })));
    }

    // Add placeholder assistant message
    const assistantId = (Date.now() + 1).toString();
    setMessages(prev => [...prev, {
      id: assistantId,
      role: 'assistant',
      content: '',
      timestamp: new Date(),
      isStreaming: true,
    }]);

    let finalContent = '';
    const steps: ThinkingStep[] = [];

    // Track which think blocks we've already added to avoid duplicates
    const addedThinkBlocks = new Set<string>();

    const handleEvent = (event: AgentEvent) => {
      if (event.type === 'done') return;
      
      const step = eventToStep(event);
      steps.push(step);
      setThinkingSteps([...steps]);

      if (event.data?.content) {
        const content = String(event.data.content);
        setStreamingContent(content);
        
        // Extract think blocks from streaming content and add to thinking panel
        const { parts } = parseMessageContent(content);
        parts.forEach((part, idx) => {
          if (part.type === 'think' && part.content) {
            const thinkKey = `think-${part.content.slice(0, 50)}`;
            if (!addedThinkBlocks.has(thinkKey)) {
              addedThinkBlocks.add(thinkKey);
              const thinkStep: ThinkingStep = {
                id: `think-${Date.now()}-${idx}`,
                type: 'thinking',
                status: 'completed',
                message: part.content.length > 200 
                  ? part.content.slice(0, 200) + '...' 
                  : part.content,
                data: { content: part.content },
                timestamp: new Date().toISOString(),
              };
              steps.push(thinkStep);
              setThinkingSteps([...steps]);
            }
          }
        });
      }

      if (event.type === 'response' && event.data?.content) {
        finalContent = String(event.data.content);
        const canvas = extractCanvasContent(finalContent);
        if (canvas) setCanvasContent(canvas);
        
        // Extract any remaining think blocks from final response
        const { parts } = parseMessageContent(finalContent);
        parts.forEach((part, idx) => {
          if (part.type === 'think' && part.content) {
            const thinkKey = `think-${part.content.slice(0, 50)}`;
            if (!addedThinkBlocks.has(thinkKey)) {
              addedThinkBlocks.add(thinkKey);
              const thinkStep: ThinkingStep = {
                id: `think-final-${Date.now()}-${idx}`,
                type: 'thinking',
                status: 'completed',
                message: part.content.length > 200 
                  ? part.content.slice(0, 200) + '...' 
                  : part.content,
                data: { content: part.content },
                timestamp: new Date().toISOString(),
              };
              steps.push(thinkStep);
              setThinkingSteps([...steps]);
            }
          }
        });
        
        setMessages(prev => prev.map(msg => 
          msg.id === assistantId ? { ...msg, content: finalContent } : msg
        ));
      }
    };

    const handleComplete = () => {
      setIsLoading(false);
      setUploadedFiles(prev => prev.map(f => ({ ...f, status: 'ready' })));
      setStreamingContent('');
      abortControllerRef.current = null;
      
      setMessages(prev => prev.map(msg => 
        msg.id === assistantId 
          ? { ...msg, content: finalContent || 'Done.', isStreaming: false }
          : msg
      ));

      // Update session metadata
      setChatHistory(prev => ({
        ...prev,
        sessions: prev.sessions.map(s => 
          s.id === sessionId
            ? {
                ...s,
                title: s.messageCount === 0 ? messageContent.slice(0, 40) : s.title,
                messageCount: s.messageCount + 2,
                preview: getDisplayContent(finalContent).slice(0, 100),
                updatedAt: new Date().toISOString(),
              }
            : s
        ),
      }));
    };

    const handleError = (error: string) => {
      setIsLoading(false);
      setUploadedFiles(prev => prev.map(f => ({ ...f, status: 'error' })));
      setStreamingContent('');
      abortControllerRef.current = null;
      
      setMessages(prev => prev.map(msg => 
        msg.id === assistantId 
          ? { ...msg, content: `Error: ${error}`, isStreaming: false }
          : msg
      ));
    };

    try {
      // Build history from existing messages (excluding the one we just added)
      const history = messages.map(m => ({ role: m.role, content: m.content }));
      
      if (files?.length) {
        abortControllerRef.current = chatApi.streamUpload(
          companyId, files, handleEvent, handleComplete, handleError,
          content, conversationId || undefined
        );
      } else {
        abortControllerRef.current = chatApi.streamMessage(
          { 
            message: content, 
            company_id: companyId, 
            conversation_id: conversationId || undefined,
            history: history.length > 0 ? history : undefined,
          },
          handleEvent, handleComplete, handleError
        );
      }
    } catch (error) {
      handleError(error instanceof Error ? error.message : 'Unknown error');
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleNewChat = () => {
    handleStop();
    resetState();
    setCurrentSessionId(null);
    setChatHistory(prev => ({ ...prev, activeSessionId: null }));
  };

  const handleSelectSession = (sessionId: string) => {
    if (sessionId === currentSessionId) return;
    handleStop();
    setChatHistory(prev => ({ ...prev, activeSessionId: sessionId }));
  };

  const handleCreateFolder = (name: string) => {
    const newFolder: ChatFolder = {
      id: `folder-${Date.now()}`,
      name,
      parentId: null,
      createdAt: new Date().toISOString(),
      isExpanded: true,
    };
    setChatHistory(prev => ({ ...prev, folders: [...prev.folders, newFolder] }));
  };

  const handleDeleteFolder = (folderId: string) => {
    setChatHistory(prev => ({
      ...prev,
      folders: prev.folders.filter(f => f.id !== folderId),
      sessions: prev.sessions.map(s => s.folderId === folderId ? { ...s, folderId: null } : s),
    }));
  };

  const handleMoveSession = (sessionId: string, folderId: string | null) => {
    setChatHistory(prev => ({
      ...prev,
      sessions: prev.sessions.map(s => s.id === sessionId ? { ...s, folderId } : s),
    }));
  };

  const handleDeleteSession = (sessionId: string) => {
    localStorage.removeItem(SESSION_DATA_PREFIX + sessionId);
    const isActive = currentSessionId === sessionId;
    
    setChatHistory(prev => ({
      ...prev,
      sessions: prev.sessions.filter(s => s.id !== sessionId),
      activeSessionId: isActive ? null : prev.activeSessionId,
    }));
    
    if (isActive) {
      resetState();
      setCurrentSessionId(null);
    }
  };

  const handleRenameSession = (sessionId: string, title: string) => {
    setChatHistory(prev => ({
      ...prev,
      sessions: prev.sessions.map(s => s.id === sessionId ? { ...s, title } : s),
    }));
  };

  const handleToggleFolder = (folderId: string) => {
    setChatHistory(prev => ({
      ...prev,
      folders: prev.folders.map(f => f.id === folderId ? { ...f, isExpanded: !f.isExpanded } : f),
    }));
  };

  const handleGenerateTitle = async () => {
    if (!currentSessionId || messages.length === 0 || isGeneratingTitle) return;
    
    setIsGeneratingTitle(true);
    try {
      const msgData = messages.map(m => ({ role: m.role, content: m.content }));
      const response = await chatApi.generateTitle(msgData);
      
      if (response.data?.title) {
        handleRenameSession(currentSessionId, response.data.title);
      }
    } catch (error) {
      console.error('Failed to generate title:', error);
    } finally {
      setIsGeneratingTitle(false);
    }
  };

  const companySessions = chatHistory.sessions.filter(s => s.companyId === companyId);

  return (
    <div className="h-screen flex overflow-hidden bg-gray-100">
      {/* Sidebar */}
      {showSidebar && (
        <div className="w-64 flex-shrink-0 border-r border-gray-200">
          <ChatHistorySidebar
            sessions={companySessions}
            folders={chatHistory.folders}
            activeSessionId={currentSessionId}
            onSelectSession={handleSelectSession}
            onNewChat={handleNewChat}
            onCreateFolder={handleCreateFolder}
            onRenameFolder={() => {}}
            onDeleteFolder={handleDeleteFolder}
            onMoveSession={handleMoveSession}
            onDeleteSession={handleDeleteSession}
            onRenameSession={handleRenameSession}
            onToggleFolder={handleToggleFolder}
            onToggleSidebar={() => setShowSidebar(false)}
          />
        </div>
      )}

      {/* Main area */}
      <div 
        ref={dropZoneRef}
        className={`flex-1 flex min-w-0 relative ${isDragging ? 'ring-2 ring-blue-400 ring-inset' : ''}`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        {isDragging && (
          <div className="absolute inset-0 bg-blue-50/90 z-20 flex items-center justify-center">
            <div className="text-center">
              <span className="text-4xl">📄</span>
              <p className="text-blue-600 font-medium mt-2">Drop files here</p>
            </div>
          </div>
        )}

        {/* Left - Thinking */}
        <div className="w-64 flex-shrink-0 bg-gray-50/50">
          <ThinkingPanel 
            steps={thinkingSteps} 
            isProcessing={isLoading}
            streamingContent={streamingContent}
          />
        </div>

        {/* Center - Chat */}
        <div className="flex-1 flex flex-col min-w-0 bg-white">
          {/* Header */}
          <div className="h-14 px-4 flex items-center gap-3 border-b border-gray-100 flex-shrink-0">
            {!showSidebar && (
              <button
                onClick={() => setShowSidebar(true)}
                className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
              >
                <span className="text-gray-500">☰</span>
              </button>
            )}
            <div className="flex-1 min-w-0 flex items-center gap-2">
              <div className="min-w-0">
                <h1 className="font-semibold text-gray-800 truncate">
                  {currentSessionId 
                    ? chatHistory.sessions.find(s => s.id === currentSessionId)?.title || 'New Chat'
                    : 'New Chat'}
                </h1>
                {companyName && <p className="text-xs text-gray-500">{companyName}</p>}
              </div>
              {currentSessionId && messages.length > 0 && (
                <button
                  onClick={handleGenerateTitle}
                  disabled={isGeneratingTitle}
                  className="p-1.5 hover:bg-gray-100 rounded-lg transition-colors text-gray-400 hover:text-gray-600 disabled:opacity-50"
                  title="Generate title from conversation"
                >
                  {isGeneratingTitle ? (
                    <span className="text-sm animate-spin inline-block">⟳</span>
                  ) : (
                    <span className="text-sm">🔄</span>
                  )}
                </button>
              )}
            </div>
            {isLoading && (
              <button
                onClick={handleStop}
                className="px-3 py-1.5 text-sm bg-red-100 text-red-700 rounded-lg hover:bg-red-200 transition-colors"
              >
                ⏹ Stop
              </button>
            )}
          </div>

          {/* Messages */}
          <div className="flex-1 overflow-y-auto min-h-0">
            <div className="max-w-3xl mx-auto px-4 py-6 space-y-6">
              {messages.length === 0 && (
                <div className="text-center py-16">
                  <span className="text-5xl">📚</span>
                  <h2 className="text-xl font-semibold text-gray-700 mt-4">Welcome to Auto Manager</h2>
                  <p className="text-gray-500 mt-2">Upload documents or ask questions about your bookkeeping</p>
                  <p className="text-xs text-gray-400 mt-4">Just start typing - a new chat will be created automatically</p>
                </div>
              )}
              
              {messages.map((msg) => (
                <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[80%] ${msg.role === 'user' ? 'order-2' : ''}`}>
                    {msg.role === 'assistant' && (
                      <div className="flex items-center gap-2 mb-1">
                        <span className="w-6 h-6 rounded-full bg-gray-900 text-white flex items-center justify-center text-xs">A</span>
                        <span className="text-xs text-gray-500">Assistant</span>
                      </div>
                    )}
                    <div className={`rounded-2xl px-4 py-3 ${
                      msg.role === 'user' 
                        ? 'bg-gray-900 text-white' 
                        : 'bg-gray-100 text-gray-800'
                    }`}>
                      {msg.role === 'assistant' ? (
                        msg.isStreaming && !msg.content ? (
                          <span className="text-gray-500">Thinking...</span>
                        ) : (
                          <MessageContent content={msg.content} />
                        )
                      ) : (
                        <p className="whitespace-pre-wrap">{msg.content}</p>
                      )}
                    </div>
                    <p className="text-[10px] text-gray-400 mt-1 px-2">
                      {msg.timestamp.toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))}
              
              {isLoading && messages[messages.length - 1]?.role === 'user' && (
                <div className="flex justify-start">
                  <div className="flex items-center gap-2">
                    <span className="w-6 h-6 rounded-full bg-gray-900 text-white flex items-center justify-center text-xs">A</span>
                    <div className="flex gap-1">
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" />
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.1s' }} />
                      <span className="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style={{ animationDelay: '0.2s' }} />
                    </div>
                  </div>
                </div>
              )}
              
              <div ref={messagesEndRef} />
            </div>
          </div>

          {/* Input */}
          <div className="p-4 border-t border-gray-100 flex-shrink-0">
            <div className="max-w-3xl mx-auto">
              {selectedFiles.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-2">
                  {selectedFiles.map((file, i) => (
                    <span key={i} className="px-2 py-1 bg-gray-100 rounded-full text-sm flex items-center gap-1">
                      📎 {file.name}
                      <button 
                        onClick={() => {
                          setSelectedFiles(prev => prev.filter((_, idx) => idx !== i));
                          setUploadedFiles(prev => prev.filter((_, idx) => idx !== i));
                        }}
                        className="text-gray-400 hover:text-red-500 ml-1"
                      >×</button>
                    </span>
                  ))}
                </div>
              )}
              <div className="flex items-end gap-2 bg-gray-100 rounded-2xl px-4 py-2">
                <input
                  type="file"
                  ref={fileInputRef}
                  onChange={(e) => addFiles(Array.from(e.target.files || []))}
                  multiple
                  accept="image/*,.pdf"
                  className="hidden"
                />
                <button
                  onClick={() => fileInputRef.current?.click()}
                  disabled={isLoading}
                  className="p-2 hover:bg-gray-200 rounded-full transition-colors flex-shrink-0"
                >
                  📎
                </button>
                <textarea
                  ref={textareaRef}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Type a message... (Shift+Enter for new line)"
                  disabled={isLoading}
                  rows={1}
                  className="flex-1 bg-transparent outline-none text-gray-800 placeholder-gray-500 resize-none min-h-[24px] max-h-[150px] py-1"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={isLoading || (!inputValue.trim() && selectedFiles.length === 0)}
                  className="p-2 bg-gray-900 text-white rounded-full hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
                >
                  <span className="text-sm">↑</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right - Files & Canvas */}
        <div className="w-72 flex-shrink-0 bg-gray-50/50 border-l border-gray-200">
          <FilesPanel
            uploadedFiles={uploadedFiles}
            pendingDocuments={pendingDocuments}
            canvasContent={canvasContent}
            onRemoveFile={(id) => {
              const idx = uploadedFiles.findIndex(f => f.id === id);
              setUploadedFiles(prev => prev.filter(f => f.id !== id));
              if (idx !== -1) setSelectedFiles(prev => prev.filter((_, i) => i !== idx));
            }}
          />
        </div>
      </div>
    </div>
  );
}
