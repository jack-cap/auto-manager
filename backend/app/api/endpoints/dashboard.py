"""Dashboard API endpoints for financial summaries and reports.

Implements Requirements 7.1-7.9:
- 7.1: Display current cash balance
- 7.2: Display cash balance over time chart
- 7.3: Display monthly cash flow (inflow/outflow/net)
- 7.4: Display income vs expense comparison
- 7.5: Display expense breakdown by category
- 7.6: Retrieve payments, receipts, transfers, and journal entries
- 7.7: Allow date range filtering on all dashboard charts
- 7.8: Calculate running balances from transaction history
- 7.9: Return recent transactions for context
"""

import logging
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.endpoints.auth import CurrentUser
from app.core.database import get_db
from app.services.company import CompanyConfigService, CompanyNotFoundError
from app.services.encryption import EncryptionService
from app.services.manager_io import ManagerIOClient, ManagerIOError

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Response Models
# =============================================================================


class CashBalance(BaseModel):
    """Current cash balance for an account."""
    
    account_name: str
    account_key: str
    balance: float
    currency: str = "USD"


class CashBalanceResponse(BaseModel):
    """Response with cash balances.
    
    Validates: Requirement 7.1 - Display current cash balance
    """
    
    balances: List[CashBalance]
    total: float
    as_of_date: str


class CashBalanceHistoryItem(BaseModel):
    """Cash balance at a point in time.
    
    Validates: Requirement 7.2 - Display cash balance over time chart
    """
    
    date: str
    balance: float
    account: Optional[str] = None


class CashBalanceHistoryResponse(BaseModel):
    """Response with cash balance history."""
    
    items: List[CashBalanceHistoryItem]
    start_date: str
    end_date: str


class CashFlowItem(BaseModel):
    """Cash flow for a period.
    
    Validates: Requirement 7.3 - Display monthly cash flow
    """
    
    period: str  # e.g., "2024-01" for monthly
    inflow: float
    outflow: float
    net: float


class CashFlowResponse(BaseModel):
    """Response with cash flow data."""
    
    items: List[CashFlowItem]
    total_inflow: float
    total_outflow: float
    net_change: float


class IncomeExpenseItem(BaseModel):
    """Income vs expense for a period.
    
    Validates: Requirement 7.4 - Display income vs expense comparison
    """
    
    period: str
    income: float
    expense: float


class IncomeExpenseResponse(BaseModel):
    """Response with income vs expense comparison."""
    
    items: List[IncomeExpenseItem]
    total_income: float
    total_expense: float
    net_profit: float


class ExpenseCategory(BaseModel):
    """Expense breakdown by category.
    
    Validates: Requirement 7.5 - Display expense breakdown by category
    """
    
    category: str
    amount: float
    percentage: float


class ExpenseBreakdownResponse(BaseModel):
    """Response with expense breakdown."""
    
    categories: List[ExpenseCategory]
    total: float


class RecentTransaction(BaseModel):
    """A recent transaction.
    
    Validates: Requirement 7.9 - Return recent transactions for context
    """
    
    date: str
    type: str  # payment, receipt, transfer, journal
    description: str
    amount: float
    account: Optional[str] = None


class RecentTransactionsResponse(BaseModel):
    """Response with recent transactions."""
    
    transactions: List[RecentTransaction]
    total_count: int


# =============================================================================
# Helper Functions
# =============================================================================


def parse_date(date_str: str) -> Optional[date]:
    """Parse a date string in various formats."""
    if not date_str:
        return None
    
    for fmt in ["%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"]:
        try:
            return datetime.strptime(date_str[:len("2024-01-01T00:00:00")], fmt).date()
        except ValueError:
            continue
    return None


def filter_by_date_range(
    records: List[Dict[str, Any]],
    start_date: Optional[date],
    end_date: Optional[date],
    date_field: str = "Date",
) -> List[Dict[str, Any]]:
    """Filter records by date range.
    
    Validates: Requirement 7.7 - Allow date range filtering
    
    Args:
        records: List of records to filter
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        date_field: Name of the date field in records
        
    Returns:
        Filtered list of records within the date range
    """
    if not start_date and not end_date:
        return records
    
    filtered = []
    for record in records:
        record_date_str = record.get(date_field, "")
        record_date = parse_date(record_date_str)
        
        if record_date is None:
            continue
        
        if start_date and record_date < start_date:
            continue
        if end_date and record_date > end_date:
            continue
        
        filtered.append(record)
    
    return filtered


def calculate_running_balance(
    transactions: List[Dict[str, Any]],
    is_credit: bool = False,
) -> float:
    """Calculate running balance from transactions.
    
    Validates: Requirement 7.8 - Calculate running balances from transaction history
    
    Args:
        transactions: List of transaction records
        is_credit: If True, amounts are credits (add to balance)
        
    Returns:
        Running balance total
    """
    total = 0.0
    for txn in transactions:
        amount = float(txn.get("Amount", 0))
        if is_credit:
            total += amount
        else:
            total -= amount
    return total


