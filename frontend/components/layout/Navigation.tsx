'use client';

/**
 * Navigation Component
 * Provides consistent navigation across all pages
 * Validates: Requirements All (Final Integration)
 */

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/components/auth';
import { useCompany } from '@/components/company';
import { CompanySelector } from '@/components/company';
import { ConnectionIndicator } from '@/components/ui/ConnectionStatus';
import { Button } from '@/components/ui/Button';

interface NavLinkProps {
  href: string;
  children: React.ReactNode;
  icon?: React.ReactNode;
}

function NavLink({ href, children, icon }: NavLinkProps) {
  const pathname = usePathname();
  const isActive = pathname === href;

  return (
    <Link
      href={href}
      className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
        isActive
          ? 'bg-primary-100 text-primary-700'
          : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
      }`}
    >
      {icon}
      {children}
    </Link>
  );
}

export function Navigation() {
  const { user, logout, isAuthenticated } = useAuth();
  const { selectedCompany } = useCompany();

  if (!isAuthenticated) {
    return null;
  }

  return (
    <header className="bg-white shadow-sm border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Logo and main nav */}
          <div className="flex items-center gap-8">
            <Link href="/" className="flex items-center gap-2">
              <span className="text-xl font-bold text-primary-600">Auto Manager</span>
            </Link>

            <nav className="hidden md:flex items-center gap-1">
              <NavLink href="/" icon={<HomeIcon />}>
                Home
              </NavLink>
              <NavLink href="/chat" icon={<ChatIcon />}>
                Chat
              </NavLink>
              <NavLink href="/dashboard" icon={<DashboardIcon />}>
                Dashboard
              </NavLink>
              <NavLink href="/companies" icon={<CompanyIcon />}>
                Companies
              </NavLink>
            </nav>
          </div>

          {/* Right side */}
          <div className="flex items-center gap-4">
            {/* Connection status */}
            <div className="hidden sm:flex items-center gap-2">
              <ConnectionIndicator pollInterval={60000} />
              <span className="text-xs text-gray-500">API</span>
            </div>

            {/* Company selector */}
            <div className="hidden md:block w-48">
              <CompanySelector />
            </div>

            {/* User menu */}
            <div className="flex items-center gap-3">
              <span className="hidden sm:block text-sm text-gray-600">
                {user?.name || user?.email}
              </span>
              <Button variant="outline" size="sm" onClick={logout}>
                Sign Out
              </Button>
            </div>
          </div>
        </div>

        {/* Mobile nav */}
        <div className="md:hidden pb-3">
          <nav className="flex items-center gap-1 overflow-x-auto">
            <NavLink href="/" icon={<HomeIcon />}>
              Home
            </NavLink>
            <NavLink href="/chat" icon={<ChatIcon />}>
              Chat
            </NavLink>
            <NavLink href="/dashboard" icon={<DashboardIcon />}>
              Dashboard
            </NavLink>
            <NavLink href="/companies" icon={<CompanyIcon />}>
              Companies
            </NavLink>
          </nav>
          <div className="mt-3">
            <CompanySelector />
          </div>
        </div>
      </div>

      {/* Selected company banner */}
      {selectedCompany && (
        <div className="bg-primary-50 border-t border-primary-100">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-2">
            <p className="text-sm text-primary-700">
              Working with: <span className="font-medium">{selectedCompany.name}</span>
            </p>
          </div>
        </div>
      )}
    </header>
  );
}

// Icon components
function HomeIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
    </svg>
  );
}

function DashboardIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  );
}

function CompanyIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
    </svg>
  );
}

export default Navigation;
