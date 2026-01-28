/**
 * Chat History Types
 * For managing chat sessions with folder organization
 */

export interface ChatSession {
  id: string;
  title: string;
  folderId: string | null;
  companyId: string;
  conversationId: string | null;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  preview?: string;
}

export interface ChatFolder {
  id: string;
  name: string;
  parentId: string | null;
  createdAt: string;
  isExpanded: boolean;
}

export interface ChatHistoryState {
  sessions: ChatSession[];
  folders: ChatFolder[];
  activeSessionId: string | null;
}
