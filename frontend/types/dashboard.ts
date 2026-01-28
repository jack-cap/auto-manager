/**
 * Dashboard and financial visualization types
 * Validates: Requirements 7.1-7.9
 */

export interface DashboardData {
  cashBalance: number;
  cashBalanceHistory: TimeSeriesData[];
  cashFlow: CashFlowData[];
  incomeExpense: IncomeExpenseData[];
  expenseBreakdown: CategoryBreakdown[];
}

export interface TimeSeriesData {
  date: string;
  value: number;
  account?: string;
}

export interface CashBalanceHistoryItem {
  date: string;
  balance: number;
  account?: string;
}

export interface CashFlowData {
  period: string;
  inflow: number;
  outflow: number;
  net: number;
}

export interface IncomeExpenseData {
  period: string;
  income: number;
  expense: number;
}

export interface CategoryBreakdown {
  category: string;
  amount: number;
  percentage: number;
}

export interface CashBalance {
  account_name: string;
  account_key: string;
  balance: number;
  currency: string;
}

export interface CashBalanceResponse {
  balances: CashBalance[];
  total: number;
  as_of_date: string;
}

export interface CashBalanceHistoryResponse {
  items: CashBalanceHistoryItem[];
  start_date: string;
  end_date: string;
}

export interface CashFlowResponse {
  items: CashFlowData[];
  total_inflow: number;
  total_outflow: number;
  net_change: number;
}

export interface IncomeExpenseResponse {
  items: IncomeExpenseData[];
  total_income: number;
  total_expense: number;
  net_profit: number;
}

export interface ExpenseBreakdownResponse {
  categories: CategoryBreakdown[];
  total: number;
}

export interface RecentTransaction {
  date: string;
  type: 'payment' | 'receipt' | 'transfer' | 'journal';
  description: string;
  amount: number;
  account?: string;
}

export interface RecentTransactionsResponse {
  transactions: RecentTransaction[];
  total_count: number;
}

export interface DashboardRequest {
  company_id: string;
  start_date?: string;
  end_date?: string;
}

export interface DashboardResponse {
  cash_balance: number;
  cash_balance_history: TimeSeriesData[];
  cash_flow: CashFlowData[];
  income_expense: IncomeExpenseData[];
  expense_breakdown: CategoryBreakdown[];
}