# =============================================================================
# Dependencies
# =============================================================================


async def get_manager_client(
    company_id: str,
    user_id: str,
    db: AsyncSession,
) -> ManagerIOClient:
    """Get Manager.io client for a company."""
    logger.info(f"Getting manager client for company_id={company_id}, user_id={user_id}")
    
    encryption = EncryptionService()
    company_service = CompanyConfigService(db, encryption)
    
    try:
        company = await company_service.get_by_id(company_id, user_id)
        logger.info(f"Found company: {company.name} at {company.base_url}")
        api_key = company_service.decrypt_api_key(company)
        return ManagerIOClient(base_url=company.base_url, api_key=api_key)
    except CompanyNotFoundError as e:
        logger.error(f"Company not found: company_id={company_id}, user_id={user_id}, error={e}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company not found: {company_id}",
        )


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/debug",
    summary="Debug endpoint to check Manager.io data",
    description="Returns raw data from Manager.io for debugging.",
)
async def debug_manager_data(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Debug endpoint to see what Manager.io returns."""
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        
        # Get accounts
        accounts = await client.get_chart_of_accounts()
        
        # Get bank accounts
        try:
            bank_accounts = await client.get_bank_accounts()
        except Exception as e:
            bank_accounts = [{"error": str(e)}]
        
        # Get trial balance (shows account balances)
        try:
            trial_balance = await client.get_trial_balance()
        except Exception as e:
            trial_balance = {"error": str(e)}
        
        # Get balance sheet
        try:
            balance_sheet = await client.get_balance_sheet()
        except Exception as e:
            balance_sheet = {"error": str(e)}
        
        # Get P&L
        try:
            profit_loss = await client.get_profit_and_loss()
        except Exception as e:
            profit_loss = {"error": str(e)}
        
        await client.close()
        
        return {
            "accounts_count": len(accounts),
            "accounts_sample": [{"key": a.key, "name": a.name, "code": a.code} for a in accounts[:10]],
            "bank_accounts": bank_accounts[:5] if bank_accounts else [],
            "trial_balance": trial_balance,
            "balance_sheet": balance_sheet,
            "profit_loss": profit_loss,
        }
        
    except ManagerIOError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )


@router.get(
    "/cash-balance",
    response_model=CashBalanceResponse,
    summary="Get cash balances",
    description="Get current cash balances for bank and cash accounts.",
)
async def get_cash_balance(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    as_of_date: Optional[date] = Query(None, description="Calculate balance as of this date"),
    db: AsyncSession = Depends(get_db),
) -> CashBalanceResponse:
    """Get current cash balances.
    
    Validates: Requirement 7.1 - Display current cash balance
    Validates: Requirement 7.8 - Calculate running balances from transaction history
    
    Fetches balances for bank and cash accounts from Manager.io.
    Tries multiple approaches: trial balance, bank accounts endpoint, then transactions.
    """
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        effective_date = as_of_date or date.today()
        
        balances = []
        total = 0.0
        
        # Try to get bank/cash accounts
        bank_accounts = []
        bank_account_keys: set = set()
        account_names: Dict[str, str] = {}
        
        try:
            bank_accounts = await client.get_bank_accounts()
            logger.info(f"Found {len(bank_accounts)} bank/cash accounts")
            
            for ba in bank_accounts:
                key = ba.get("Key") or ba.get("key") or ba.get("Guid") or ba.get("guid") or ""
                name = ba.get("Name") or ba.get("name") or "Unknown Account"
                if key:
                    bank_account_keys.add(key)
                    account_names[key] = name
                    logger.info(f"Bank account: {name} ({key})")
        except Exception as e:
            logger.warning(f"Could not get bank accounts: {e}")
        
        # Try to get trial balance for accurate balances
        trial_balance = None
        try:
            trial_balance = await client.get_trial_balance(effective_date.isoformat())
            logger.info(f"Trial balance response type: {type(trial_balance)}")
            
            # Parse trial balance
            tb_items = []
            if isinstance(trial_balance, list):
                tb_items = trial_balance
            elif isinstance(trial_balance, dict):
                tb_items = trial_balance.get("items", trial_balance.get("data", trial_balance.get("Accounts", [])))
                if not tb_items and "Groups" in trial_balance:
                    for group in trial_balance.get("Groups", []):
                        tb_items.extend(group.get("Accounts", []))
            
            logger.info(f"Trial balance items count: {len(tb_items)}")
            
            # Extract balances for bank/cash accounts
            for item in tb_items:
                account_key = (
                    item.get("Key") or item.get("key") or 
                    item.get("Account") or item.get("account") or
                    item.get("AccountKey") or item.get("account_key") or ""
                )
                
                if account_key in bank_account_keys:
                    balance = 0.0
                    if "Balance" in item or "balance" in item:
                        balance = float(item.get("Balance") or item.get("balance") or 0)
                    elif "Debit" in item or "Credit" in item:
                        debit = float(item.get("Debit") or item.get("debit") or 0)
                        credit = float(item.get("Credit") or item.get("credit") or 0)
                        balance = debit - credit
                    
                    account_name = account_names.get(account_key, item.get("Name") or item.get("name") or "Unknown")
                    balances.append(CashBalance(
                        account_name=account_name,
                        account_key=account_key,
                        balance=round(balance, 2),
                    ))
                    total += balance
                    logger.info(f"Added balance from trial balance for {account_name}: {balance}")
                    
        except Exception as e:
            logger.warning(f"Could not get trial balance: {e}")
        
        # If no balances from trial balance, try bank accounts directly
        if not balances and bank_accounts:
            logger.info("Trying to get balances from bank accounts endpoint")
            for ba in bank_accounts:
                key = ba.get("Key") or ba.get("key") or ba.get("Guid") or ""
                name = ba.get("Name") or ba.get("name") or "Unknown"
                
                balance = 0.0
                if "Balance" in ba or "balance" in ba:
                    balance = float(ba.get("Balance") or ba.get("balance") or 0)
                elif "CurrentBalance" in ba or "current_balance" in ba:
                    balance = float(ba.get("CurrentBalance") or ba.get("current_balance") or 0)
                
                if key:
                    balances.append(CashBalance(
                        account_name=name,
                        account_key=key,
                        balance=round(balance, 2),
                    ))
                    total += balance
        
        # If still no balances, fall back to calculating from transactions
        if not balances:
            logger.info("Falling back to calculating balances from transactions")
            
            # Get chart of accounts to identify cash/bank accounts by name
            accounts = await client.get_chart_of_accounts()
            for acc in accounts:
                if any(term in acc.name.lower() for term in ['cash', 'bank', 'checking', 'savings', 'petty']):
                    bank_account_keys.add(acc.key)
                    account_names[acc.key] = acc.name
            
            logger.info(f"Identified {len(bank_account_keys)} cash/bank accounts from chart of accounts")
            
            if bank_account_keys:
                # Fetch transactions
                payments = await client.fetch_all_paginated("/payments")
                receipts = await client.fetch_all_paginated("/receipts")
                transfers = await client.fetch_all_paginated("/inter-account-transfers")
                
                # Filter by date
                payments = filter_by_date_range(payments, None, effective_date)
                receipts = filter_by_date_range(receipts, None, effective_date)
                transfers = filter_by_date_range(transfers, None, effective_date)
                
                logger.info(f"Fetched {len(payments)} payments, {len(receipts)} receipts, {len(transfers)} transfers")
                
                # Calculate balances per account
                account_balances: Dict[str, float] = defaultdict(float)
                
                for receipt in receipts:
                    account_key = (
                        receipt.get("BankAccount") or receipt.get("BankCashAccount") or
                        receipt.get("Account") or receipt.get("bank_account") or ""
                    )
                    if account_key in bank_account_keys:
                        amount = float(receipt.get("Amount") or receipt.get("amount") or 0)
                        account_balances[account_key] += amount
                
                for payment in payments:
                    account_key = (
                        payment.get("BankAccount") or payment.get("BankCashAccount") or
                        payment.get("Account") or payment.get("bank_account") or ""
                    )
                    if account_key in bank_account_keys:
                        amount = float(payment.get("Amount") or payment.get("amount") or 0)
                        account_balances[account_key] -= amount
                
                for transfer in transfers:
                    from_account = (
                        transfer.get("CreditAccount") or transfer.get("FromAccount") or
                        transfer.get("PaidFrom") or ""
                    )
                    to_account = (
                        transfer.get("DebitAccount") or transfer.get("ToAccount") or
                        transfer.get("ReceivedIn") or ""
                    )
                    amount = float(transfer.get("Amount") or transfer.get("amount") or 0)
                    
                    if from_account in bank_account_keys:
                        account_balances[from_account] -= amount
                    if to_account in bank_account_keys:
                        account_balances[to_account] += amount
                
                # Build response
                for account_key, balance in sorted(account_balances.items(), key=lambda x: -x[1]):
                    account_name = account_names.get(account_key, "Unknown Account")
                    balances.append(CashBalance(
                        account_name=account_name,
                        account_key=account_key,
                        balance=round(balance, 2),
                    ))
                    total += balance
        
        await client.close()
        
        return CashBalanceResponse(
            balances=balances,
            total=round(total, 2),
            as_of_date=effective_date.isoformat(),
        )
        
    except ManagerIOError as e:
        logger.error(f"Manager.io API error in get_cash_balance: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )


@router.get(
    "/cash-balance-history",
    response_model=CashBalanceHistoryResponse,
    summary="Get cash balance history",
    description="Get cash balance over time for charting.",
)
async def get_cash_balance_history(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    db: AsyncSession = Depends(get_db),
) -> CashBalanceHistoryResponse:
    """Get cash balance history over time.
    
    Validates: Requirement 7.2 - Display cash balance over time chart
    Validates: Requirement 7.7 - Allow date range filtering
    Validates: Requirement 7.8 - Calculate running balances from transaction history
    
    Returns daily cash balance snapshots for the specified date range.
    """
    # Default to last 90 days
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=90)
    
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        
        # Get bank/cash accounts
        cash_account_keys = set()
        account_names: Dict[str, str] = {}
        
        try:
            bank_accounts = await client.get_bank_accounts()
            for ba in bank_accounts:
                key = ba.get("Key") or ba.get("key") or ba.get("Guid") or ""
                name = ba.get("Name") or ba.get("name") or "Unknown"
                if key:
                    cash_account_keys.add(key)
                    account_names[key] = name
        except Exception as e:
            logger.warning(f"Could not get bank accounts: {e}")
        
        # If no bank accounts found, try to identify from chart of accounts
        if not cash_account_keys:
            logger.info("No bank accounts from endpoint, identifying from chart of accounts")
            accounts = await client.get_chart_of_accounts()
            for acc in accounts:
                if any(term in acc.name.lower() for term in ['cash', 'bank', 'checking', 'savings', 'petty']):
                    cash_account_keys.add(acc.key)
                    account_names[acc.key] = acc.name
        
        logger.info(f"Cash balance history: tracking {len(cash_account_keys)} bank/cash accounts")
        
        # Get current balance from trial balance as starting point
        current_total = 0.0
        try:
            trial_balance = await client.get_trial_balance(end_date.isoformat())
            
            tb_items = []
            if isinstance(trial_balance, list):
                tb_items = trial_balance
            elif isinstance(trial_balance, dict):
                tb_items = trial_balance.get("items", trial_balance.get("data", 
                           trial_balance.get("Accounts", [])))
                if not tb_items and "Groups" in trial_balance:
                    for group in trial_balance.get("Groups", []):
                        tb_items.extend(group.get("Accounts", []))
            
            for item in tb_items:
                account_key = (
                    item.get("Key") or item.get("key") or 
                    item.get("Account") or item.get("AccountKey") or ""
                )
                if account_key in cash_account_keys:
                    if "Balance" in item or "balance" in item:
                        current_total += float(item.get("Balance") or item.get("balance") or 0)
                    else:
                        debit = float(item.get("Debit") or item.get("debit") or 0)
                        credit = float(item.get("Credit") or item.get("credit") or 0)
                        current_total += debit - credit
            
            logger.info(f"Current cash total from trial balance: {current_total}")
            
        except Exception as e:
            logger.warning(f"Could not get trial balance for history: {e}")
        
        # Fetch all transactions
        payments = await client.fetch_all_paginated("/payments")
        receipts = await client.fetch_all_paginated("/receipts")
        transfers = await client.fetch_all_paginated("/inter-account-transfers")
        
        logger.info(f"Fetched {len(payments)} payments, {len(receipts)} receipts, {len(transfers)} transfers")
        
        # Build daily balance changes
        daily_changes: Dict[str, float] = defaultdict(float)
        
        for receipt in receipts:
            receipt_date = receipt.get("Date", "")[:10]
            account_key = (
                receipt.get("BankAccount") or receipt.get("BankCashAccount") or
                receipt.get("Account") or receipt.get("bank_account") or ""
            )
            if account_key in cash_account_keys and receipt_date:
                daily_changes[receipt_date] += float(receipt.get("Amount") or receipt.get("amount") or 0)
        
        for payment in payments:
            payment_date = payment.get("Date", "")[:10]
            account_key = (
                payment.get("BankAccount") or payment.get("BankCashAccount") or
                payment.get("Account") or payment.get("bank_account") or ""
            )
            if account_key in cash_account_keys and payment_date:
                daily_changes[payment_date] -= float(payment.get("Amount") or payment.get("amount") or 0)
        
        for transfer in transfers:
            transfer_date = transfer.get("Date", "")[:10]
            from_account = (
                transfer.get("CreditAccount") or transfer.get("FromAccount") or
                transfer.get("PaidFrom") or ""
            )
            to_account = (
                transfer.get("DebitAccount") or transfer.get("ToAccount") or
                transfer.get("ReceivedIn") or ""
            )
            amount = float(transfer.get("Amount") or transfer.get("amount") or 0)
            
            if transfer_date:
                if from_account in cash_account_keys:
                    daily_changes[transfer_date] -= amount
                if to_account in cash_account_keys:
                    daily_changes[transfer_date] += amount
        
        # If we don't have a current total from trial balance, calculate from transactions
        if current_total == 0.0 and daily_changes:
            # Sum all changes up to end_date
            for date_str, change in daily_changes.items():
                txn_date = parse_date(date_str)
                if txn_date and txn_date <= end_date:
                    current_total += change
            logger.info(f"Calculated current total from transactions: {current_total}")
        
        # Build list of dates in range
        date_list = []
        current = start_date
        while current <= end_date:
            date_list.append(current)
            current += timedelta(days=1)
        
        # Calculate balance at end_date, then work backwards
        running_balance = current_total
        
        # Process dates in reverse to build history
        balances = {}
        for d in reversed(date_list):
            date_str = d.isoformat()
            balances[date_str] = running_balance
            if date_str in daily_changes:
                running_balance -= daily_changes[date_str]
        
        # Build items in chronological order
        items = []
        for d in date_list:
            date_str = d.isoformat()
            items.append(CashBalanceHistoryItem(
                date=date_str,
                balance=round(balances.get(date_str, 0), 2),
            ))
        
        await client.close()
        
        return CashBalanceHistoryResponse(
            items=items,
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
        )
        
    except ManagerIOError as e:
        logger.error(f"Manager.io API error in get_cash_balance_history: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )


@router.get(
    "/cash-flow",
    response_model=CashFlowResponse,
    summary="Get cash flow",
    description="Get cash flow data for a date range.",
)
async def get_cash_flow(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    db: AsyncSession = Depends(get_db),
) -> CashFlowResponse:
    """Get cash flow data.
    
    Validates: Requirement 7.3 - Display monthly cash flow (inflow/outflow/net)
    Validates: Requirement 7.6 - Retrieve payments, receipts, transfers
    Validates: Requirement 7.7 - Allow date range filtering
    
    Returns inflows, outflows, and net cash flow by period.
    Uses cash flow statement from Manager.io when available.
    """
    # Default to last 6 months
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=180)
    
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        
        # Try to get cash flow statement for totals
        total_inflow = 0.0
        total_outflow = 0.0
        
        try:
            cf_statement = await client.get_cash_flow_statement(
                from_date=start_date.isoformat(),
                to_date=end_date.isoformat()
            )
            logger.info(f"Cash flow statement response type: {type(cf_statement)}")
            
            if isinstance(cf_statement, dict):
                # Try to extract totals from cash flow statement
                total_inflow = float(
                    cf_statement.get("TotalInflows") or cf_statement.get("total_inflows") or
                    cf_statement.get("CashInflows") or cf_statement.get("cash_inflows") or 0
                )
                total_outflow = float(
                    cf_statement.get("TotalOutflows") or cf_statement.get("total_outflows") or
                    cf_statement.get("CashOutflows") or cf_statement.get("cash_outflows") or 0
                )
                
                logger.info(f"Cash flow statement totals - Inflow: {total_inflow}, Outflow: {total_outflow}")
                
        except Exception as e:
            logger.warning(f"Could not get cash flow statement: {e}")
        
        # Get monthly breakdown from transactions
        payments = await client.fetch_all_paginated("/payments")
        receipts = await client.fetch_all_paginated("/receipts")
        
        # Apply date range filtering
        payments = filter_by_date_range(payments, start_date, end_date)
        receipts = filter_by_date_range(receipts, start_date, end_date)
        
        # Group by month
        monthly_data: Dict[str, Dict[str, float]] = {}
        
        for payment in payments:
            payment_date = payment.get("Date", "")
            if payment_date:
                month = payment_date[:7]  # YYYY-MM
                if month not in monthly_data:
                    monthly_data[month] = {"inflow": 0.0, "outflow": 0.0}
                monthly_data[month]["outflow"] += float(payment.get("Amount") or payment.get("amount") or 0)
        
        for receipt in receipts:
            receipt_date = receipt.get("Date", "")
            if receipt_date:
                month = receipt_date[:7]
                if month not in monthly_data:
                    monthly_data[month] = {"inflow": 0.0, "outflow": 0.0}
                monthly_data[month]["inflow"] += float(receipt.get("Amount") or receipt.get("amount") or 0)
        
        # Build response
        items = []
        calc_inflow = 0.0
        calc_outflow = 0.0
        
        for period in sorted(monthly_data.keys()):
            data = monthly_data[period]
            inflow = data["inflow"]
            outflow = data["outflow"]
            items.append(CashFlowItem(
                period=period,
                inflow=round(inflow, 2),
                outflow=round(outflow, 2),
                net=round(inflow - outflow, 2),
            ))
            calc_inflow += inflow
            calc_outflow += outflow
        
        # Use cash flow statement totals if available, otherwise use calculated
        if total_inflow == 0 and total_outflow == 0:
            total_inflow = calc_inflow
            total_outflow = calc_outflow
        
        await client.close()
        
        return CashFlowResponse(
            items=items,
            total_inflow=round(total_inflow, 2),
            total_outflow=round(total_outflow, 2),
            net_change=round(total_inflow - total_outflow, 2),
        )
        
    except ManagerIOError as e:
        logger.error(f"Manager.io API error in get_cash_flow: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )


@router.get(
    "/income-expense",
    response_model=IncomeExpenseResponse,
    summary="Get income vs expense",
    description="Get income and expense comparison by period.",
)
async def get_income_expense(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    db: AsyncSession = Depends(get_db),
) -> IncomeExpenseResponse:
    """Get income vs expense comparison.
    
    Validates: Requirement 7.4 - Display income vs expense comparison
    Validates: Requirement 7.6 - Retrieve payments, receipts
    Validates: Requirement 7.7 - Allow date range filtering
    
    Uses profit and loss statement from Manager.io for accurate figures.
    """
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=365)
    
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        
        # Try to get P&L statement first for accurate totals
        try:
            pnl = await client.get_profit_and_loss(
                from_date=start_date.isoformat(),
                to_date=end_date.isoformat()
            )
            logger.info(f"P&L response type: {type(pnl)}")
            
            # Parse P&L for totals
            total_income = 0.0
            total_expense = 0.0
            
            if isinstance(pnl, dict):
                # Try different field names
                total_income = float(
                    pnl.get("TotalIncome") or pnl.get("total_income") or
                    pnl.get("Income") or pnl.get("income") or
                    pnl.get("Revenue") or pnl.get("revenue") or 0
                )
                total_expense = float(
                    pnl.get("TotalExpenses") or pnl.get("total_expenses") or
                    pnl.get("Expenses") or pnl.get("expenses") or 0
                )
                
                # If totals not at top level, try to sum from groups
                if total_income == 0 and total_expense == 0:
                    for group in pnl.get("Groups", pnl.get("groups", [])):
                        group_name = group.get("Name") or group.get("name") or ""
                        group_total = float(group.get("Total") or group.get("total") or 0)
                        
                        if "income" in group_name.lower() or "revenue" in group_name.lower():
                            total_income += abs(group_total)
                        elif "expense" in group_name.lower() or "cost" in group_name.lower():
                            total_expense += abs(group_total)
            
            logger.info(f"P&L totals - Income: {total_income}, Expense: {total_expense}")
            
        except Exception as e:
            logger.warning(f"Could not get P&L statement: {e}, falling back to transaction calculation")
            total_income = 0.0
            total_expense = 0.0
        
        # Get monthly breakdown from transactions
        receipts = await client.fetch_all_paginated("/receipts")
        payments = await client.fetch_all_paginated("/payments")
        
        # Apply date range filtering
        receipts = filter_by_date_range(receipts, start_date, end_date)
        payments = filter_by_date_range(payments, start_date, end_date)
        
        # Group by month
        monthly_data: Dict[str, Dict[str, float]] = {}
        
        for receipt in receipts:
            receipt_date = receipt.get("Date", "")
            if receipt_date:
                month = receipt_date[:7]
                if month not in monthly_data:
                    monthly_data[month] = {"income": 0.0, "expense": 0.0}
                monthly_data[month]["income"] += float(receipt.get("Amount") or receipt.get("amount") or 0)
        
        for payment in payments:
            payment_date = payment.get("Date", "")
            if payment_date:
                month = payment_date[:7]
                if month not in monthly_data:
                    monthly_data[month] = {"income": 0.0, "expense": 0.0}
                monthly_data[month]["expense"] += float(payment.get("Amount") or payment.get("amount") or 0)
        
        items = []
        calc_income = 0.0
        calc_expense = 0.0
        
        for period in sorted(monthly_data.keys()):
            data = monthly_data[period]
            items.append(IncomeExpenseItem(
                period=period,
                income=round(data["income"], 2),
                expense=round(data["expense"], 2),
            ))
            calc_income += data["income"]
            calc_expense += data["expense"]
        
        # Use P&L totals if available, otherwise use calculated
        if total_income == 0 and total_expense == 0:
            total_income = calc_income
            total_expense = calc_expense
        
        await client.close()
        
        return IncomeExpenseResponse(
            items=items,
            total_income=round(total_income, 2),
            total_expense=round(total_expense, 2),
            net_profit=round(total_income - total_expense, 2),
        )
        
    except ManagerIOError as e:
        logger.error(f"Manager.io API error in get_income_expense: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )


@router.get(
    "/expense-breakdown",
    response_model=ExpenseBreakdownResponse,
    summary="Get expense breakdown",
    description="Get expense breakdown by category/account.",
)
async def get_expense_breakdown(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    start_date: Optional[date] = Query(None, description="Start date"),
    end_date: Optional[date] = Query(None, description="End date"),
    db: AsyncSession = Depends(get_db),
) -> ExpenseBreakdownResponse:
    """Get expense breakdown by category.
    
    Validates: Requirement 7.5 - Display expense breakdown by category
    Validates: Requirement 7.6 - Retrieve payments
    Validates: Requirement 7.7 - Allow date range filtering
    
    Uses P&L statement for accurate expense categorization when available.
    """
    if not end_date:
        end_date = date.today()
    if not start_date:
        start_date = end_date - timedelta(days=365)
    
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        
        # Try to get expense breakdown from P&L statement
        by_account: Dict[str, float] = defaultdict(float)
        total = 0.0
        
        try:
            pnl = await client.get_profit_and_loss(
                from_date=start_date.isoformat(),
                to_date=end_date.isoformat()
            )
            logger.info(f"P&L for expense breakdown: {type(pnl)}")
            
            if isinstance(pnl, dict):
                # Look for expense groups
                for group in pnl.get("Groups", pnl.get("groups", [])):
                    group_name = group.get("Name") or group.get("name") or ""
                    
                    # Only process expense groups
                    if "expense" in group_name.lower() or "cost" in group_name.lower():
                        # Get individual accounts in this group
                        for account in group.get("Accounts", group.get("accounts", [])):
                            acc_name = account.get("Name") or account.get("name") or "Other"
                            acc_amount = abs(float(account.get("Amount") or account.get("amount") or 
                                                   account.get("Balance") or account.get("balance") or 0))
                            if acc_amount > 0:
                                by_account[acc_name] += acc_amount
                                total += acc_amount
                        
                        # If no individual accounts, use group total
                        if not group.get("Accounts") and not group.get("accounts"):
                            group_total = abs(float(group.get("Total") or group.get("total") or 0))
                            if group_total > 0:
                                by_account[group_name] += group_total
                                total += group_total
            
            logger.info(f"Expense breakdown from P&L: {len(by_account)} categories, total: {total}")
            
        except Exception as e:
            logger.warning(f"Could not get P&L for expense breakdown: {e}")
        
        # If P&L didn't give us data, fall back to payments
        if not by_account:
            logger.info("Falling back to payments for expense breakdown")
            
            # Get accounts for names
            accounts = await client.get_chart_of_accounts()
            account_names = {acc.key: acc.name for acc in accounts}
            
            # Fetch payments
            payments = await client.fetch_all_paginated("/payments")
            
            # Apply date range filtering
            payments = filter_by_date_range(payments, start_date, end_date)
            
            # Group by account
            for payment in payments:
                account_key = payment.get("Account", "")
                amount = float(payment.get("Amount") or payment.get("amount") or 0)
                
                account_name = account_names.get(account_key, "Other")
                by_account[account_name] += amount
                total += amount
        
        # Build categories
        categories = []
        for category, amount in sorted(by_account.items(), key=lambda x: -x[1]):
            percentage = (amount / total * 100) if total > 0 else 0
            categories.append(ExpenseCategory(
                category=category,
                amount=round(amount, 2),
                percentage=round(percentage, 1),
            ))
        
        await client.close()
        
        return ExpenseBreakdownResponse(
            categories=categories[:10],  # Top 10 categories
            total=round(total, 2),
        )
        
    except ManagerIOError as e:
        logger.error(f"Manager.io API error in get_expense_breakdown: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )


@router.get(
    "/recent-transactions",
    response_model=RecentTransactionsResponse,
    summary="Get recent transactions",
    description="Get recent transactions for context.",
)
async def get_recent_transactions(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    limit: int = Query(50, description="Maximum number of transactions to return", ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> RecentTransactionsResponse:
    """Get recent transactions.
    
    Validates: Requirement 7.9 - Return recent transactions for context
    Validates: Requirement 7.6 - Retrieve payments, receipts, transfers, journal entries
    
    Returns the most recent transactions across all types.
    """
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        
        # Get accounts for names
        accounts = await client.get_chart_of_accounts()
        account_names = {acc.key: acc.name for acc in accounts}
        
        # Fetch recent transactions from each type
        payments = await client.fetch_all_paginated("/payments")
        receipts = await client.fetch_all_paginated("/receipts")
        transfers = await client.fetch_all_paginated("/inter-account-transfers")
        
        # Combine all transactions
        all_transactions: List[RecentTransaction] = []
        
        for payment in payments:
            account_key = payment.get("Account", "")
            all_transactions.append(RecentTransaction(
                date=payment.get("Date", "")[:10],
                type="payment",
                description=payment.get("Description", payment.get("Payee", "Payment")),
                amount=-float(payment.get("Amount", 0)),  # Negative for outflow
                account=account_names.get(account_key),
            ))
        
        for receipt in receipts:
            account_key = receipt.get("Account", receipt.get("BankAccount", ""))
            all_transactions.append(RecentTransaction(
                date=receipt.get("Date", "")[:10],
                type="receipt",
                description=receipt.get("Description", receipt.get("Payer", "Receipt")),
                amount=float(receipt.get("Amount", 0)),  # Positive for inflow
                account=account_names.get(account_key),
            ))
        
        for transfer in transfers:
            all_transactions.append(RecentTransaction(
                date=transfer.get("Date", "")[:10],
                type="transfer",
                description=transfer.get("Description", "Transfer"),
                amount=float(transfer.get("Amount", 0)),
                account=None,
            ))
        
        # Sort by date descending and limit
        all_transactions.sort(key=lambda x: x.date, reverse=True)
        limited_transactions = all_transactions[:limit]
        
        await client.close()
        
        return RecentTransactionsResponse(
            transactions=limited_transactions,
            total_count=len(all_transactions),
        )
        
    except ManagerIOError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )


@router.get(
    "/account-balances",
    summary="Get all account balances",
    description="Get balances for all accounts from trial balance.",
)
async def get_account_balances(
    current_user: CurrentUser,
    company_id: str = Query(..., description="Company ID"),
    as_of_date: Optional[date] = Query(None, description="Balance as of this date"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get all account balances from trial balance.
    
    Returns account balances grouped by account ID/key.
    This is useful for getting accurate balances directly from Manager.io
    rather than calculating from transactions.
    """
    try:
        client = await get_manager_client(company_id, current_user.id, db)
        
        effective_date = as_of_date or date.today()
        
        # Get trial balance
        trial_balance = await client.get_trial_balance(effective_date.isoformat())
        logger.info(f"Trial balance response: {type(trial_balance)}")
        
        # Get chart of accounts for additional info
        accounts = await client.get_chart_of_accounts()
        account_info = {acc.key: {"name": acc.name, "code": acc.code} for acc in accounts}
        
        # Get bank accounts to identify cash accounts
        bank_accounts = await client.get_bank_accounts()
        bank_account_keys = set()
        for ba in bank_accounts:
            key = ba.get("Key") or ba.get("key") or ba.get("Guid") or ""
            if key:
                bank_account_keys.add(key)
        
        # Parse trial balance
        balances_by_account = []
        
        # Handle different response formats
        tb_items = []
        if isinstance(trial_balance, list):
            tb_items = trial_balance
        elif isinstance(trial_balance, dict):
            # Try different structures
            tb_items = trial_balance.get("items", trial_balance.get("data", []))
            
            # Check for grouped structure
            if not tb_items and "Groups" in trial_balance:
                for group in trial_balance.get("Groups", []):
                    group_name = group.get("Name") or group.get("name") or ""
                    for acc in group.get("Accounts", group.get("accounts", [])):
                        acc["_group"] = group_name
                        tb_items.append(acc)
            
            # Check for Accounts at top level
            if not tb_items and "Accounts" in trial_balance:
                tb_items = trial_balance.get("Accounts", [])
        
        for item in tb_items:
            account_key = (
                item.get("Key") or item.get("key") or 
                item.get("Account") or item.get("account") or
                item.get("AccountKey") or item.get("account_key") or ""
            )
            
            # Get balance
            balance = 0.0
            debit = float(item.get("Debit") or item.get("debit") or 0)
            credit = float(item.get("Credit") or item.get("credit") or 0)
            
            if "Balance" in item or "balance" in item:
                balance = float(item.get("Balance") or item.get("balance") or 0)
            else:
                balance = debit - credit
            
            account_name = (
                item.get("Name") or item.get("name") or
                account_info.get(account_key, {}).get("name") or "Unknown"
            )
            account_code = (
                item.get("Code") or item.get("code") or
                account_info.get(account_key, {}).get("code")
            )
            
            balances_by_account.append({
                "key": account_key,
                "name": account_name,
                "code": account_code,
                "debit": round(debit, 2),
                "credit": round(credit, 2),
                "balance": round(balance, 2),
                "is_bank_account": account_key in bank_account_keys,
                "group": item.get("_group"),
            })
        
        await client.close()
        
        # Calculate totals
        total_debit = sum(a["debit"] for a in balances_by_account)
        total_credit = sum(a["credit"] for a in balances_by_account)
        cash_total = sum(a["balance"] for a in balances_by_account if a["is_bank_account"])
        
        return {
            "as_of_date": effective_date.isoformat(),
            "accounts": balances_by_account,
            "total_accounts": len(balances_by_account),
            "total_debit": round(total_debit, 2),
            "total_credit": round(total_credit, 2),
            "cash_total": round(cash_total, 2),
            "raw_trial_balance": trial_balance,  # Include raw data for debugging
        }
        
    except ManagerIOError as e:
        logger.error(f"Manager.io API error in get_account_balances: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Manager.io API error: {str(e)}",
        )
