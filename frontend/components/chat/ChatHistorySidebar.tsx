'use client';

/**
 * Chat History Sidebar - With working drag-drop support
 */

import React, { useState, useRef, DragEvent } from 'react';
import { ChatSession, ChatFolder } from '@/types/chatHistory';

interface ChatHistorySidebarProps {
  sessions: ChatSession[];
  folders: ChatFolder[];
  activeSessionId: string | null;
  onSelectSession: (sessionId: string) => void;
  onNewChat: () => void;
  onCreateFolder: (name: string, parentId?: string | null) => void;
  onRenameFolder: (folderId: string, name: string) => void;
  onDeleteFolder: (folderId: string) => void;
  onMoveSession: (sessionId: string, folderId: string | null) => void;
  onDeleteSession: (sessionId: string) => void;
  onRenameSession: (sessionId: string, title: string) => void;
  onToggleFolder: (folderId: string) => void;
  onToggleSidebar: () => void;
}

export function ChatHistorySidebar({
  sessions,
  folders,
  activeSessionId,
  onSelectSession,
  onNewChat,
  onCreateFolder,
  onDeleteFolder,
  onMoveSession,
  onDeleteSession,
  onRenameSession,
  onToggleFolder,
  onToggleSidebar,
}: ChatHistorySidebarProps) {
  const [newFolderName, setNewFolderName] = useState('');
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [draggedSessionId, setDraggedSessionId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null); // folder id or 'root'
  
  const dragCounterRef = useRef<Map<string, number>>(new Map());

  const handleCreateFolder = () => {
    if (newFolderName.trim()) {
      onCreateFolder(newFolderName.trim());
      setNewFolderName('');
      setShowNewFolder(false);
    }
  };

  const startEditing = (id: string, currentName: string) => {
    setEditingId(id);
    setEditingName(currentName);
  };

  const handleRename = () => {
    if (editingId && editingName.trim()) {
      onRenameSession(editingId, editingName.trim());
    }
    setEditingId(null);
    setEditingName('');
  };

  // Drag handlers
  const handleDragStart = (e: DragEvent, sessionId: string) => {
    setDraggedSessionId(sessionId);
    e.dataTransfer.setData('text/plain', sessionId);
    e.dataTransfer.effectAllowed = 'move';
    // Add a slight delay to show the drag effect
    setTimeout(() => {
      const el = e.target as HTMLElement;
      el.style.opacity = '0.5';
    }, 0);
  };

  const handleDragEnd = (e: DragEvent) => {
    setDraggedSessionId(null);
    setDropTargetId(null);
    dragCounterRef.current.clear();
    const el = e.target as HTMLElement;
    el.style.opacity = '1';
  };

  const handleDragEnter = (e: DragEvent, targetId: string) => {
    e.preventDefault();
    e.stopPropagation();
    
    const counter = (dragCounterRef.current.get(targetId) || 0) + 1;
    dragCounterRef.current.set(targetId, counter);
    
    if (draggedSessionId) {
      setDropTargetId(targetId);
    }
  };

  const handleDragLeave = (e: DragEvent, targetId: string) => {
    e.preventDefault();
    e.stopPropagation();
    
    const counter = (dragCounterRef.current.get(targetId) || 1) - 1;
    dragCounterRef.current.set(targetId, counter);
    
    if (counter <= 0) {
      dragCounterRef.current.delete(targetId);
      if (dropTargetId === targetId) {
        setDropTargetId(null);
      }
    }
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  };

  const handleDrop = (e: DragEvent, targetFolderId: string | null) => {
    e.preventDefault();
    e.stopPropagation();
    
    const sessionId = e.dataTransfer.getData('text/plain') || draggedSessionId;
    
    if (sessionId) {
      // Don't move if dropping on the same folder
      const session = sessions.find(s => s.id === sessionId);
      if (session && session.folderId !== targetFolderId) {
        onMoveSession(sessionId, targetFolderId);
      }
    }
    
    setDraggedSessionId(null);
    setDropTargetId(null);
    dragCounterRef.current.clear();
  };

  const rootSessions = sessions.filter(s => !s.folderId);
  const getSessionsInFolder = (folderId: string) => sessions.filter(s => s.folderId === folderId);
  const rootFolders = folders.filter(f => !f.parentId);

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const days = Math.floor(diff / (1000 * 60 * 60 * 24));
    
    if (days === 0) return 'Today';
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days}d ago`;
    return date.toLocaleDateString();
  };

  const renderSession = (session: ChatSession) => {
    const isDragging = draggedSessionId === session.id;
    
    return (
      <div
        key={session.id}
        draggable
        onDragStart={(e) => handleDragStart(e, session.id)}
        onDragEnd={handleDragEnd}
        className={`
          group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all
          ${activeSessionId === session.id ? 'bg-white shadow-sm' : 'hover:bg-white/50'}
          ${isDragging ? 'opacity-50' : ''}
        `}
        onClick={() => !isDragging && onSelectSession(session.id)}
        onDoubleClick={() => startEditing(session.id, session.title)}
      >
        <span className="text-gray-400 text-sm cursor-grab active:cursor-grabbing">⋮⋮</span>
        {editingId === session.id ? (
          <input
            type="text"
            value={editingName}
            onChange={(e) => setEditingName(e.target.value)}
            onBlur={handleRename}
            onKeyDown={(e) => e.key === 'Enter' && handleRename()}
            className="flex-1 px-1 py-0.5 text-sm bg-white border rounded"
            autoFocus
            onClick={(e) => e.stopPropagation()}
          />
        ) : (
          <>
            <span className="flex-1 text-sm truncate text-gray-700">{session.title}</span>
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDeleteSession(session.id);
              }}
              className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 text-xs"
            >
              ×
            </button>
          </>
        )}
      </div>
    );
  };

  const renderFolder = (folder: ChatFolder) => {
    const folderSessions = getSessionsInFolder(folder.id);
    const isDropTarget = dropTargetId === folder.id;

    return (
      <div key={folder.id}>
        <div
          className={`
            group flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer transition-all
            ${isDropTarget ? 'bg-blue-100 ring-2 ring-blue-400' : 'hover:bg-white/50'}
          `}
          onClick={() => onToggleFolder(folder.id)}
          onDragEnter={(e) => handleDragEnter(e, folder.id)}
          onDragLeave={(e) => handleDragLeave(e, folder.id)}
          onDragOver={handleDragOver}
          onDrop={(e) => handleDrop(e, folder.id)}
        >
          <span className={`text-[10px] text-gray-400 transform transition-transform ${folder.isExpanded ? 'rotate-90' : ''}`}>
            ▶
          </span>
          <span className="text-gray-400 text-sm">{isDropTarget ? '📂' : '📁'}</span>
          <span className="flex-1 text-sm font-medium text-gray-700 truncate">{folder.name}</span>
          <span className="text-xs text-gray-400">{folderSessions.length}</span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDeleteFolder(folder.id);
            }}
            className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 text-xs"
          >
            ×
          </button>
        </div>
        {folder.isExpanded && (
          <div 
            className="ml-4 min-h-[8px]"
            onDragEnter={(e) => handleDragEnter(e, folder.id)}
            onDragLeave={(e) => handleDragLeave(e, folder.id)}
            onDragOver={handleDragOver}
            onDrop={(e) => handleDrop(e, folder.id)}
          >
            {folderSessions.length > 0 ? (
              folderSessions.map(renderSession)
            ) : (
              <div className={`text-xs text-gray-400 px-3 py-2 ${isDropTarget ? 'text-blue-500' : ''}`}>
                {isDropTarget ? 'Drop here' : 'Empty folder'}
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // Group sessions by date
  const todaySessions = rootSessions.filter(s => formatDate(s.updatedAt) === 'Today');
  const yesterdaySessions = rootSessions.filter(s => formatDate(s.updatedAt) === 'Yesterday');
  const olderSessions = rootSessions.filter(s => !['Today', 'Yesterday'].includes(formatDate(s.updatedAt)));
  
  const isRootDropTarget = dropTargetId === 'root';

  return (
    <div className="h-full flex flex-col bg-gray-50/80">
      {/* Header */}
      <div className="p-3 flex items-center gap-2">
        <button
          onClick={onToggleSidebar}
          className="p-2 hover:bg-gray-200 rounded-lg transition-colors"
          title="Hide sidebar"
        >
          <span className="text-gray-500">◀</span>
        </button>
        <button
          onClick={onNewChat}
          className="flex-1 px-4 py-2.5 bg-gray-900 text-white rounded-lg hover:bg-gray-800 transition-colors flex items-center justify-center gap-2 text-sm font-medium"
        >
          <span>+</span>
          <span>New Chat</span>
        </button>
      </div>

      {/* Folder creation */}
      <div className="px-3 pb-2">
        {showNewFolder ? (
          <div className="flex gap-1">
            <input
              type="text"
              value={newFolderName}
              onChange={(e) => setNewFolderName(e.target.value)}
              placeholder="Folder name"
              className="flex-1 px-2 py-1 text-sm border rounded bg-white"
              onKeyDown={(e) => e.key === 'Enter' && handleCreateFolder()}
              autoFocus
            />
            <button onClick={handleCreateFolder} className="px-2 text-gray-600 hover:text-gray-900">✓</button>
            <button onClick={() => setShowNewFolder(false)} className="px-2 text-gray-400 hover:text-gray-600">×</button>
          </div>
        ) : (
          <button
            onClick={() => setShowNewFolder(true)}
            className="w-full px-3 py-1.5 text-xs text-gray-500 hover:text-gray-700 hover:bg-white/50 rounded flex items-center gap-2 transition-colors"
          >
            <span>📁</span>
            <span>New Folder</span>
          </button>
        )}
      </div>

      {/* Chat list */}
      <div 
        className={`flex-1 overflow-y-auto px-2 pb-4 transition-colors ${isRootDropTarget ? 'bg-blue-50' : ''}`}
        onDragEnter={(e) => handleDragEnter(e, 'root')}
        onDragLeave={(e) => handleDragLeave(e, 'root')}
        onDragOver={handleDragOver}
        onDrop={(e) => handleDrop(e, null)}
      >
        {/* Folders */}
        {rootFolders.length > 0 && (
          <div className="mb-3">
            {rootFolders.map(renderFolder)}
          </div>
        )}

        {/* Today */}
        {todaySessions.length > 0 && (
          <div className="mb-3">
            <p className="px-3 py-1 text-xs font-medium text-gray-400 uppercase">Today</p>
            {todaySessions.map(renderSession)}
          </div>
        )}

        {/* Yesterday */}
        {yesterdaySessions.length > 0 && (
          <div className="mb-3">
            <p className="px-3 py-1 text-xs font-medium text-gray-400 uppercase">Yesterday</p>
            {yesterdaySessions.map(renderSession)}
          </div>
        )}

        {/* Older */}
        {olderSessions.length > 0 && (
          <div className="mb-3">
            <p className="px-3 py-1 text-xs font-medium text-gray-400 uppercase">Previous</p>
            {olderSessions.map(renderSession)}
          </div>
        )}

        {sessions.length === 0 && folders.length === 0 && (
          <div className="text-center py-8">
            <p className="text-sm text-gray-400">No conversations yet</p>
            <p className="text-xs text-gray-300 mt-1">Drag chats to folders to organize</p>
          </div>
        )}
        
        {/* Drop indicator when dragging */}
        {draggedSessionId && isRootDropTarget && (
          <div className="mt-2 p-2 border-2 border-dashed border-blue-300 rounded-lg text-center text-xs text-blue-500">
            Drop here to move to root
          </div>
        )}
      </div>
    </div>
  );
}
