import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import './globals.css'
import { AuthProvider } from '@/components/auth'
import { CompanyProvider } from '@/components/company'
import { Navigation } from '@/components/layout'
import { ErrorBoundary } from '@/components/ui'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'Auto Manager',
  description: 'AI-powered bookkeeping automation for Manager.io',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <ErrorBoundary>
          <AuthProvider>
            <CompanyProvider>
              <Navigation />
              <main>{children}</main>
            </CompanyProvider>
          </AuthProvider>
        </ErrorBoundary>
      </body>
    </html>
  )
}
