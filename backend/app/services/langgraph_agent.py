"""LangGraph-based bookkeeping agent with multi-agent architecture.

Architecture:
- Supervisor: Routes requests to specialized sub-agents
- DataAgent: Queries accounts, suppliers, transactions, reports
- DocumentAgent: OCR, classification, matching
- EntryAgent: Creates/modifies entries in Manager.io

Each sub-agent has a focused toolset (~5-8 tools) for better LLM performance.
"""

import json
import logging
import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence, TypedDict, Union

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.ocr import OCRService

logger = logging.getLogger(__name__)


# =============================================================================
# Helper Functions
# =============================================================================


def strip_thinking_tags(text: str) -> str:
    """Remove thinking content from LLM responses.
    
    Handles multiple patterns:
    - <think>...</think> blocks
    - Content before </think> (no opening tag)
    - Repetition loops (model stuck repeating same phrase)
    """
    if not text:
        return text
    
    # Pattern 1: Some models output thinking then </think> to mark the real response (no opening tag)
    if '</think>' in text.lower():
        # Take everything after the last </think>
        parts = re.split(r'</think>', text, flags=re.IGNORECASE)
        text = parts[-1]
    
    # Pattern 2: Remove <think>...</think> blocks (including multiline)
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL | re.IGNORECASE)
    
    # Pattern 3: Detect repetition loops (same phrase repeated many times)
    # This catches models stuck in "Wait, I need to check..." loops
    lines = cleaned.split('\n')
    if len(lines) > 20:
        # Check for repetitive content
        line_counts = {}
        for line in lines:
            line_stripped = line.strip()
            if len(line_stripped) > 20:  # Only count substantial lines
                line_counts[line_stripped] = line_counts.get(line_stripped, 0) + 1
        
        # If any line repeats more than 5 times, it's likely a loop
        max_repeats = max(line_counts.values()) if line_counts else 0
        if max_repeats > 5:
            logger.warning(f"Detected repetition loop ({max_repeats} repeats), truncating response")
            # Try to extract just the final decision/answer
            # Look for routing keywords at the end
            for keyword in ['DIRECT', 'DATA', 'REPORT', 'TRANSACTION', 'INVENTORY', 'INVESTMENT', 'DOCUMENT', 'ENTRY']:
                if keyword in cleaned.upper():
                    return keyword
            # Otherwise return a truncated version
            cleaned = cleaned[:500] + "... [truncated due to repetition]"
    
    # Clean up extra whitespace
    cleaned = cleaned.strip()
    return cleaned


# =============================================================================
# Models
# =============================================================================


class DocumentType(str, Enum):
    RECEIPT = "receipt"
    INVOICE = "invoice"
    EXPENSE = "expense"
    UNKNOWN = "unknown"


class ProcessedDocument(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    document_type: DocumentType = DocumentType.UNKNOWN
    filename: Optional[str] = None
    status: str = "pending"
    extracted_data: Optional[Dict[str, Any]] = None
    matched_supplier: Optional[Dict[str, Any]] = None
    matched_account: Optional[Dict[str, Any]] = None
    prepared_entry: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AgentEvent(BaseModel):
    type: str
    status: Literal["started", "completed", "error"] = "started"
    message: str
    data: Optional[Dict[str, Any]] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ThinkingStep(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: Literal["thinking", "tool_call", "tool_result", "routing", "observation"]
    content: str
    tool_name: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Any] = None
    agent: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# =============================================================================
# State Definition
# =============================================================================


class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    conversation_id: str
    user_id: str
    company_id: str
    company_name: str
    accounts: List[Dict[str, Any]]
    suppliers: List[Dict[str, Any]]
    processed_documents: List[ProcessedDocument]
    thinking_steps: List[ThinkingStep]
    events: List[AgentEvent]
    current_agent: str  # "supervisor", "data", "document", "entry"
    should_continue: bool
    confirm_submission: bool


# =============================================================================
# Tool Definitions by Agent
# =============================================================================


def create_data_tools(
    accounts: List[Dict[str, Any]],
    suppliers: List[Dict[str, Any]],
    manager_client=None,
) -> List[BaseTool]:
    """Tools for querying master data (accounts, contacts, etc)."""
    from langchain_core.tools import tool
    
    @tool
    async def get_chart_of_accounts() -> str:
        """Get chart of accounts with key, name, code."""
        if accounts:
            return json.dumps(accounts[:100], indent=2)
        if manager_client:
            try:
                accts = await manager_client.get_chart_of_accounts()
                return json.dumps([{"key": a.key, "name": a.name, "code": a.code} for a in accts][:100], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "No data available"
    
    @tool
    async def get_suppliers() -> str:
        """Get suppliers list with key and name."""
        if suppliers:
            return json.dumps(suppliers[:100], indent=2)
        if manager_client:
            try:
                sups = await manager_client.get_suppliers()
                return json.dumps([{"key": s.key, "name": s.name} for s in sups][:100], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "No data available"
    
    @tool
    async def get_customers() -> str:
        """Get customers list."""
        if manager_client:
            try:
                custs = await manager_client.get_customers()
                return json.dumps([{"key": c.key, "name": c.name} for c in custs][:100], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_bank_accounts() -> str:
        """Get bank and cash accounts."""
        if manager_client:
            try:
                banks = await manager_client.get_bank_accounts()
                return json.dumps(banks[:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_employees() -> str:
        """Get employees (for expense claims)."""
        if manager_client:
            try:
                emps = await manager_client.get_employees()
                return json.dumps([{"key": e.get("Key"), "name": e.get("Name")} for e in emps][:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_tax_codes() -> str:
        """Get tax codes for applying correct tax rates."""
        if manager_client:
            try:
                codes = await manager_client.get_tax_codes()
                return json.dumps(codes[:30], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_projects() -> str:
        """Get projects for tracking income/expenses by project."""
        if manager_client:
            try:
                projects = await manager_client.get_projects()
                return json.dumps(projects[:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_fixed_assets() -> str:
        """Get fixed assets (property, equipment, vehicles)."""
        if manager_client:
            try:
                assets = await manager_client.get_fixed_assets()
                return json.dumps(assets[:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_current_context() -> str:
        """Get current date, time, timezone, location, and company financial year info.
        
        Use this tool when you need to know:
        - Today's date
        - Current time and timezone
        - Company's financial year end date
        - Company location/address
        
        This is essential for date-relative queries like "this month", "last quarter", "YTD"."""
        from datetime import datetime, timezone as tz, timedelta
        import zoneinfo
        
        # Default to Hong Kong timezone (common for this app)
        try:
            hk_tz = zoneinfo.ZoneInfo("Asia/Hong_Kong")
            now = datetime.now(hk_tz)
        except Exception:
            now = datetime.now(tz.utc)
            hk_tz = tz.utc
        
        context = {
            "today": now.strftime("%Y-%m-%d"),
            "current_time": now.strftime("%H:%M:%S"),
            "day_of_week": now.strftime("%A"),
            "timezone": str(hk_tz),
            "utc_offset": now.strftime("%z"),
            "current_year": now.year,
            "current_month": now.month,
            "current_quarter": (now.month - 1) // 3 + 1,
        }
        
        # Try to get company business details from Manager.io
        if manager_client:
            try:
                # Use the generic API call to get business details
                # The business info is usually in the response of any API call
                response = await manager_client._request("GET", "/chart-of-accounts", params={"pageSize": 1})
                if response and "business" in response:
                    business = response["business"]
                    context["company_name"] = business.get("name", "Unknown")
                    context["company_key"] = business.get("key", "")
            except Exception:
                pass
            
            try:
                # Try to get lock date (indicates year-end processing)
                lock_response = await manager_client._request("GET", "/lock-date-form")
                if lock_response:
                    context["lock_date_info"] = lock_response
            except Exception:
                pass
        
        # Common financial year ends (can be customized per company)
        # Default assumption: Dec 31 year-end
        context["assumed_year_end"] = {
            "month": 12,
            "day": 31,
            "note": "Default assumption - verify with company records"
        }
        
        # Calculate useful date ranges
        last_month_date = now.replace(day=1) - timedelta(days=1)
        context["date_ranges"] = {
            "this_month_start": now.replace(day=1).strftime("%Y-%m-%d"),
            "this_year_start": f"{now.year}-01-01",
            "last_year": now.year - 1,
            "last_month": last_month_date.strftime("%Y-%m"),
        }
        
        return json.dumps(context, indent=2)
    
    return [get_chart_of_accounts, get_suppliers, get_customers, get_bank_accounts, 
            get_employees, get_tax_codes, get_projects, get_fixed_assets, get_current_context]


def create_report_tools(manager_client=None) -> List[BaseTool]:
    """Tools for financial reports."""
    from langchain_core.tools import tool
    
    @tool
    async def get_balance_sheet(as_of_date: Optional[str] = None) -> str:
        """Get balance sheet report - financial position.
        Args: as_of_date (optional, YYYY-MM-DD format)"""
        if manager_client:
            try:
                report = await manager_client.get_balance_sheet(as_of_date)
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_profit_and_loss(from_date: Optional[str] = None, to_date: Optional[str] = None) -> str:
        """Get profit and loss (income statement) report.
        Args: from_date (optional, YYYY-MM-DD), to_date (optional, YYYY-MM-DD)"""
        if manager_client:
            try:
                report = await manager_client.get_profit_and_loss(from_date, to_date)
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_trial_balance(as_of_date: Optional[str] = None) -> str:
        """Get trial balance report - all account balances with debits/credits.
        Args: as_of_date (optional, YYYY-MM-DD format)"""
        if manager_client:
            try:
                report = await manager_client.get_trial_balance(as_of_date)
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_general_ledger_summary(from_date: Optional[str] = None, to_date: Optional[str] = None) -> str:
        """Get general ledger summary - account movements with opening/closing balances.
        Args: from_date (optional, YYYY-MM-DD), to_date (optional, YYYY-MM-DD)"""
        if manager_client:
            try:
                report = await manager_client.get_general_ledger_summary(from_date, to_date)
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_cash_flow_statement(from_date: Optional[str] = None, to_date: Optional[str] = None) -> str:
        """Get cash flow statement report.
        Args: from_date (optional, YYYY-MM-DD), to_date (optional, YYYY-MM-DD)"""
        if manager_client:
            try:
                report = await manager_client.get_cash_flow_statement(from_date, to_date)
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_aged_receivables() -> str:
        """Get aged receivables - outstanding customer invoices by age."""
        if manager_client:
            try:
                report = await manager_client.get_aged_receivables()
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_aged_payables() -> str:
        """Get aged payables - outstanding supplier invoices by age."""
        if manager_client:
            try:
                report = await manager_client.get_aged_payables()
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_account_balances() -> str:
        """Get current balances for all accounts (uses trial balance)."""
        if manager_client:
            try:
                report = await manager_client.get_trial_balance()
                return json.dumps(report, indent=2) if report else "No data"
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    return [get_balance_sheet, get_profit_and_loss, get_trial_balance, 
            get_general_ledger_summary, get_cash_flow_statement,
            get_aged_receivables, get_aged_payables, get_account_balances]


def create_transaction_tools(manager_client=None) -> List[BaseTool]:
    """Tools for fetching transactions and documents."""
    from langchain_core.tools import tool
    
    def format_amount(amount_obj) -> str:
        """Format nested amount object to string."""
        if isinstance(amount_obj, dict):
            value = amount_obj.get("value", 0)
            currency = amount_obj.get("currency", "")
            return f"{currency} {value:,.2f}" if currency else f"{value:,.2f}"
        return str(amount_obj) if amount_obj else "0"
    
    def format_payment(txn: dict) -> dict:
        """Format a payment (money OUT - we paid someone)."""
        return {
            "type": "payment",
            "direction": "OUT (we paid)",
            "date": txn.get("date") or txn.get("Date"),
            "paid_to": txn.get("payee") or txn.get("Payee", ""),
            "paid_from_account": txn.get("paidFrom") or txn.get("PaidFrom", ""),
            "description": txn.get("description") or txn.get("Description", ""),
            "amount": format_amount(txn.get("amount") or txn.get("Amount")),
        }
    
    def format_receipt(txn: dict) -> dict:
        """Format a receipt (money IN - someone paid us)."""
        received_in = txn.get("receivedIn") or txn.get("ReceivedIn")
        if isinstance(received_in, dict):
            received_in = received_in.get("name", str(received_in))
        return {
            "type": "receipt",
            "direction": "IN (we received)",
            "date": txn.get("date") or txn.get("Date"),
            "received_from": txn.get("paidBy") or txn.get("PaidBy", ""),
            "received_in_account": received_in or "",
            "description": txn.get("description") or txn.get("Description", ""),
            "amount": format_amount(txn.get("amount") or txn.get("Amount")),
        }
    
    @tool
    async def get_recent_transactions(limit: int = 30) -> str:
        """Get recent payments (money OUT) and receipts (money IN).
        
        Returns transactions with clear direction:
        - payment/OUT: We paid someone (they are our supplier/vendor)
        - receipt/IN: Someone paid us (they are our customer/client)
        
        Args: limit (default 30)"""
        if manager_client:
            try:
                txns = []
                try:
                    payments = await manager_client.get_payments(skip=0, take=limit//2)
                    for p in payments.items:
                        txns.append(format_payment(p))
                except: pass
                try:
                    receipts = await manager_client.get_receipts(skip=0, take=limit//2)
                    for r in receipts.items:
                        txns.append(format_receipt(r))
                except: pass
                # Sort by date descending
                txns.sort(key=lambda x: x.get("date", ""), reverse=True)
                return json.dumps(txns[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_payments(limit: int = 50) -> str:
        """Get payments (money OUT - we paid suppliers/vendors).
        
        Use this to find what we paid to a specific supplier.
        The 'paid_to' field shows who we paid.
        
        Args: limit (default 50)"""
        if manager_client:
            try:
                payments = await manager_client.get_payments(skip=0, take=limit)
                formatted = [format_payment(p) for p in payments.items[:limit]]
                return json.dumps(formatted, indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_receipts(limit: int = 50) -> str:
        """Get receipts (money IN - customers/clients paid us).
        
        Use this to find what a specific customer paid us.
        The 'received_from' field shows who paid us.
        
        Args: limit (default 50)"""
        if manager_client:
            try:
                receipts = await manager_client.get_receipts(skip=0, take=limit)
                formatted = [format_receipt(r) for r in receipts.items[:limit]]
                return json.dumps(formatted, indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_expense_claims(limit: int = 30) -> str:
        """Get expense claims (money OUT - employee expenses to be reimbursed).
        
        Expense claims are costs we incurred, paid by employees, to be reimbursed.
        The 'payee' is who we paid (the vendor/merchant).
        
        Args: limit"""
        if manager_client:
            try:
                claims = await manager_client.get_expense_claims(skip=0, take=limit)
                formatted = []
                for c in claims.items[:limit]:
                    formatted.append({
                        "type": "expense_claim",
                        "direction": "OUT (we paid via employee)",
                        "date": c.get("date") or c.get("Date"),
                        "paid_to": c.get("payee") or c.get("Payee"),
                        "description": c.get("description") or c.get("Description"),
                        "amount": format_amount(c.get("amount") or c.get("Amount")),
                        "expense_accounts": c.get("accounts") or c.get("Accounts", ""),
                    })
                return json.dumps(formatted, indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_purchase_invoices(limit: int = 30) -> str:
        """Get purchase invoices (bills FROM suppliers - we owe them money).
        
        Purchase invoices are bills we received from suppliers.
        The 'supplier' is who we owe money to.
        
        Args: limit"""
        if manager_client:
            try:
                invoices = await manager_client.get_purchase_invoices(skip=0, take=limit)
                formatted = []
                for inv in invoices.items[:limit]:
                    formatted.append({
                        "type": "purchase_invoice",
                        "direction": "IN (bill from supplier - we owe)",
                        "date": inv.get("issueDate") or inv.get("IssueDate"),
                        "reference": inv.get("reference") or inv.get("Reference"),
                        "supplier": inv.get("supplier") or inv.get("Supplier"),
                        "description": inv.get("description") or inv.get("Description"),
                        "amount": format_amount(inv.get("invoiceAmount") or inv.get("InvoiceAmount")),
                        "balance_due": format_amount(inv.get("balanceDue") or inv.get("BalanceDue")),
                        "status": inv.get("status") or inv.get("Status"),
                    })
                return json.dumps(formatted, indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_sales_invoices(limit: int = 30) -> str:
        """Get sales invoices (bills TO customers - they owe us money).
        
        Sales invoices are bills we sent to customers.
        The 'customer' is who owes us money.
        
        Args: limit"""
        if manager_client:
            try:
                invoices = await manager_client.get_sales_invoices(skip=0, take=limit)
                formatted = []
                for inv in invoices.items[:limit]:
                    formatted.append({
                        "type": "sales_invoice",
                        "direction": "OUT (bill to customer - they owe)",
                        "date": inv.get("issueDate") or inv.get("IssueDate"),
                        "reference": inv.get("reference") or inv.get("Reference"),
                        "customer": inv.get("customer") or inv.get("Customer"),
                        "description": inv.get("description") or inv.get("Description"),
                        "amount": format_amount(inv.get("invoiceAmount") or inv.get("InvoiceAmount")),
                        "balance_due": format_amount(inv.get("balanceDue") or inv.get("BalanceDue")),
                        "status": inv.get("status") or inv.get("Status"),
                    })
                return json.dumps(formatted, indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_credit_notes(limit: int = 30) -> str:
        """Get credit notes (refunds to customers). Args: limit"""
        if manager_client:
            try:
                notes = await manager_client.get_credit_notes(skip=0, take=limit)
                return json.dumps(notes.items[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_debit_notes(limit: int = 30) -> str:
        """Get debit notes (refunds from suppliers). Args: limit"""
        if manager_client:
            try:
                notes = await manager_client.get_debit_notes(skip=0, take=limit)
                return json.dumps(notes.items[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_sales_orders(limit: int = 30) -> str:
        """Get sales orders. Args: limit"""
        if manager_client:
            try:
                orders = await manager_client.get_sales_orders(skip=0, take=limit)
                return json.dumps(orders.items[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_purchase_orders(limit: int = 30) -> str:
        """Get purchase orders. Args: limit"""
        if manager_client:
            try:
                orders = await manager_client.get_purchase_orders(skip=0, take=limit)
                return json.dumps(orders.items[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    return [get_recent_transactions, get_payments, get_receipts, get_expense_claims, 
            get_purchase_invoices, get_sales_invoices, get_credit_notes, get_debit_notes, 
            get_sales_orders, get_purchase_orders]


def create_inventory_tools(manager_client=None) -> List[BaseTool]:
    """Tools for inventory management."""
    from langchain_core.tools import tool
    
    @tool
    async def get_inventory_items() -> str:
        """Get inventory items with quantities and values."""
        if manager_client:
            try:
                items = await manager_client.get_inventory_items()
                return json.dumps(items[:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_inventory_kits() -> str:
        """Get inventory kits (bundled products)."""
        if manager_client:
            try:
                kits = await manager_client.get_inventory_kits()
                return json.dumps(kits[:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_goods_receipts(limit: int = 30) -> str:
        """Get goods receipts (inventory received from suppliers). Args: limit"""
        if manager_client:
            try:
                receipts = await manager_client.get_goods_receipts(skip=0, take=limit)
                return json.dumps(receipts.items[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_delivery_notes(limit: int = 30) -> str:
        """Get delivery notes (inventory shipped to customers). Args: limit"""
        if manager_client:
            try:
                notes = await manager_client.get_delivery_notes(skip=0, take=limit)
                return json.dumps(notes.items[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def create_goods_receipt(
        supplier_key: str,
        date: str,
        items: str,
    ) -> str:
        """Create goods receipt for inventory received.
        Args: supplier_key, date (YYYY-MM-DD), items (JSON array of {item_key, qty})"""
        if not manager_client:
            return "Client not configured"
        try:
            item_list = json.loads(items)
            data = {
                "Supplier": supplier_key,
                "Date": date,
                "Lines": [{"Item": i["item_key"], "Qty": i["qty"]} for i in item_list]
            }
            result = await manager_client.create_goods_receipt(data)
            return f"Created goods receipt: {json.dumps(result)}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_inventory_write_off(
        date: str,
        items: str,
        description: str,
    ) -> str:
        """Write off inventory (damaged, lost, etc).
        Args: date (YYYY-MM-DD), items (JSON array of {item_key, qty}), description"""
        if not manager_client:
            return "Client not configured"
        try:
            item_list = json.loads(items)
            data = {
                "Date": date,
                "Description": description,
                "Lines": [{"Item": i["item_key"], "Qty": i["qty"]} for i in item_list]
            }
            result = await manager_client.create_inventory_write_off(data)
            return f"Created write-off: {json.dumps(result)}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_inventory_transfer(
        date: str,
        from_location: str,
        to_location: str,
        items: str,
    ) -> str:
        """Transfer inventory between locations.
        Args: date, from_location, to_location, items (JSON array of {item_key, qty})"""
        if not manager_client:
            return "Client not configured"
        try:
            item_list = json.loads(items)
            data = {
                "Date": date,
                "FromLocation": from_location,
                "ToLocation": to_location,
                "Lines": [{"Item": i["item_key"], "Qty": i["qty"]} for i in item_list]
            }
            result = await manager_client.create_inventory_transfer(data)
            return f"Created transfer: {json.dumps(result)}"
        except Exception as e:
            return f"Error: {e}"
    
    return [get_inventory_items, get_inventory_kits, get_goods_receipts, 
            get_delivery_notes, create_goods_receipt, create_inventory_write_off, 
            create_inventory_transfer]


def create_investment_tools(manager_client=None) -> List[BaseTool]:
    """Tools for investment tracking."""
    from langchain_core.tools import tool
    
    @tool
    async def get_investments() -> str:
        """Get investment accounts (stocks, bonds, funds, etc)."""
        if manager_client:
            try:
                investments = await manager_client.get_investments()
                return json.dumps(investments[:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_investment_transactions(limit: int = 50) -> str:
        """Get investment transactions (buys, sells, dividends). Args: limit"""
        if manager_client:
            try:
                txns = await manager_client.get_investment_transactions(skip=0, take=limit)
                return json.dumps(txns.items[:limit], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def get_investment_market_prices() -> str:
        """Get current market prices for investments."""
        if manager_client:
            try:
                prices = await manager_client.get_investment_market_prices()
                return json.dumps(prices[:50], indent=2)
            except Exception as e:
                return f"Error: {e}"
        return "Client not configured"
    
    @tool
    async def create_investment_account(
        name: str,
        code: Optional[str] = None,
    ) -> str:
        """Create a new investment account (for tracking stocks, bonds, etc).
        Args: name (investment name), code (optional account code)"""
        if not manager_client:
            return "Client not configured"
        try:
            data = {"Name": name}
            if code:
                data["Code"] = code
            result = await manager_client.create_investment(data)
            return f"Created investment account: {json.dumps({'success': result.success, 'key': result.key, 'message': result.message})}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    def handle_forex(
        amount: float,
        from_currency: str,
        to_currency: str,
        exchange_rate: Optional[float] = None,
    ) -> str:
        """Convert amount between currencies.
        Args: amount, from_currency (e.g., USD), to_currency (e.g., EUR), exchange_rate (optional, will use 1.0 if not provided)"""
        rate = exchange_rate or 1.0
        converted = amount * rate
        return json.dumps({
            "original_amount": amount,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "exchange_rate": rate,
            "converted_amount": round(converted, 2),
            "note": "Exchange rate should be verified with current market rates" if not exchange_rate else None
        }, indent=2)
    
    return [get_investments, get_investment_transactions, get_investment_market_prices,
            create_investment_account, handle_forex]


def create_generic_api_tool(manager_client=None) -> BaseTool:
    """Create a generic API tool that can call any Manager.io endpoint.
    
    This is a fallback tool for when specific tools don't cover the needed endpoint.
    """
    from langchain_core.tools import tool
    
    @tool
    async def call_manager_api(
        method: str,
        endpoint: str,
        params: Optional[Union[str, dict]] = None,
        data: Optional[Union[str, dict]] = None,
    ) -> str:
        """Call any Manager.io API endpoint directly. Use as fallback when specific tools don't exist.
        
        Args:
            method: HTTP method - GET, POST, PUT, DELETE
            endpoint: API endpoint path starting with / (e.g., "/receipts", "/supplier-form")
            params: Query params - can be JSON string '{"pageSize": 10}' or dict {"pageSize": 10}
            data: POST/PUT body - can be JSON string '{"Name": "Test"}' or dict {"Name": "Test"}
        
        API PATTERNS:
        
        1. LIST ENDPOINTS (GET) - Fetch multiple records:
           - GET /receipts, /payments, /expense-claims, /purchase-invoices, /sales-invoices
           - GET /suppliers, /customers, /employees, /bank-and-cash-accounts
           - GET /chart-of-accounts, /tax-codes, /projects, /fixed-assets
           - GET /inventory-items, /investments, /journal-entries
           - Params: {"skip": 0, "pageSize": 50}
           - Response: {"business": {...}, "totalRecords": N, "<dataKey>": [...]}
           - Data key is camelCase of endpoint (e.g., /expense-claims -> expenseClaims)
        
        2. FORM ENDPOINTS - CRUD operations on single records:
           - POST /supplier-form (create) -> Returns {"Key": "uuid"}
           - GET /supplier-form/{key} (read) -> Returns record data
           - PUT /supplier-form/{key} (update) -> Updates record
           - DELETE /supplier-form/{key} (delete) -> Deletes record
           - Common forms: supplier-form, customer-form, project-form, employee-form,
             expense-claim-form, purchase-invoice-form, sales-invoice-form, journal-entry-form
        
        3. REPORT ENDPOINTS - Two-step pattern:
           - Step 1: POST /report-form with params -> Returns {"Key": "uuid"}
           - Step 2: GET /report-view/{key} -> Returns report data
           - Working reports: general-ledger-summary, aged-receivables, aged-payables
           - Report params: {"FromDate": "2024-01-01", "ToDate": "2024-12-31"} or {"Date": "2024-12-31"}
           - Response: {"Subtitle": "...", "Columns": [...], "Rows": [...]}
        
        RESPONSE FORMAT:
        - List endpoints return: {"totalRecords": N, "<dataKey>": [{record}, ...]}
        - Form POST returns: {"Key": "uuid-of-created-record"}
        - Form GET returns: {field: value, ...} for the record
        - Report view returns: {"Subtitle": "...", "Columns": [...], "Rows": [...]}
        - Amounts are nested: {"amount": {"value": 100.00, "currency": "HKD"}}
        
        EXAMPLES:
        - Get suppliers: method="GET", endpoint="/suppliers", params='{"pageSize": 10}'
        - Create supplier: method="POST", endpoint="/supplier-form", data='{"Name": "Test Co", "Code": "TEST"}'
        - Get supplier by key: method="GET", endpoint="/supplier-form/uuid-here"
        - Get report: First POST to /general-ledger-summary-form with data='{}', then GET /general-ledger-summary-view/{key}
        
        Returns: JSON response from the API
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        
        try:
            # Ensure endpoint starts with /
            if not endpoint.startswith('/'):
                endpoint = '/' + endpoint
            
            # Parse params if provided
            params_dict = None
            if params:
                if isinstance(params, str):
                    if params.lower() == 'null' or params == '':
                        params_dict = None
                    else:
                        params_dict = json.loads(params)
                elif isinstance(params, dict):
                    params_dict = params
            
            # Parse data if provided
            data_dict = None
            if data:
                if isinstance(data, str):
                    if data.lower() == 'null' or data == '':
                        data_dict = None
                    else:
                        data_dict = json.loads(data)
                elif isinstance(data, dict):
                    data_dict = data
            
            result = await manager_client.call_api(
                method=method,
                endpoint=endpoint,
                params=params_dict,
                data=data_dict,
            )
            return json.dumps(result, indent=2, default=str)
        except json.JSONDecodeError as e:
            return f"Error parsing JSON: {e}. Make sure params and data are valid JSON strings like '{{}}' not {{}}"
        except Exception as e:
            return f"Error: {e}"
    
    return call_manager_api


def create_document_tools(
    accounts: List[Dict[str, Any]],
    suppliers: List[Dict[str, Any]],
    ocr_service: Optional[OCRService] = None,
) -> List[BaseTool]:
    """Tools for document processing and matching."""
    from langchain_core.tools import tool
    from difflib import SequenceMatcher
    
    tools = []
    
    @tool
    def search_supplier(vendor_name: str) -> str:
        """Search for supplier by name. Returns matches with confidence.
        Args: vendor_name - vendor/supplier name to search"""
        if not suppliers:
            return "No supplier data"
        
        matches = []
        name_lower = vendor_name.lower()
        for s in suppliers:
            sname = s.get("name", "").lower()
            if name_lower in sname or sname in name_lower:
                matches.append({"key": s.get("key"), "name": s.get("name"), "score": 0.9})
            else:
                score = SequenceMatcher(None, name_lower, sname).ratio()
                if score > 0.4:
                    matches.append({"key": s.get("key"), "name": s.get("name"), "score": round(score, 2)})
        
        matches.sort(key=lambda x: x["score"], reverse=True)
        return json.dumps(matches[:5], indent=2)
    
    @tool
    def search_account(description: str) -> str:
        """Search for expense account by keywords.
        Args: description - expense type keywords (e.g., 'office supplies', 'travel')"""
        if not accounts:
            return "No account data"
        
        matches = []
        desc_lower = description.lower()
        keywords = desc_lower.split()
        
        for a in accounts:
            name_lower = a.get("name", "").lower()
            kw_matches = sum(1 for k in keywords if k in name_lower)
            score = kw_matches / len(keywords) if keywords else 0
            seq_score = SequenceMatcher(None, desc_lower, name_lower).ratio()
            final = max(score, seq_score)
            
            if final > 0.3:
                matches.append({"key": a.get("key"), "name": a.get("name"), "code": a.get("code"), "score": round(final, 2)})
        
        matches.sort(key=lambda x: x["score"], reverse=True)
        return json.dumps(matches[:5], indent=2)
    
    @tool
    def classify_document(ocr_text: str) -> str:
        """Classify document type from OCR text.
        Args: ocr_text - extracted text from document
        Returns: document type (receipt, invoice, expense, unknown)"""
        text_lower = ocr_text.lower()
        
        if any(kw in text_lower for kw in ["invoice", "bill to", "due date", "payment terms", "inv#"]):
            return "invoice"
        elif any(kw in text_lower for kw in ["receipt", "thank you", "paid", "change due", "subtotal"]):
            return "receipt"
        elif any(kw in text_lower for kw in ["expense", "reimbursement", "claim"]):
            return "expense"
        return "unknown"
    
    @tool
    def extract_document_fields(ocr_text: str) -> str:
        """Extract key fields from document text.
        Args: ocr_text - extracted text
        Returns: JSON with vendor, amount, date, description"""
        import re
        
        result = {"vendor": None, "amount": None, "date": None, "description": None}
        
        # Amount patterns
        amount_patterns = [
            r'total[:\s]*\$?([\d,]+\.?\d*)',
            r'amount[:\s]*\$?([\d,]+\.?\d*)',
            r'\$\s*([\d,]+\.?\d{2})',
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, ocr_text, re.IGNORECASE)
            if match:
                result["amount"] = match.group(1).replace(",", "")
                break
        
        # Date patterns
        date_patterns = [
            r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})',
            r'(\d{4}[/-]\d{1,2}[/-]\d{1,2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, ocr_text)
            if match:
                result["date"] = match.group(1)
                break
        
        # First line often has vendor name
        lines = [l.strip() for l in ocr_text.split('\n') if l.strip()]
        if lines:
            result["vendor"] = lines[0][:50]
        
        return json.dumps(result, indent=2)
    
    @tool
    def match_vendor_to_supplier(vendor_name: str) -> str:
        """Match extracted vendor name to existing supplier.
        Args: vendor_name - vendor name from document
        Returns: best matching supplier or suggestion to create new"""
        if not suppliers or not vendor_name:
            return json.dumps({"matched": False, "suggestion": "No suppliers available"})
        
        vendor_lower = vendor_name.lower()
        best_match = None
        best_score = 0
        
        for s in suppliers:
            sname = s.get("name", "").lower()
            if vendor_lower in sname or sname in vendor_lower:
                return json.dumps({"matched": True, "supplier": s, "confidence": 0.95})
            
            score = SequenceMatcher(None, vendor_lower, sname).ratio()
            if score > best_score:
                best_score = score
                best_match = s
        
        if best_score > 0.6:
            return json.dumps({"matched": True, "supplier": best_match, "confidence": round(best_score, 2)})
        elif best_score > 0.4:
            return json.dumps({"matched": False, "possible_match": best_match, "confidence": round(best_score, 2), 
                             "suggestion": f"Low confidence match. Confirm if '{best_match.get('name')}' is correct."})
        return json.dumps({"matched": False, "suggestion": f"No match found for '{vendor_name}'. May need to create new supplier."})
    
    tools = [search_supplier, search_account, classify_document, extract_document_fields, match_vendor_to_supplier]
    return tools


def create_entry_tools(manager_client=None) -> List[BaseTool]:
    """Tools for creating/modifying entries in Manager.io."""
    from langchain_core.tools import tool
    
    # Helper function to check if string is a UUID
    def is_uuid(s: str) -> bool:
        try:
            uuid.UUID(s)
            return True
        except (ValueError, AttributeError):
            return False
    
    # Helper function to lookup employee by name
    async def lookup_employee(name_or_key: str) -> tuple[str, str]:
        """Returns (key, error_message). If successful, error_message is empty."""
        if is_uuid(name_or_key):
            return name_or_key, ""
        
        employees = await manager_client.get_employees()
        if isinstance(employees, dict):
            employee_list = employees.get("employees", [])
        else:
            employee_list = employees
        
        name_lower = name_or_key.lower()
        for emp in employee_list:
            if hasattr(emp, 'name'):
                emp_name, emp_key = emp.name, emp.key
            else:
                emp_name, emp_key = emp.get("name", ""), emp.get("key", "")
            if name_lower in emp_name.lower() or emp_name.lower() in name_lower:
                return emp_key, ""
        
        available = [e.name if hasattr(e, 'name') else e.get('name', '') for e in employee_list[:10]]
        return "", f"Could not find employee matching '{name_or_key}'. Available: {available}"
    
    # Helper function to lookup account by name
    async def lookup_account(name_or_key: str) -> tuple[str, str]:
        """Returns (key, error_message). If successful, error_message is empty."""
        if is_uuid(name_or_key):
            return name_or_key, ""
        
        accounts = await manager_client.get_chart_of_accounts()
        if isinstance(accounts, dict):
            account_list = accounts.get("chartOfAccounts", [])
        else:
            account_list = accounts
        
        name_lower = name_or_key.lower()
        for acc in account_list:
            if hasattr(acc, 'name'):
                acc_name, acc_key = acc.name, acc.key
            else:
                acc_name, acc_key = acc.get("name", ""), acc.get("key", "")
            if name_lower in acc_name.lower() or acc_name.lower() in name_lower:
                return acc_key, ""
        
        return "", f"Could not find account matching '{name_or_key}'"
    
    # Helper function to lookup bank account by name
    async def lookup_bank_account(name_or_key: str) -> tuple[str, str]:
        """Returns (key, error_message). If successful, error_message is empty."""
        if is_uuid(name_or_key):
            return name_or_key, ""
        
        bank_accounts = await manager_client.get_bank_accounts()
        if isinstance(bank_accounts, dict):
            account_list = bank_accounts.get("bankAndCashAccounts", [])
        else:
            account_list = bank_accounts
        
        name_lower = name_or_key.lower()
        for acc in account_list:
            if hasattr(acc, 'name'):
                acc_name, acc_key = acc.name, acc.key
            else:
                # manager_io.py returns normalized records with uppercase keys (Key, Name)
                acc_name = acc.get("Name") or acc.get("name") or ""
                acc_key = acc.get("Key") or acc.get("key") or ""
            if name_lower in acc_name.lower() or acc_name.lower() in name_lower:
                return acc_key, ""
        
        available = [a.name if hasattr(a, 'name') else (a.get('Name') or a.get('name') or '') for a in account_list[:10]]
        return "", f"Could not find bank account matching '{name_or_key}'. Available: {available}"
    
    # Helper function to lookup supplier by name
    async def lookup_supplier(name_or_key: str) -> tuple[str, str]:
        """Returns (key, error_message). If successful, error_message is empty."""
        if is_uuid(name_or_key):
            return name_or_key, ""
        
        suppliers = await manager_client.get_suppliers()
        if isinstance(suppliers, dict):
            supplier_list = suppliers.get("suppliers", [])
        else:
            supplier_list = suppliers
        
        name_lower = name_or_key.lower()
        for sup in supplier_list:
            if hasattr(sup, 'name'):
                sup_name, sup_key = sup.name, sup.key
            else:
                sup_name, sup_key = sup.get("name", ""), sup.get("key", "")
            if name_lower in sup_name.lower() or sup_name.lower() in name_lower:
                return sup_key, ""
        
        available = [s.name if hasattr(s, 'name') else s.get('name', '') for s in supplier_list[:10]]
        return "", f"Could not find supplier matching '{name_or_key}'. Available: {available}"
    
    # Helper function to lookup customer by name
    async def lookup_customer(name_or_key: str) -> tuple[str, str]:
        """Returns (key, error_message). If successful, error_message is empty."""
        if is_uuid(name_or_key):
            return name_or_key, ""
        
        customers = await manager_client.get_customers()
        if isinstance(customers, dict):
            customer_list = customers.get("customers", [])
        else:
            customer_list = customers
        
        name_lower = name_or_key.lower()
        for cust in customer_list:
            if hasattr(cust, 'name'):
                cust_name, cust_key = cust.name, cust.key
            else:
                cust_name, cust_key = cust.get("name", ""), cust.get("key", "")
            if name_lower in cust_name.lower() or cust_name.lower() in name_lower:
                return cust_key, ""
        
        available = [c.name if hasattr(c, 'name') else c.get('name', '') for c in customer_list[:10]]
        return "", f"Could not find customer matching '{name_or_key}'. Available: {available}"
    
    @tool
    async def search_employee(name: str) -> str:
        """Get all employees/directors to find the payer for expense claims.
        
        Args:
            name: Who you're looking for (e.g., "Winnie", "director")
                  This is just for context - all employees will be returned for you to choose from.
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            employees = await manager_client.get_employees()
            # Handle both list and dict responses
            if isinstance(employees, dict):
                employee_list = employees.get("employees", [])
            else:
                employee_list = employees
            
            # Build full employee list
            all_employees = []
            for emp in employee_list:
                if hasattr(emp, 'name'):
                    emp_name = emp.name
                    emp_key = emp.key
                else:
                    emp_name = emp.get("name", emp.get("Name", ""))
                    emp_key = emp.get("key", emp.get("Key", ""))
                if emp_key and emp_name:
                    all_employees.append({"key": emp_key, "name": emp_name})
            
            result = {
                "looking_for": name,
                "instruction": "Select the appropriate employee/director. Return the 'key' UUID.",
                "employees": all_employees
            }
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def search_account(description: str) -> str:
        """Get the Chart of Accounts to find the appropriate account for a transaction.
        
        Args:
            description: What you're looking for (e.g., "audit fee", "transportation", "office supplies")
                        This is just for context - the full COA will be returned for you to choose from.
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            accounts = await manager_client.get_chart_of_accounts()
            # Handle both list and dict responses
            if isinstance(accounts, dict):
                account_list = accounts.get("chartOfAccounts", [])
            else:
                account_list = accounts
            
            # Build full account list with key, name, code
            all_accounts = []
            for acc in account_list:
                if hasattr(acc, 'name'):
                    acc_name = acc.name
                    acc_key = acc.key
                    acc_code = acc.code if hasattr(acc, 'code') else ""
                else:
                    acc_name = acc.get("name", "")
                    acc_key = acc.get("key", "")
                    acc_code = acc.get("code", "") or ""
                all_accounts.append({"key": acc_key, "name": acc_name, "code": acc_code or ""})
            
            # Group by account type for easier reading
            expense_accounts = [a for a in all_accounts if (a["code"] or "").startswith("5")]
            income_accounts = [a for a in all_accounts if (a["code"] or "").startswith("4")]
            asset_accounts = [a for a in all_accounts if (a["code"] or "").startswith("1")]
            liability_accounts = [a for a in all_accounts if (a["code"] or "").startswith("2")]
            equity_accounts = [a for a in all_accounts if (a["code"] or "").startswith("3")]
            other_accounts = [a for a in all_accounts if not (a["code"] or "").startswith(("1","2","3","4","5"))]
            
            result = {
                "looking_for": description,
                "instruction": "Select the most appropriate account from the lists below. Return the 'key' UUID.",
                "expense_accounts": expense_accounts,
                "income_accounts": income_accounts,
                "asset_accounts": asset_accounts,
                "liability_accounts": liability_accounts,
                "equity_accounts": equity_accounts,
                "other_accounts": other_accounts,
            }
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_expense_claim(
        payer_key: str,
        date: str,
        description: str,
        account_key: str,
        amount: float,
        payee: Optional[str] = None,
    ) -> str:
        """Create expense claim - records expense paid by someone on behalf of the company.
        
        IMPORTANT: Use search_employee() and search_account() FIRST to get UUIDs!
        
        This creates:
        - DR: expense account (e.g., Meals & Entertainment, or Transportation)
        - CR: payer's account (e.g., Amount due to director)
        
        Args:
            payer_key: Employee/director UUID key (use search_employee to get this)
            date: Date in YYYY-MM-DD format
            description: Description of the expense
            account_key: Expense account UUID key (use search_account to get this)
            amount: Amount of the expense
            payee: Vendor/payee name (optional, defaults to description)
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            from app.services.manager_io import ExpenseClaimData, ExpenseClaimLine
            
            # Look up payer (employee/director) if name provided instead of key
            actual_payer_key, err = await lookup_employee(payer_key)
            if err:
                return f"Error: {err}"
            
            # Look up expense account if name provided instead of key
            actual_account_key, err = await lookup_account(account_key)
            if err:
                return f"Error: {err}"
            
            # Build proper ExpenseClaimData object
            expense_data = ExpenseClaimData(
                date=date,
                paid_by=actual_payer_key,
                payee=payee or description,  # Use payee if provided, otherwise use description
                description=description,
                lines=[
                    ExpenseClaimLine(
                        account=actual_account_key,
                        line_description=description,
                        qty=1,
                        purchase_unit_price=amount
                    )
                ],
                has_line_description=True
            )
            
            result = await manager_client.create_expense_claim(expense_data)
            if result.success:
                return f"Successfully created expense claim. Key: {result.key}"
            else:
                return f"Error creating expense claim: {result.message}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_purchase_invoice(
        supplier_key: str,
        date: str,
        description: str,
        account_key: str,
        amount: float,
        reference: Optional[str] = None,
    ) -> str:
        """Create purchase invoice from supplier.
        
        IMPORTANT: Get UUIDs first using search tools!
        
        Args:
            supplier_key: Supplier UUID key (get from supplier search/context)
            date: Date in YYYY-MM-DD format
            description: Description of the purchase
            account_key: Expense/asset account UUID key (use search_account to get this)
            amount: Invoice amount
            reference: Invoice reference number (optional)
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            from app.services.manager_io import PurchaseInvoiceData, PurchaseInvoiceLine
            
            # Look up supplier if name provided
            actual_supplier_key, err = await lookup_supplier(supplier_key)
            if err:
                return f"Error: {err}"
            
            # Look up account if name provided
            actual_account_key, err = await lookup_account(account_key)
            if err:
                return f"Error: {err}"
            
            invoice_data = PurchaseInvoiceData(
                issue_date=date,
                reference=reference or "",
                description=description,
                supplier=actual_supplier_key,
                lines=[
                    PurchaseInvoiceLine(
                        account=actual_account_key,
                        line_description=description,
                        purchase_unit_price=amount
                    )
                ],
                has_line_number=True,
                has_line_description=True
            )
            
            result = await manager_client.create_purchase_invoice(invoice_data)
            if result.success:
                return f"Successfully created purchase invoice. Key: {result.key}"
            else:
                return f"Error creating purchase invoice: {result.message}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_sales_invoice(
        customer_key: str,
        date: str,
        description: str,
        account_key: str,
        amount: float,
        reference: Optional[str] = None,
    ) -> str:
        """Create sales invoice to customer.
        
        IMPORTANT: Get UUIDs first using search tools!
        
        Args:
            customer_key: Customer UUID key (get from customer search/context)
            date: Date in YYYY-MM-DD format
            description: Description of the sale
            account_key: Income account UUID key (use search_account to get this)
            amount: Invoice amount
            reference: Invoice reference number (optional)
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            from app.services.manager_io import SalesInvoiceData, SalesInvoiceLine
            
            # Look up customer if name provided
            actual_customer_key, err = await lookup_customer(customer_key)
            if err:
                return f"Error: {err}"
            
            # Look up account if name provided
            actual_account_key, err = await lookup_account(account_key)
            if err:
                return f"Error: {err}"
            
            invoice_data = SalesInvoiceData(
                issue_date=date,
                reference=reference or "",
                description=description,
                customer=actual_customer_key,
                lines=[
                    SalesInvoiceLine(
                        account=actual_account_key,
                        line_description=description,
                        qty=1,
                        sales_unit_price=amount
                    )
                ],
                has_line_number=True,
                has_line_description=True
            )
            
            result = await manager_client.create_sales_invoice(invoice_data)
            if result.success:
                return f"Successfully created sales invoice. Key: {result.key}"
            else:
                return f"Error creating sales invoice: {result.message}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_payment(
        bank_account_key: str,
        date: str,
        payee: str,
        amount: float,
        account_key: Optional[str] = None,
        description: Optional[str] = None,
        supplier_key: Optional[str] = None,
        purchase_invoice_key: Optional[str] = None,
    ) -> str:
        """Create payment (money out from bank).
        
        IMPORTANT: Get UUIDs first using search tools!
        
        TWO MODES:
        1. PAYING A PURCHASE INVOICE: Use supplier_key + purchase_invoice_key. NO account_key needed.
           The expense was already recorded when invoice was created. Payment just clears Accounts Payable.
        2. DIRECT PAYMENT (no invoice): Use account_key to specify expense account.
        
        Args:
            bank_account_key: Bank/cash account UUID key (get from bank account search/context)
            date: Date in YYYY-MM-DD format
            payee: Who the payment is to (name - free text)
            amount: Payment amount
            account_key: Expense account UUID - ONLY for direct payments without invoice (optional)
            description: Description (optional)
            supplier_key: Supplier UUID - REQUIRED when paying a purchase invoice (optional)
            purchase_invoice_key: Purchase invoice UUID if paying specific invoice (optional)
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            # Look up bank account if name provided
            actual_bank_key, err = await lookup_bank_account(bank_account_key)
            if err:
                return f"Error: {err}"
            
            # Look up supplier if name provided
            actual_supplier_key = None
            if supplier_key:
                actual_supplier_key, err = await lookup_supplier(supplier_key)
                if err:
                    return f"Error: {err}"
            
            # Build line item based on payment type
            line = {
                "LineDescription": description or payee,
                "Amount": amount
            }
            
            # If paying against a purchase invoice
            if purchase_invoice_key and actual_supplier_key:
                # Payment against invoice - need Account (Accounts Payable), AccountsPayableSupplier, and PurchaseInvoice
                # First, find the Accounts Payable control account
                accounts = await manager_client.get_chart_of_accounts()
                if isinstance(accounts, dict):
                    account_list = accounts.get("chartOfAccounts", [])
                else:
                    account_list = accounts
                
                ap_account_key = None
                for acc in account_list:
                    acc_name = acc.name if hasattr(acc, 'name') else acc.get("name", "")
                    acc_key = acc.key if hasattr(acc, 'key') else acc.get("key", "")
                    # Look for "Accounts payable" or similar
                    if "accounts payable" in acc_name.lower() or "trade payable" in acc_name.lower():
                        ap_account_key = acc_key
                        break
                
                if not ap_account_key:
                    return "Error: Could not find Accounts Payable control account in Chart of Accounts"
                
                line["Account"] = ap_account_key
                line["AccountsPayableSupplier"] = actual_supplier_key
                line["PurchaseInvoice"] = purchase_invoice_key
            elif account_key:
                # Direct payment - need expense account
                actual_account_key, err = await lookup_account(account_key)
                if err:
                    return f"Error: {err}"
                line["Account"] = actual_account_key
            else:
                return "Error: Either provide purchase_invoice_key+supplier_key (for invoice payment) or account_key (for direct payment)"
            
            # Build payload
            if actual_supplier_key:
                # Payment to supplier
                data = {
                    "Date": date,
                    "PaidFrom": actual_bank_key,
                    "Payee": 2,  # Supplier
                    "Supplier": actual_supplier_key,
                    "Description": description or payee,
                    "Lines": [line],
                    "HasLineDescription": True
                }
            else:
                # Payment to other (free text payee)
                data = {
                    "Date": date,
                    "PaidFrom": actual_bank_key,
                    "Payee": 3,  # Other
                    "PayeeName": payee,
                    "Description": description or payee,
                    "Lines": [line],
                    "HasLineDescription": True
                }
            
            result = await manager_client._post("/payment-form", data)
            entry_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return f"Successfully created payment. Key: {entry_key}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_receipt(
        bank_account_key: str,
        date: str,
        payer: str,
        amount: float,
        account_key: Optional[str] = None,
        description: Optional[str] = None,
        customer_key: Optional[str] = None,
        sales_invoice_key: Optional[str] = None,
    ) -> str:
        """Create receipt (money in to bank).
        
        IMPORTANT: Get UUIDs first using search tools!
        
        TWO MODES:
        1. RECEIVING FOR A SALES INVOICE: Use customer_key + sales_invoice_key. NO account_key needed.
           The income was already recorded when invoice was created. Receipt just clears Accounts Receivable.
        2. DIRECT RECEIPT (no invoice): Use account_key to specify income account.
        
        Args:
            bank_account_key: Bank/cash account UUID key (get from bank account search/context)
            date: Date in YYYY-MM-DD format
            payer: Who the payment is from (name - free text)
            amount: Receipt amount
            account_key: Income account UUID - ONLY for direct receipts without invoice (optional)
            description: Description (optional)
            customer_key: Customer UUID - REQUIRED when receiving for a sales invoice (optional)
            sales_invoice_key: Sales invoice UUID if receiving for specific invoice (optional)
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            # Look up bank account if name provided
            actual_bank_key, err = await lookup_bank_account(bank_account_key)
            if err:
                return f"Error: {err}"
            
            # Look up customer if name provided
            actual_customer_key = None
            if customer_key:
                actual_customer_key, err = await lookup_customer(customer_key)
                if err:
                    return f"Error: {err}"
            
            # Build line item based on receipt type
            line = {
                "LineDescription": description or payer,
                "Amount": amount
            }
            
            # If receiving against a sales invoice
            if sales_invoice_key and actual_customer_key:
                # Receipt against invoice - need Account (Accounts Receivable), AccountsReceivableCustomer, and SalesInvoice
                # First, find the Accounts Receivable control account
                accounts = await manager_client.get_chart_of_accounts()
                if isinstance(accounts, dict):
                    account_list = accounts.get("chartOfAccounts", [])
                else:
                    account_list = accounts
                
                ar_account_key = None
                for acc in account_list:
                    acc_name = acc.name if hasattr(acc, 'name') else acc.get("name", "")
                    acc_key = acc.key if hasattr(acc, 'key') else acc.get("key", "")
                    # Look for "Accounts receivable" or "Trade receivables" or similar
                    if "accounts receivable" in acc_name.lower() or "trade receivable" in acc_name.lower():
                        ar_account_key = acc_key
                        break
                
                if not ar_account_key:
                    return "Error: Could not find Accounts Receivable control account in Chart of Accounts"
                
                line["Account"] = ar_account_key
                line["AccountsReceivableCustomer"] = actual_customer_key
                line["SalesInvoice"] = sales_invoice_key
            elif account_key:
                # Direct receipt - need income account
                actual_account_key, err = await lookup_account(account_key)
                if err:
                    return f"Error: {err}"
                line["Account"] = actual_account_key
            else:
                return "Error: Either provide sales_invoice_key+customer_key (for invoice receipt) or account_key (for direct receipt)"
            
            # Build payload
            if actual_customer_key:
                # Receipt from customer
                data = {
                    "Date": date,
                    "ReceivedIn": actual_bank_key,
                    "Customer": actual_customer_key,
                    "Description": description or payer,
                    "Lines": [line],
                    "HasLineDescription": True
                }
            else:
                # Receipt from other (free text payer)
                data = {
                    "Date": date,
                    "ReceivedIn": actual_bank_key,
                    "Payer": 3,  # Other
                    "PayerName": payer,
                    "Description": description or payer,
                    "Lines": [line],
                    "HasLineDescription": True
                }
            
            result = await manager_client._post("/receipt-form", data)
            entry_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return f"Successfully created receipt. Key: {entry_key}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_journal_entry(
        date: str,
        description: str,
        debit_account: str,
        credit_account: str,
        amount: float,
    ) -> str:
        """Create journal entry for adjustments.
        
        IMPORTANT: Get UUIDs first using search_account!
        
        Args:
            date: Date in YYYY-MM-DD format
            description: Narration/description of the entry
            debit_account: Account to debit UUID key (use search_account to get this)
            credit_account: Account to credit UUID key (use search_account to get this)
            amount: Amount to debit/credit
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            # Look up debit account if name provided
            actual_debit_key, err = await lookup_account(debit_account)
            if err:
                return f"Error: {err}"
            
            # Look up credit account if name provided
            actual_credit_key, err = await lookup_account(credit_account)
            if err:
                return f"Error: {err}"
            
            data = {
                "Date": date,
                "Narration": description,
                "Lines": [
                    {"Account": actual_debit_key, "Debit": amount},
                    {"Account": actual_credit_key, "Credit": amount},
                ]
            }
            
            result = await manager_client._post("/journal-entry-form", data)
            entry_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return f"Successfully created journal entry. Key: {entry_key}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_transfer(
        from_account: str,
        to_account: str,
        date: str,
        amount: float,
        description: Optional[str] = None,
    ) -> str:
        """Create inter-account transfer.
        
        IMPORTANT: Get UUIDs first!
        
        Args:
            from_account: Source bank/cash account UUID key (get from bank account search/context)
            to_account: Destination bank/cash account UUID key (get from bank account search/context)
            date: Date in YYYY-MM-DD format
            amount: Transfer amount
            description: Description (optional)
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            # Look up from account if name provided
            actual_from_key, err = await lookup_bank_account(from_account)
            if err:
                return f"Error: {err}"
            
            # Look up to account if name provided
            actual_to_key, err = await lookup_bank_account(to_account)
            if err:
                return f"Error: {err}"
            
            data = {
                "Date": date,
                "PaidFrom": actual_from_key,
                "ReceivedIn": actual_to_key,
                "CreditAmount": amount,
                "Description": description or ""
            }
            
            result = await manager_client._post("/inter-account-transfer-form", data)
            entry_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return f"Successfully created transfer. Key: {entry_key}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_credit_note(
        customer_key: str,
        date: str,
        description: str,
        account_key: str,
        amount: float,
    ) -> str:
        """Create credit note (refund to customer).
        
        IMPORTANT: Get UUIDs first!
        
        Args:
            customer_key: Customer UUID key (get from customer search/context)
            date: Date in YYYY-MM-DD format
            description: Description of the credit note
            account_key: Income account UUID key (use search_account to get this)
            amount: Credit note amount
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            # Look up customer if name provided
            actual_customer_key, err = await lookup_customer(customer_key)
            if err:
                return f"Error: {err}"
            
            # Look up account if name provided
            actual_account_key, err = await lookup_account(account_key)
            if err:
                return f"Error: {err}"
            
            # Credit notes use similar structure to sales invoices
            data = {
                "IssueDate": date,
                "Customer": actual_customer_key,
                "Description": description,
                "Lines": [{
                    "Account": actual_account_key,
                    "LineDescription": description,
                    "Qty": 1,
                    "SalesUnitPrice": amount
                }],
                "HasLineDescription": True
            }
            result = await manager_client._post("/credit-note-form", data)
            entry_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return f"Successfully created credit note. Key: {entry_key}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_debit_note(
        supplier_key: str,
        date: str,
        description: str,
        account_key: str,
        amount: float,
    ) -> str:
        """Create debit note (refund from supplier).
        
        IMPORTANT: Get UUIDs first!
        
        Args:
            supplier_key: Supplier UUID key (get from supplier search/context)
            date: Date in YYYY-MM-DD format
            description: Description of the debit note
            account_key: Expense account UUID key (use search_account to get this)
            amount: Debit note amount
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            # Look up supplier if name provided
            actual_supplier_key, err = await lookup_supplier(supplier_key)
            if err:
                return f"Error: {err}"
            
            # Look up account if name provided
            actual_account_key, err = await lookup_account(account_key)
            if err:
                return f"Error: {err}"
            
            # Debit notes use similar structure to purchase invoices
            data = {
                "IssueDate": date,
                "Supplier": actual_supplier_key,
                "Description": description,
                "Lines": [{
                    "Account": actual_account_key,
                    "LineDescription": description,
                    "PurchaseUnitPrice": amount
                }],
                "HasLineDescription": True
            }
            result = await manager_client._post("/debit-note-form", data)
            entry_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return f"Successfully created debit note. Key: {entry_key}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def amend_entry(
        entry_type: str,
        entry_key: str,
        updates: str,
    ) -> str:
        """Amend/update an existing entry.
        Args: entry_type (expense-claim, purchase-invoice, etc), entry_key, updates (JSON of fields to update)"""
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            update_data = json.loads(updates)
            result = await manager_client.update_entry(entry_type, entry_key, update_data)
            return f"Updated entry: {json.dumps(result)}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def delete_entry(
        entry_type: str,
        entry_key: str,
    ) -> str:
        """Delete an entry. Use with caution!
        Args: entry_type (expense-claim, purchase-invoice, etc), entry_key"""
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            result = await manager_client.delete_entry(entry_type, entry_key)
            return f"Deleted entry: {result}"
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    def extract_fields_from_ocr(ocr_text: str) -> str:
        """Extract key fields from OCR document text for creating entries.
        
        Args:
            ocr_text: The OCR text from a scanned document
            
        Returns: JSON with extracted fields (vendor, amount, date, description)
        """
        import re
        
        result = {
            "vendor": None,
            "amount": None,
            "date": None,
            "description": None,
            "currency": "HKD",
        }
        
        text = ocr_text.lower()
        
        # Extract amount - look for common patterns
        amount_patterns = [
            r'(?:total|amount paid|金額|總金額|合計)[:\s]*\$?([\d,]+\.?\d*)',
            r'\$\s*([\d,]+\.?\d*)',
            r'hkd\s*([\d,]+\.?\d*)',
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(',', '')
                try:
                    result["amount"] = float(amount_str)
                    break
                except ValueError:
                    pass
        
        # Extract date
        date_patterns = [
            r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})',
            r'(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+\d{2,4})',
            r'(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
        ]
        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                result["date"] = match.group(1)
                break
        
        # Try to extract vendor from first few lines
        lines = [l.strip() for l in ocr_text.split('\n') if l.strip()][:5]
        for line in lines:
            # Skip lines that are just numbers or very short
            clean = re.sub(r'<[^>]+>', '', line).strip()
            if len(clean) > 3 and not clean.replace('.', '').replace(',', '').isdigit():
                result["vendor"] = clean[:100]
                break
        
        return json.dumps(result, indent=2, ensure_ascii=False)
    
    @tool
    async def get_bank_accounts() -> str:
        """Get all bank and cash accounts to find where to pay from or receive into.
        
        Returns: List of bank/cash accounts with key, name, and current balance.
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            banks = await manager_client.get_bank_accounts()
            # Handle both list and dict responses
            if isinstance(banks, dict):
                bank_list = banks.get("bankAndCashAccounts", [])
            else:
                bank_list = banks
            
            all_banks = []
            for bank in bank_list:
                if hasattr(bank, 'name'):
                    bank_name = bank.name
                    bank_key = bank.key
                    balance = getattr(bank, 'actualBalance', None)
                else:
                    # manager_io.py returns normalized records with uppercase keys (Key, Name, Balance)
                    # Also check lowercase for raw API responses
                    bank_name = bank.get("Name") or bank.get("name") or ""
                    bank_key = bank.get("Key") or bank.get("key") or ""
                    balance = bank.get("Balance") or bank.get("actualBalance")
                
                bank_info = {"key": bank_key, "name": bank_name}
                if balance:
                    if isinstance(balance, dict):
                        bank_info["balance"] = f"{balance.get('currency', '')} {balance.get('value', 0):,.2f}"
                    else:
                        bank_info["balance"] = str(balance)
                all_banks.append(bank_info)
            
            result = {
                "instruction": "Select the appropriate bank/cash account. Return the 'key' UUID.",
                "bank_accounts": all_banks
            }
            return json.dumps(result, indent=2)
        except Exception as e:
            return f"Error: {e}"
    
    @tool
    async def create_supplier(
        name: str,
        code: Optional[str] = None,
    ) -> str:
        """Create a new supplier in the system.
        
        Use this when you need to create a purchase invoice but the supplier doesn't exist yet.
        
        Args:
            name: Supplier name (e.g., "ABC Company Limited")
            code: Optional supplier code (e.g., "ABC")
        
        Returns: The created supplier's UUID key
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            data = {"Name": name}
            if code:
                data["Code"] = code
            
            result = await manager_client._post("/supplier-form", data)
            supplier_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return json.dumps({
                "success": True,
                "supplier_key": supplier_key,
                "name": name,
                "message": f"Created supplier '{name}' with key {supplier_key}"
            }, indent=2)
        except Exception as e:
            return f"Error creating supplier: {e}"
    
    @tool
    async def create_customer(
        name: str,
        code: Optional[str] = None,
    ) -> str:
        """Create a new customer in the system.
        
        Use this when you need to create a sales invoice but the customer doesn't exist yet.
        
        Args:
            name: Customer name (e.g., "XYZ Company Limited")
            code: Optional customer code (e.g., "XYZ")
        
        Returns: The created customer's UUID key
        """
        if not manager_client:
            return "Error: Manager.io client not configured"
        try:
            data = {"Name": name}
            if code:
                data["Code"] = code
            
            result = await manager_client._post("/customer-form", data)
            customer_key = result.get("Key") or result.get("key") if isinstance(result, dict) else None
            return json.dumps({
                "success": True,
                "customer_key": customer_key,
                "name": name,
                "message": f"Created customer '{name}' with key {customer_key}"
            }, indent=2)
        except Exception as e:
            return f"Error creating customer: {e}"
    
    return [search_employee, search_account, get_bank_accounts, create_supplier, create_customer,
            create_expense_claim, create_purchase_invoice, create_sales_invoice,
            create_payment, create_receipt, create_journal_entry, create_transfer,
            create_credit_note, create_debit_note, amend_entry, delete_entry,
            extract_fields_from_ocr]


# =============================================================================
# System Prompts for Each Agent
# =============================================================================


SUPERVISOR_PROMPT = """You are a bookkeeping assistant supervisor for {company_name}.

IMPORTANT: Output ONLY one word. No thinking, no explanation, no reasoning. Just the routing word.

FIRST, decide if you can respond DIRECTLY without needing any tools or data lookups:
- Greetings (hi, hello, thanks, bye) → DIRECT
- General questions about what you can do → DIRECT  
- Simple clarifying questions → DIRECT
- Follow-up questions about previous actions → DIRECT
- Questions asking "why" about something you did → DIRECT
- Anything you can answer from general knowledge → DIRECT

If you need actual data or actions, route to a specialized agent:
- DATA: Master data queries (accounts, suppliers, customers, employees, bank accounts, tax codes)
- REPORT: Financial reports (balance sheet, P&L, trial balance, aged receivables/payables)
- TRANSACTION: Transaction queries - looking up payments, receipts, invoices, expense claims, orders from the system
- INVENTORY: Inventory management (items, goods receipts, transfers, write-offs)
- INVESTMENT: Investment tracking (stocks, bonds, dividends, forex)
- DOCUMENT: ONLY for classifying/extracting data from documents WITHOUT creating entries
- ENTRY: Create/modify entries (expense claims, invoices, payments, journals) - USE THIS when user wants to CREATE something

CRITICAL ROUTING RULES:
1. If message contains "[Document" and "OCR Text]" → This means documents were uploaded
2. If documents uploaded AND user wants to CREATE an entry → ENTRY
3. If documents uploaded AND user says "process" or "add" or "record" → ENTRY (they want to create entries)
4. If documents uploaded AND user just wants to see/classify → DOCUMENT
5. Default for uploaded documents: ENTRY (most users want to create entries from receipts/invoices)

ROUTING EXAMPLES:
- "show me the latest receipt from X" → TRANSACTION
- "what did we pay to supplier Y?" → TRANSACTION
- "[Document 1 OCR Text]... add this as expense claim" → ENTRY
- "[Document 1 OCR Text]... process these documents" → ENTRY (user wants to create entries)
- "[Document 1 OCR Text]... what is this document?" → DOCUMENT (just classifying)
- "create an expense claim for $100" → ENTRY
- "[Document 1 OCR Text]... [Document 2 OCR Text]..." → ENTRY (multiple docs = user wants to process them)
- "why did you use that account?" → DIRECT
- "can you change it to audit fee?" → ENTRY

OUTPUT: Respond with ONLY one word. No thinking. No explanation. Just: DIRECT, DATA, REPORT, TRANSACTION, INVENTORY, INVESTMENT, DOCUMENT, or ENTRY"""


DIRECT_RESPONSE_PROMPT = """You are a helpful bookkeeping assistant for {company_name}.

Respond naturally and helpfully to the user. Keep responses concise.

You can help with:
- Viewing financial reports (balance sheet, P&L, trial balance)
- Managing accounts, suppliers, customers
- Processing documents (receipts, invoices) via OCR
- Creating entries (expense claims, invoices, payments)
- Tracking inventory and investments

IMPORTANT: If the message contains "[Document" and "OCR Text]", this means documents were uploaded.
In this case, you should NOT respond directly - the request should be routed to the ENTRY agent.
If you see document OCR text, respond with: "I see you've uploaded documents. Let me process them and create the appropriate entries."

If the user needs specific data or wants to perform actions, let them know what you can do.

OUTPUT FORMAT (when applicable):
- For structured data, use <canvas>...</canvas> tags
- For thinking/reasoning, use <think>...</think> tags"""


DATA_AGENT_PROMPT = """You are a master data specialist for {company_name}.

You MUST use the available tools to answer questions. DO NOT say you don't have access - USE THE TOOLS.

Available tools:
- get_chart_of_accounts() - Get chart of accounts with key, name, code
- get_suppliers() - Get suppliers list with key and name
- get_customers() - Get customers list
- get_bank_accounts() - Get bank and cash accounts
- get_employees() - Get employees (for expense claims)
- get_tax_codes() - Get tax codes for applying correct tax rates
- get_projects() - Get projects for tracking income/expenses by project
- get_fixed_assets() - Get fixed assets (property, equipment, vehicles)
- get_current_context() - Get today's date, time, timezone, and company year-end info
- call_manager_api(method, endpoint, params, data) - Call any Manager.io API endpoint directly (fallback)

IMPORTANT: 
1. When asked about master data (accounts, suppliers, customers, etc.), ALWAYS call the appropriate tool first
2. When asked about dates, "today", "this month", "this year", etc., call get_current_context() first
3. Present the findings clearly
4. If a specific tool doesn't work, use call_manager_api as a fallback

Never say "I don't have access" - you DO have access through these tools."""


REPORT_AGENT_PROMPT = """You are a financial reporting specialist for {company_name}.

You MUST use the available tools to answer questions. DO NOT say you don't have access - USE THE TOOLS.

Available tools:
- get_balance_sheet(as_of_date) - Get balance sheet report (financial position)
- get_profit_and_loss(from_date, to_date) - Get profit and loss (income statement) report
- get_trial_balance(as_of_date) - Get trial balance report (all account balances with debits/credits)
- get_general_ledger_summary(from_date, to_date) - Get general ledger summary with account movements
- get_cash_flow_statement(from_date, to_date) - Get cash flow statement
- get_aged_receivables() - Get aged receivables (outstanding customer invoices by age)
- get_aged_payables() - Get aged payables (outstanding supplier invoices by age)
- get_account_balances() - Get current balances for all accounts
- call_manager_api(method, endpoint, params, data) - Call any Manager.io API endpoint directly (fallback)

IMPORTANT: When asked about financial reports or account balances:
1. ALWAYS call the appropriate tool first
2. Present the findings clearly
3. If a specific tool doesn't work, use call_manager_api as a fallback

OUTPUT FORMAT:
- For report data and tables, wrap in <canvas>...</canvas> tags
- Use markdown tables for clean formatting

Never say "I don't have access" - you DO have access through these tools."""


TRANSACTION_AGENT_PROMPT = """You are a transaction query specialist for {company_name}.

You MUST use the available tools to answer questions. DO NOT say you don't have access - USE THE TOOLS.

CRITICAL - UNDERSTAND TRANSACTION DIRECTIONS:
- PAYMENT (money OUT): We paid someone → they are our SUPPLIER/VENDOR
- RECEIPT (money IN): Someone paid us → they are our CUSTOMER/CLIENT
- PURCHASE INVOICE: Bill FROM a supplier → we OWE them money
- SALES INVOICE: Bill TO a customer → they OWE us money
- EXPENSE CLAIM: Employee paid on our behalf → we reimburse them

When an entity appears in BOTH payments and receipts, they may be:
- A customer we also buy from (e.g., related company)
- A supplier who also buys from us

Available tools:
- get_recent_transactions(limit) - Get recent payments (OUT) and receipts (IN) combined
- get_payments(limit) - Get payments only (money OUT - we paid suppliers)
- get_receipts(limit) - Get receipts only (money IN - customers paid us)
- get_expense_claims(limit) - Get expense claims (employee expenses)
- get_purchase_invoices(limit) - Get purchase invoices (bills FROM suppliers)
- get_sales_invoices(limit) - Get sales invoices (bills TO customers)
- get_credit_notes(limit) - Get credit notes (refunds TO customers)
- get_debit_notes(limit) - Get debit notes (refunds FROM suppliers)
- get_sales_orders(limit) - Get sales orders
- get_purchase_orders(limit) - Get purchase orders
- call_manager_api(method, endpoint, params, data) - Call any Manager.io API endpoint directly (fallback)

IMPORTANT: When presenting results, ALWAYS clearly indicate the direction:
- "We PAID [entity] HKD X" for payments (they are supplier)
- "We RECEIVED HKD X FROM [entity]" for receipts (they are customer)
- Group by direction when showing multiple transactions

For example, if asked "show transactions with Company X":
1. Call get_payments(limit=50) and get_receipts(limit=50)
2. Filter both for "Company X"
3. Present separately:
   - "Payments TO Company X (as supplier): ..."
   - "Receipts FROM Company X (as customer): ..."

Never say "I don't have access" - you DO have access through these tools."""


INVENTORY_AGENT_PROMPT = """You are an inventory management specialist for {company_name}.

You MUST use the available tools to answer questions. DO NOT say you don't have access - USE THE TOOLS.

Available tools:
- get_inventory_items() - Get inventory items with quantities and values
- get_inventory_kits() - Get inventory kits (bundled products)
- get_goods_receipts(limit) - Get goods receipts (inventory received from suppliers)
- get_delivery_notes(limit) - Get delivery notes (inventory shipped to customers)
- create_goods_receipt(supplier_key, date, items) - Create goods receipt for inventory received
- create_inventory_write_off(date, items, description) - Write off inventory (damaged, lost, etc)
- create_inventory_transfer(date, from_location, to_location, items) - Transfer inventory between locations

IMPORTANT: When asked about inventory:
1. ALWAYS call the appropriate tool first
2. Present the findings clearly
3. For create operations, confirm before executing

Never say "I don't have access" - you DO have access through these tools."""


INVESTMENT_AGENT_PROMPT = """You are an investment tracking specialist for {company_name}.

You MUST use the available tools to answer questions. DO NOT say you don't have access - USE THE TOOLS.

Available tools:
- get_investments() - Get investment accounts (stocks, bonds, funds, etc)
- get_investment_transactions(limit) - Get investment transactions (buys, sells, dividends)
- get_investment_market_prices() - Get current market prices for investments
- create_investment_account(name, code) - Create a new investment account
- handle_forex(amount, from_currency, to_currency, exchange_rate) - Convert amount between currencies

IMPORTANT: When asked about investments or forex:
1. ALWAYS call the appropriate tool first
2. Present the findings clearly

Never say "I don't have access" - you DO have access through these tools."""


DOCUMENT_AGENT_PROMPT = """You are a document processing specialist for {company_name}.

You MUST use the available tools to answer questions. DO NOT say you don't have access - USE THE TOOLS.

Available tools:
- classify_document(ocr_text) - Classify document type from OCR text
- extract_document_fields(ocr_text) - Extract key fields from document text
- search_supplier(vendor_name) - Search for supplier by name
- search_account(description) - Search for expense account by keywords
- match_vendor_to_supplier(vendor_name) - Match extracted vendor name to existing supplier

IMPORTANT: When processing documents:
1. Use classify_document to determine document type
2. Use extract_document_fields to get key data
3. Use search_supplier/search_account to match to existing records

OUTPUT FORMAT:
- For extracted/structured data, wrap in <canvas>...</canvas> tags
- Use markdown tables or formatted text inside canvas

Never say "I don't have access" - you DO have access through these tools."""


ENTRY_AGENT_PROMPT = """You are an entry creation specialist for {company_name}.

You MUST use the available tools to create entries. DO NOT just say you created something - you MUST actually call the tool.

=== CRITICAL: ONE TOOL AT A TIME ===
Call ONE tool, wait for the result, then call the next tool.
DO NOT try to call multiple tools in parallel - the system only processes one at a time.

Available tools:
- search_employee(name) - Get all employees/directors to find the payer for expense claims
- search_account(description) - Get the Chart of Accounts to find the appropriate account
- get_bank_accounts() - Get all bank/cash accounts to find where to pay from or receive into
- create_supplier(name, code) - Create a new supplier (use before create_purchase_invoice if supplier doesn't exist)
- create_customer(name, code) - Create a new customer (use before create_sales_invoice if customer doesn't exist)
- extract_fields_from_ocr(ocr_text) - Extract vendor, amount, date from OCR text
- create_expense_claim(payer_key, date, description, account_key, amount, payee) - Create expense claim
- create_purchase_invoice(supplier_key, date, description, account_key, amount, reference) - Create purchase invoice
- create_sales_invoice(customer_key, date, description, account_key, amount, reference) - Create sales invoice
- create_payment(bank_account_key, date, payee, amount, ...) - Create payment (see modes below)
- create_receipt(bank_account_key, date, payer, account_key, amount, description) - Create receipt (money in)
- create_journal_entry(date, description, debit_account, credit_account, amount) - Create journal entry
- create_transfer(from_account, to_account, date, amount, description) - Create inter-account transfer
- create_credit_note(customer_key, date, description, account_key, amount) - Create credit note
- create_debit_note(supplier_key, date, description, account_key, amount) - Create debit note
- amend_entry(entry_type, entry_key, updates) - Amend/update an existing entry
- delete_entry(entry_type, entry_key) - Delete an entry
- call_manager_api(method, endpoint, params, data) - Call any Manager.io API endpoint directly

=== WORKFLOW REFERENCE ===

EXPENSE CLAIM (employee/director paid out of pocket):
  DR: Expense account (meals, transport, supplies, etc.)
  CR: Amount due to employee/director
  Tool: create_expense_claim(payer, date, description, expense_account, amount)
  Note: NO supplier needed. Use search_employee to find payer UUID if needed.

PURCHASE INVOICE (bill from supplier, on credit):
  DR: Expense or Asset account
  CR: Accounts Payable (supplier)
  Tool: create_purchase_invoice(supplier, date, description, account, amount)
  Later: create_payment when paid

PAYMENT - TWO MODES:
  Mode 1 - PAYING A PURCHASE INVOICE (clearing Accounts Payable):
    DR: Accounts Payable (auto from invoice)
    CR: Bank account
    Tool: create_payment(bank_account_key, date, payee, amount, supplier_key=X, purchase_invoice_key=Y)
    NOTE: Do NOT pass account_key - the invoice already recorded the expense!
  
  Mode 2 - DIRECT PAYMENT (no invoice, e.g., cash purchase):
    DR: Expense account
    CR: Bank account
    Tool: create_payment(bank_account_key, date, payee, amount, account_key=expense_account)

SALES INVOICE (bill to customer):
  DR: Accounts Receivable (customer)
  CR: Income account
  Tool: create_sales_invoice(customer, date, description, account, amount)
  Later: create_receipt when customer pays

RECEIPT - TWO MODES:
  Mode 1 - RECEIVING FOR A SALES INVOICE (clearing Accounts Receivable):
    DR: Bank account
    CR: Accounts Receivable (auto from invoice)
    Tool: create_receipt(bank_account_key, date, payer, amount, customer_key=X, sales_invoice_key=Y)
    NOTE: Do NOT pass account_key - the invoice already recorded the income!
  
  Mode 2 - DIRECT RECEIPT (no invoice, e.g., cash sale):
    DR: Bank account
    CR: Income account
    Tool: create_receipt(bank_account_key, date, payer, amount, account_key=income_account)

JOURNAL ENTRY (manual adjustment):
  DR: Account to increase (assets/expenses) or decrease (liabilities/income)
  CR: Account to decrease (assets/expenses) or increase (liabilities/income)
  Tool: create_journal_entry(date, description, debit_account, credit_account, amount)

=== END WORKFLOW REFERENCE ===

=== CRITICAL: UUID LOOKUP WORKFLOW ===

ALWAYS use search tools FIRST to get UUIDs before creating entries.
Call ONE tool at a time and wait for the result.

1. For payer_key (expense claims): Call search_employee(name) FIRST to get the UUID
2. For account_key: Call search_account(description) FIRST to get the full Chart of Accounts, then choose the best match
3. For supplier_key: Use the supplier UUID from context or search
4. For customer_key: Use the customer UUID from context or search
5. For bank_account_key: Use the bank account UUID from context or call_manager_api to get bank accounts

ACCOUNT SELECTION:
- search_account returns the FULL Chart of Accounts grouped by type (expense, income, asset, liability, equity)
- YOU must choose the most appropriate account based on the transaction description
- For audit fees → look for "audit" or "professional fees" in expense accounts
- For transportation → look for "transport" or "taxi" or "uber" in expense accounts
- Use your judgment to match the expense type to the best account name

Example workflow for expense claim (ONE TOOL AT A TIME):
Step 1: Call search_employee("director") → Wait for result with all employees
Step 2: Call search_account("transportation") → Wait for result with full COA
Step 3: Choose the best account from the COA (e.g., "Local taxi or uber")
Step 4: Call create_expense_claim with the UUIDs from steps 1-3

DO NOT pass names directly to create_* tools. Always get UUIDs first using search tools.

=== END UUID LOOKUP WORKFLOW ===

WORKFLOW when OCR text is provided:
1. Use extract_fields_from_ocr to get amount, date, vendor from the document
2. Call search_employee to get payer UUID (wait for result)
3. Call search_account to get expense account UUID (wait for result)
4. Create the entry using the UUIDs

WORKFLOW for MULTIPLE DOCUMENTS:
When multiple documents are provided (e.g., "[Document 1 OCR Text]...", "[Document 2 OCR Text]..."):
1. Process EACH document separately, ONE AT A TIME
2. For each document:
   a. Extract fields (amount, date, vendor)
   b. Determine the appropriate entry type (expense claim, invoice, etc.)
   c. Search for required UUIDs (one search at a time)
   d. Create the entry
3. Summarize all created entries at the end

CRITICAL RULES:
1. ONE TOOL AT A TIME - call one tool, wait for result, then call next
2. ALWAYS call search_employee/search_account FIRST to get UUIDs before calling create_* tools
3. Parameters ending in "_key" MUST be UUIDs, not names
4. When user confirms or provides all required info, call search tools then create tool
5. NEVER say "I've recorded" or "I've created" without actually calling the tool
6. If you have: payer name, date, description, amount → search for UUIDs FIRST, then call create_expense_claim
7. For MULTIPLE documents, process EACH one and create separate entries

AFTER CREATING ENTRIES:
- Summarize what you created (entry type, amount, account used)
- Be ready for follow-up questions like "why did you use that account?"
- If user wants to change something, use amend_entry or delete_entry and create a new one

DO NOT skip the search steps - ALWAYS get UUIDs first."""


# =============================================================================
# LLM Configuration
# =============================================================================


def create_llm(with_tools: bool = False, tools: List[BaseTool] = None):
    """Create LLM instance."""
    logger.info(f"Creating LLM: provider={settings.default_llm_provider}, model={settings.default_llm_model}, with_tools={with_tools}, num_tools={len(tools) if tools else 0}")
    
    if settings.default_llm_provider == "lmstudio":
        llm = ChatOpenAI(
            base_url=settings.lmstudio_url,
            api_key="not-needed",
            model=settings.default_llm_model,
            temperature=0.1,
        )
    elif settings.default_llm_provider == "ollama":
        llm = ChatOpenAI(
            base_url=f"{settings.ollama_url}/v1",
            api_key="ollama",
            model=settings.default_llm_model,
            temperature=0.1,
        )
    else:
        llm = ChatOpenAI(
            model=settings.default_llm_model or "gpt-4",
            temperature=0.1,
        )
    
    if with_tools and tools:
        logger.info(f"Binding {len(tools)} tools to LLM: {[t.name for t in tools]}")
        bound_llm = llm.bind_tools(tools)
        return bound_llm
    return llm


def parse_tool_calls_from_text(content: str, available_tools: List[BaseTool]) -> List[dict]:
    """
    Parse tool calls from model text output for models that don't support native tool calling.
    Supports multiple formats:
    - [TOOL_REQUEST]{"name": "...", "arguments": {...}}[END_TOOL_REQUEST]
    - <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    - JSON objects with "name" and "arguments" keys
    """
    import re
    import uuid
    
    tool_calls = []
    tool_names = {t.name for t in available_tools}
    
    # Pattern 1: [TOOL_REQUEST]...[END_TOOL_REQUEST]
    pattern1 = r'\[TOOL_REQUEST\](.*?)\[END_TOOL_REQUEST\]'
    matches = re.findall(pattern1, content, re.DOTALL | re.IGNORECASE)
    
    # Pattern 2: <tool_call>...</tool_call>
    pattern2 = r'<tool_call>(.*?)</tool_call>'
    matches.extend(re.findall(pattern2, content, re.DOTALL | re.IGNORECASE))
    
    for match in matches:
        try:
            data = json.loads(match.strip())
            name = data.get("name")
            args = data.get("arguments", {})
            
            if name and name in tool_names:
                tool_calls.append({
                    "id": str(uuid.uuid4())[:8],
                    "name": name,
                    "args": args if isinstance(args, dict) else {},
                })
        except json.JSONDecodeError:
            continue
    
    # Pattern 3: Look for JSON-like tool calls in the text
    if not tool_calls:
        # Try to find any JSON object that looks like a tool call
        json_pattern = r'\{[^{}]*"name"\s*:\s*"([^"]+)"[^{}]*"arguments"\s*:\s*(\{[^{}]*\})[^{}]*\}'
        for match in re.finditer(json_pattern, content, re.DOTALL):
            name = match.group(1)
            try:
                args = json.loads(match.group(2))
                if name in tool_names:
                    tool_calls.append({
                        "id": str(uuid.uuid4())[:8],
                        "name": name,
                        "args": args,
                    })
            except json.JSONDecodeError:
                continue
    
    return tool_calls


# =============================================================================
# Graph Nodes
# =============================================================================


def create_supervisor_node(company_name: str):
    """Supervisor decides which agent handles the request - with self-reflection for direct responses."""
    
    async def supervisor(state: AgentState) -> AgentState:
        events = list(state.get("events", []))
        thinking_steps = list(state.get("thinking_steps", []))
        
        events.append(AgentEvent(
            type="routing",
            status="started",
            message="Analyzing request...",
        ))
        
        prompt = SUPERVISOR_PROMPT.format(company_name=company_name)
        messages = [SystemMessage(content=prompt)] + list(state.get("messages", []))
        
        llm = create_llm()
        response = await llm.ainvoke(messages)
        
        # Parse response to get agent
        content = response.content.upper().strip()
        logger.info(f"[supervisor] Raw response content (first 200 chars): {content[:200]}")
        
        # Strip thinking tags first
        content_stripped = strip_thinking_tags(content).upper().strip()
        logger.info(f"[supervisor] After stripping think tags: {content_stripped[:100]}")
        
        # Get the last word/line which should be the routing decision
        # The model should output just the routing word at the end
        last_line = content_stripped.split('\n')[-1].strip()
        last_word = content_stripped.split()[-1].strip() if content_stripped.split() else ""
        logger.info(f"[supervisor] Last line: '{last_line}', Last word: '{last_word}'")
        
        # Check the last word/line first for exact match
        routing_keywords = ["DIRECT", "DATA", "REPORT", "TRANSACTION", "INVENTORY", "INVESTMENT", "DOCUMENT", "ENTRY"]
        
        next_agent = "direct"  # default
        
        # Clean up any remaining tags from last_word and last_line
        # Sometimes the model outputs "REPORT.</THINK>REPORT" or similar
        import re
        last_word_clean = re.sub(r'</?(THINK|think)>', '', last_word).strip()
        last_line_clean = re.sub(r'</?(THINK|think)>', '', last_line).strip()
        logger.info(f"[supervisor] Cleaned - Last line: '{last_line_clean}', Last word: '{last_word_clean}'")
        
        # First try exact match on cleaned last word
        if last_word_clean in routing_keywords:
            next_agent = last_word_clean.lower()
            logger.info(f"[supervisor] Matched last word: '{last_word_clean}'")
        # Then try cleaned last line
        elif last_line_clean in routing_keywords:
            next_agent = last_line_clean.lower()
            logger.info(f"[supervisor] Matched last line: '{last_line_clean}'")
        # Try to find a keyword at the END of the content (most reliable)
        else:
            # Look for keyword at the very end of content
            for keyword in routing_keywords:
                if content_stripped.endswith(keyword):
                    next_agent = keyword.lower()
                    logger.info(f"[supervisor] Matched keyword at end: '{keyword}'")
                    break
            else:
                # Last resort: find the LAST occurrence of any keyword
                last_pos = -1
                last_keyword = None
                for keyword in routing_keywords:
                    pos = content_stripped.rfind(keyword)
                    if pos > last_pos:
                        last_pos = pos
                        last_keyword = keyword
                if last_keyword:
                    next_agent = last_keyword.lower()
                    logger.info(f"[supervisor] Matched last occurrence of keyword: '{last_keyword}' at pos {last_pos}")
        
        logger.info(f"[supervisor] Determined next_agent: '{next_agent}'")
        
        # CRITICAL: Override routing to ENTRY if documents are present
        # Check if the message contains OCR text from uploaded documents
        user_message = ""
        for msg in state.get("messages", []):
            if hasattr(msg, 'content') and isinstance(msg.content, str):
                user_message += msg.content
        
        # Check for both old and new document markers
        has_documents = (
            ("=== " in user_message and "DOCUMENT(S) UPLOADED ===" in user_message) or
            ("[Document" in user_message and "OCR Text]" in user_message)
        )
        if has_documents and next_agent in ["direct", "document"]:
            logger.info(f"[supervisor] Documents detected, overriding '{next_agent}' to 'entry'")
            next_agent = "entry"
        
        thinking_steps.append(ThinkingStep(
            type="routing",
            content=f"Routing to {next_agent}",
            agent="supervisor",
        ))
        events.append(AgentEvent(
            type="routing",
            status="completed",
            message=f"Routing to {next_agent}",
            data={"next_agent": next_agent},
        ))
        
        # For direct responses, we go straight to respond node
        # For other agents, we continue to the sub-agent
        return {
            **state,
            "current_agent": next_agent,
            "events": events,
            "thinking_steps": thinking_steps,
            "should_continue": next_agent not in ["respond", "direct"],
        }
    
    return supervisor


def create_direct_response_node(company_name: str):
    """Direct response node - supervisor answers without tools."""
    
    async def direct_respond(state: AgentState) -> AgentState:
        events = list(state.get("events", []))
        
        events.append(AgentEvent(
            type="thinking",
            status="started",
            message="Generating response...",
        ))
        
        prompt = DIRECT_RESPONSE_PROMPT.format(company_name=company_name)
        messages = [SystemMessage(content=prompt)] + list(state.get("messages", []))
        
        llm = create_llm()
        response = await llm.ainvoke(messages)
        
        response_text = strip_thinking_tags(response.content) if response.content else "How can I help you?"
        
        events.append(AgentEvent(
            type="thinking",
            status="completed",
            message="Response ready",
        ))
        
        events.append(AgentEvent(
            type="response",
            status="completed",
            message="Response ready",
            data={"content": response_text},
        ))
        
        return {
            **state,
            "events": events,
            "should_continue": False,
        }
    
    return direct_respond


def create_sub_agent_node(agent_name: str, tools: List[BaseTool], system_prompt: str):
    """Create a sub-agent node with specific tools."""
    
    tool_node = ToolNode(tools)
    
    # Create a tool description string for fallback prompting
    tool_names = [t.name for t in tools]
    tool_descriptions = "\n".join([
        f"- {t.name}: {t.description}" for t in tools
    ])
    
    logger.info(f"[{agent_name}] Creating agent with tools: {tool_names}")
    
    async def agent_node(state: AgentState) -> AgentState:
        events = list(state.get("events", []))
        thinking_steps = list(state.get("thinking_steps", []))
        
        events.append(AgentEvent(
            type="thinking",
            status="started",
            message=f"{agent_name} agent processing...",
            data={"agent": agent_name},
        ))
        
        # Enhanced prompt with explicit tool instructions
        enhanced_prompt = f"""{system_prompt}

CRITICAL: You have access to these tools and MUST use them:
{tool_descriptions}

To use a tool, output a tool call in this EXACT format:
<tool_call>
{{"name": "tool_name", "arguments": {{"param": "value"}}}}
</tool_call>

RULES:
1. DO NOT say you don't have access to data - USE THE TOOLS
2. DO NOT say "I've created" or "I've recorded" without actually calling a tool
3. When you have all required information, CALL THE TOOL IMMEDIATELY
4. The tool call MUST be in the exact format shown above"""
        
        messages = [SystemMessage(content=enhanced_prompt)] + list(state.get("messages", []))
        llm = create_llm(with_tools=True, tools=tools)
        
        # Log the tools being used
        logger.info(f"[{agent_name}] Agent invoked with {len(tools)} tools: {[t.name for t in tools]}")
        
        # Agent loop - keep calling tools until done
        max_iterations = 8  # Most tasks complete in 3-5 iterations
        tool_called = False
        recent_tool_calls = []  # Track recent calls to detect loops
        max_same_call_repeats = 2  # Stop if same call repeated this many times
        
        for iteration in range(max_iterations):
            logger.info(f"[{agent_name}] Iteration {iteration + 1}/{max_iterations}")
            response = await llm.ainvoke(messages)
            messages.append(response)
            
            # Check for native tool calls first
            tool_calls_to_process = []
            
            if response.tool_calls:
                logger.info(f"[{agent_name}] Native tool_calls: {response.tool_calls}")
                tool_calls_to_process = response.tool_calls
            else:
                # Try to parse tool calls from text content (for models without native support)
                if response.content:
                    parsed_calls = parse_tool_calls_from_text(response.content, tools)
                    if parsed_calls:
                        logger.info(f"[{agent_name}] Parsed tool calls from text: {parsed_calls}")
                        tool_calls_to_process = parsed_calls
                    else:
                        logger.warning(f"[{agent_name}] No tool calls found. Response: {response.content[:300]}...")
            
            if not tool_calls_to_process:
                # Check if model is claiming to have done something without calling a tool
                response_lower = response.content.lower() if response.content else ""
                fake_completion_phrases = [
                    "i've recorded", "i've created", "i have recorded", "i have created",
                    "the claim has been added", "has been recorded", "has been created",
                    "entry has been", "successfully created", "successfully recorded",
                    "expense claim for", "recorded the expense"
                ]
                
                if any(phrase in response_lower for phrase in fake_completion_phrases) and not tool_called:
                    # Model is lying - it didn't actually call a tool
                    logger.warning(f"[{agent_name}] Model claimed completion without tool call. Prompting to actually call tool.")
                    correction_msg = HumanMessage(content="""You said you created/recorded something, but you did NOT actually call any tool.

You MUST call the tool to actually create the entry. Output a tool call like this:
<tool_call>
{"name": "create_expense_claim", "arguments": {"payer_key": "...", "date": "...", "description": "...", "account_key": "...", "amount": ...}}
</tool_call>

DO NOT just say you did it - ACTUALLY CALL THE TOOL NOW.""")
                    messages.append(correction_msg)
                    continue  # Try again
                
                break
            
            # LOOP DETECTION: Check if we're repeating the same tool call
            for tc in tool_calls_to_process:
                if isinstance(tc, dict):
                    call_signature = f"{tc.get('name', '')}:{json.dumps(tc.get('args', {}), sort_keys=True)}"
                else:
                    call_signature = f"{tc.get('name', '')}:{json.dumps(tc.get('args', {}), sort_keys=True)}"
                
                repeat_count = recent_tool_calls.count(call_signature)
                if repeat_count >= max_same_call_repeats:
                    logger.warning(f"[{agent_name}] LOOP DETECTED: Same tool call repeated {repeat_count + 1} times: {call_signature[:100]}")
                    # Force stop - add a message explaining the issue
                    messages.append(AIMessage(content=f"I've tried this approach multiple times without success. Let me explain what I found so far and what might be the issue."))
                    tool_calls_to_process = []  # Clear to break the loop
                    break
                
                recent_tool_calls.append(call_signature)
                # Keep only last 10 calls for comparison
                if len(recent_tool_calls) > 10:
                    recent_tool_calls.pop(0)
            
            if not tool_calls_to_process:
                break
            
            tool_called = True
            
            # Record tool calls
            for tc in tool_calls_to_process:
                # Handle both native format and parsed format
                if isinstance(tc, dict):
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})
                    tool_id = tc.get("id", str(uuid.uuid4())[:8])
                else:
                    tool_name = tc["name"]
                    tool_args = tc.get("args", {})
                    tool_id = tc.get("id", str(uuid.uuid4())[:8])
                
                logger.info(f"[{agent_name}] Calling tool: {tool_name} with args: {tool_args}")
                thinking_steps.append(ThinkingStep(
                    type="tool_call",
                    content=f"Calling {tool_name}",
                    tool_name=tool_name,
                    tool_input=tool_args,
                    agent=agent_name,
                ))
                events.append(AgentEvent(
                    type="tool_call",
                    status="started",
                    message=f"{agent_name}: Using {tool_name}",
                    data={"agent": agent_name, "tool": tool_name, "args": tool_args},
                ))
            
            # Execute tools - need to handle both native and parsed formats
            if response.tool_calls:
                # Native format - use ToolNode directly
                tool_result = await tool_node.ainvoke({"messages": messages})
                tool_messages = tool_result.get("messages", [])
            else:
                # Parsed format - execute tools manually
                tool_messages = []
                for tc in tool_calls_to_process:
                    tool_name = tc.get("name", "")
                    tool_args = tc.get("args", {})
                    tool_id = tc.get("id", str(uuid.uuid4())[:8])
                    
                    # Find and execute the tool
                    tool_result_content = "Tool not found"
                    for tool in tools:
                        if tool.name == tool_name:
                            try:
                                # Execute the tool
                                if hasattr(tool, 'ainvoke'):
                                    tool_result_content = await tool.ainvoke(tool_args)
                                else:
                                    tool_result_content = tool.invoke(tool_args)
                                if not isinstance(tool_result_content, str):
                                    tool_result_content = json.dumps(tool_result_content)
                            except Exception as e:
                                tool_result_content = f"Error executing tool: {e}"
                            break
                    
                    tool_messages.append(ToolMessage(
                        content=tool_result_content,
                        tool_call_id=tool_id,
                        name=tool_name,
                    ))
            
            for msg in tool_messages:
                if isinstance(msg, ToolMessage):
                    preview = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
                    logger.info(f"[{agent_name}] Tool {msg.name} result preview: {preview[:100]}...")
                    thinking_steps.append(ThinkingStep(
                        type="tool_result",
                        content=preview,
                        tool_name=msg.name,
                        tool_output=msg.content,
                        agent=agent_name,
                    ))
                    events.append(AgentEvent(
                        type="tool_result",
                        status="completed",
                        message=f"{agent_name}: Got result from {msg.name}",
                        data={"agent": agent_name, "tool": msg.name, "result_preview": preview[:150]},
                    ))
            
            messages.extend(tool_messages)
        
        # Get final response
        final_response = messages[-1] if messages else AIMessage(content="No response")
        
        # REFLECTION: Check if we actually accomplished what the user wanted (only once, no recursion)
        reflection_done = state.get("reflection_done", False)
        if final_response.content and tool_called and not reflection_done:
            # Get the original user request
            user_request = ""
            for msg in state.get("messages", []):
                if isinstance(msg, HumanMessage):
                    user_request = msg.content
                    break
            
            if user_request:
                reflection_prompt = f"""Before finishing, briefly check: Did you accomplish what the user wanted?

USER REQUEST: {user_request[:300]}

YOUR RESPONSE SO FAR: {final_response.content[:300]}

If YES - respond normally.
If NO - call ONE more tool to complete the task, or explain what's missing."""
                
                reflection_messages = messages + [HumanMessage(content=reflection_prompt)]
                try:
                    reflection_response = await llm.ainvoke(reflection_messages)
                    
                    # Check if reflection triggered more tool calls (limit to 1 additional round)
                    if reflection_response.tool_calls:
                        logger.info(f"[{agent_name}] Reflection triggered additional tool call")
                        messages.append(reflection_response)
                        tool_result = await tool_node.ainvoke({"messages": messages})
                        tool_messages = tool_result.get("messages", [])
                        messages.extend(tool_messages)
                        
                        # Get new final response (no more reflection after this)
                        final_llm_response = await llm.ainvoke(messages)
                        final_response = final_llm_response
                except Exception as e:
                    logger.warning(f"[{agent_name}] Reflection failed: {e}")
        
        events.append(AgentEvent(
            type="thinking",
            status="completed",
            message=f"{agent_name} agent done",
            data={"agent": agent_name},
        ))
        
        # Update state with new messages
        new_messages = list(state.get("messages", []))
        new_messages.append(final_response)
        
        return {
            **state,
            "messages": new_messages,
            "events": events,
            "thinking_steps": thinking_steps,
            "current_agent": "supervisor",  # Return to supervisor
            "should_continue": False,  # Let supervisor decide next
        }
    
    return agent_node


def create_respond_node():
    """Final response node - extracts response from sub-agent messages."""
    
    async def respond(state: AgentState) -> AgentState:
        events = list(state.get("events", []))
        
        # Get response from the last AI message (from sub-agent)
        messages = state.get("messages", [])
        response = ""
        
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                response = strip_thinking_tags(msg.content)
                break
        
        if not response:
            response = "I've processed your request. Is there anything else you'd like to know?"
        
        events.append(AgentEvent(
            type="response",
            status="completed",
            message="Response ready",
            data={"content": response},  # Send full response, not truncated
        ))
        
        return {
            **state,
            "events": events,
            "should_continue": False,
        }
    
    return respond


# =============================================================================
# Graph Builder
# =============================================================================


def create_multi_agent_graph(
    company_name: str,
    accounts: List[Dict[str, Any]],
    suppliers: List[Dict[str, Any]],
    manager_client=None,
    ocr_service: Optional[OCRService] = None,
) -> StateGraph:
    """Create multi-agent graph with supervisor routing."""
    
    # Create the generic API tool (fallback for any endpoint)
    generic_api_tool = create_generic_api_tool(manager_client)
    
    # Create tools for each agent (with generic API tool as fallback)
    data_tools = create_data_tools(accounts, suppliers, manager_client) + [generic_api_tool]
    report_tools = create_report_tools(manager_client) + [generic_api_tool]
    transaction_tools = create_transaction_tools(manager_client) + [generic_api_tool]
    inventory_tools = create_inventory_tools(manager_client) + [generic_api_tool]
    investment_tools = create_investment_tools(manager_client) + [generic_api_tool]
    document_tools = create_document_tools(accounts, suppliers, ocr_service)  # No API needed
    entry_tools = create_entry_tools(manager_client) + [generic_api_tool]
    
    # Log tool assignments
    logger.info(f"[graph] data_tools: {[t.name for t in data_tools]}")
    logger.info(f"[graph] report_tools: {[t.name for t in report_tools]}")
    logger.info(f"[graph] transaction_tools: {[t.name for t in transaction_tools]}")
    
    # Create prompts
    data_prompt = DATA_AGENT_PROMPT.format(company_name=company_name)
    report_prompt = REPORT_AGENT_PROMPT.format(company_name=company_name)
    transaction_prompt = TRANSACTION_AGENT_PROMPT.format(company_name=company_name)
    inventory_prompt = INVENTORY_AGENT_PROMPT.format(company_name=company_name)
    investment_prompt = INVESTMENT_AGENT_PROMPT.format(company_name=company_name)
    document_prompt = DOCUMENT_AGENT_PROMPT.format(company_name=company_name)
    entry_prompt = ENTRY_AGENT_PROMPT.format(company_name=company_name)
    
    # Build graph
    graph = StateGraph(AgentState)
    
    # Add nodes
    graph.add_node("supervisor", create_supervisor_node(company_name))
    graph.add_node("direct", create_direct_response_node(company_name))  # Direct response without tools
    graph.add_node("data", create_sub_agent_node("data", data_tools, data_prompt))
    graph.add_node("report", create_sub_agent_node("report", report_tools, report_prompt))
    graph.add_node("transaction", create_sub_agent_node("transaction", transaction_tools, transaction_prompt))
    graph.add_node("inventory", create_sub_agent_node("inventory", inventory_tools, inventory_prompt))
    graph.add_node("investment", create_sub_agent_node("investment", investment_tools, investment_prompt))
    graph.add_node("document", create_sub_agent_node("document", document_tools, document_prompt))
    graph.add_node("entry", create_sub_agent_node("entry", entry_tools, entry_prompt))
    graph.add_node("respond", create_respond_node())
    
    # Routing function
    def route_from_supervisor(state: AgentState) -> str:
        agent = state.get("current_agent", "direct")
        logger.info(f"[route_from_supervisor] current_agent from state: '{agent}'")
        valid_agents = ["data", "report", "transaction", "inventory", "investment", "document", "entry", "direct"]
        if agent in valid_agents:
            logger.info(f"[route_from_supervisor] Routing to: '{agent}'")
            return agent
        logger.warning(f"[route_from_supervisor] Invalid agent '{agent}', defaulting to 'direct'")
        return "direct"
    
    # Add edges
    graph.set_entry_point("supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        {
            "direct": "direct",  # Direct response path (no tools)
            "data": "data", 
            "report": "report",
            "transaction": "transaction",
            "inventory": "inventory",
            "investment": "investment",
            "document": "document", 
            "entry": "entry", 
            "respond": "respond"
        }
    )
    
    # Direct goes straight to END (no respond node needed)
    graph.add_edge("direct", END)
    
    # All sub-agents go to respond after completion
    graph.add_edge("data", "respond")
    graph.add_edge("report", "respond")
    graph.add_edge("transaction", "respond")
    graph.add_edge("inventory", "respond")
    graph.add_edge("investment", "respond")
    graph.add_edge("document", "respond")
    graph.add_edge("entry", "respond")
    graph.add_edge("respond", END)
    
    return graph


# =============================================================================
# Main Agent Class
# =============================================================================


class BookkeeperAgent:
    """Multi-agent bookkeeping assistant."""
    
    def __init__(
        self,
        ocr_service: Optional[OCRService] = None,
        manager_client=None,
        checkpointer: Optional[MemorySaver] = None,
    ):
        self.ocr_service = ocr_service or OCRService()
        self.manager_client = manager_client
        self.checkpointer = checkpointer or MemorySaver()
        self._compiled = None
    
    def _ensure_compiled(
        self,
        company_name: str,
        accounts: List[Dict[str, Any]],
        suppliers: List[Dict[str, Any]],
    ):
        """Build and compile the multi-agent graph."""
        graph = create_multi_agent_graph(
            company_name=company_name,
            accounts=accounts,
            suppliers=suppliers,
            manager_client=self.manager_client,
            ocr_service=self.ocr_service,
        )
        self._compiled = graph.compile(
            checkpointer=self.checkpointer,
        )
        # Set recursion limit for the graph (max supervisor -> agent cycles)
        self._compiled.recursion_limit = 50
    
    def _classify_document(
        self,
        doc: ProcessedDocument,
        text: str,
        suppliers: List[Dict[str, Any]],
    ) -> ProcessedDocument:
        """Quick document classification."""
        text_lower = text.lower()
        
        if any(kw in text_lower for kw in ["invoice", "bill", "due date"]):
            doc.document_type = DocumentType.INVOICE
        elif any(kw in text_lower for kw in ["receipt", "thank you", "paid"]):
            doc.document_type = DocumentType.RECEIPT
        elif any(kw in text_lower for kw in ["expense", "reimbursement"]):
            doc.document_type = DocumentType.EXPENSE
        
        # Quick supplier match
        if suppliers:
            from difflib import SequenceMatcher
            for s in suppliers:
                sname = s.get("name", "").lower()
                if sname and sname in text_lower:
                    doc.matched_supplier = {"key": s.get("key"), "name": s.get("name"), "confidence": 0.9}
                    break
        
        return doc
    
    async def process_message(
        self,
        user_id: str,
        company_id: str,
        company_name: str,
        message: str,
        conversation_id: Optional[str] = None,
        images: Optional[List[bytes]] = None,
        accounts: Optional[List[Dict[str, Any]]] = None,
        suppliers: Optional[List[Dict[str, Any]]] = None,
        confirm_submission: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> tuple[str, List[AgentEvent], List[ProcessedDocument]]:
        """Process message through multi-agent system."""
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        
        accounts = accounts or []
        suppliers = suppliers or []
        
        self._ensure_compiled(company_name, accounts, suppliers)
        
        # Process images with OCR
        full_message = message
        processed_docs: List[ProcessedDocument] = []
        
        if images:
            document_summaries = []
            for i, img in enumerate(images):
                doc = ProcessedDocument(filename=f"document_{i+1}", status="processing")
                try:
                    is_pdf = img[:4] == b'%PDF'
                    result = await (self.ocr_service.extract_from_pdf(img) if is_pdf 
                                   else self.ocr_service.extract_text(img))
                    
                    if result.success:
                        doc.extracted_data = {"ocr_text": result.text}
                        doc.status = "ready"
                        doc = self._classify_document(doc, result.text, suppliers)
                        
                        # Create summary for each document
                        ocr_text = result.text[:2000]
                        doc_type = doc.document_type.value if doc.document_type else "unknown"
                        
                        document_summaries.append({
                            "doc_num": i + 1,
                            "type": doc_type,
                            "ocr_text": ocr_text,
                            "matched_supplier": doc.matched_supplier.get("name") if doc.matched_supplier else None,
                        })
                except Exception as e:
                    doc.status = "error"
                    doc.error = str(e)
                
                processed_docs.append(doc)
            
            # Build structured message for the agent
            if document_summaries:
                full_message += f"\n\n=== {len(document_summaries)} DOCUMENT(S) UPLOADED ===\n"
                full_message += "Process each document and create the appropriate entry.\n\n"
                
                for doc_info in document_summaries:
                    full_message += f"--- Document {doc_info['doc_num']} ({doc_info['type']}) ---\n"
                    if doc_info['matched_supplier']:
                        full_message += f"Matched Supplier: {doc_info['matched_supplier']}\n"
                    full_message += f"OCR Text:\n{doc_info['ocr_text']}\n\n"
                
                full_message += "=== END OF DOCUMENTS ===\n"
                full_message += "\nPlease process each document above and create the appropriate entries."
        
        # Build messages from history
        messages: List[BaseMessage] = []
        if history:
            for msg in history[-10:]:  # Last 10 messages for context
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        # Add current message
        messages.append(HumanMessage(content=full_message))
        
        # Build initial state
        initial_state: AgentState = {
            "messages": messages,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "company_id": company_id,
            "company_name": company_name,
            "accounts": accounts,
            "suppliers": suppliers,
            "processed_documents": processed_docs,
            "thinking_steps": [],
            "events": [],
            "current_agent": "supervisor",
            "should_continue": True,
            "confirm_submission": confirm_submission,
        }
        
        config = {"configurable": {"thread_id": conversation_id}}
        
        try:
            final_state = await self._compiled.ainvoke(initial_state, config)
            
            # Extract response
            messages = final_state.get("messages", [])
            response = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content and not getattr(msg, 'tool_calls', None):
                    response = strip_thinking_tags(msg.content)
                    break
            
            events = final_state.get("events", [])
            return response or "Request processed.", events, processed_docs
            
        except Exception as e:
            logger.error(f"Agent error: {e}")
            return f"Error: {e}", [AgentEvent(type="error", status="error", message=str(e))], processed_docs

    async def stream_process(
        self,
        user_id: str,
        company_id: str,
        company_name: str,
        message: str,
        conversation_id: Optional[str] = None,
        images: Optional[List[bytes]] = None,
        accounts: Optional[List[Dict[str, Any]]] = None,
        suppliers: Optional[List[Dict[str, Any]]] = None,
        confirm_submission: bool = False,
        history: Optional[List[Dict[str, str]]] = None,
    ):
        """Process with streaming events."""
        logger.info(f"[stream_process] Starting with {len(images) if images else 0} images")
        
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
        
        accounts = accounts or []
        suppliers = suppliers or []
        
        self._ensure_compiled(company_name, accounts, suppliers)
        
        full_message = message
        processed_docs: List[ProcessedDocument] = []
        
        # OCR with streaming events - process each document through Chandra
        if images:
            logger.info(f"[stream_process] Processing {len(images)} images through OCR")
            yield AgentEvent(type="ocr", status="started", message=f"Processing {len(images)} document(s)...")
            
            document_summaries = []
            for i, img in enumerate(images):
                logger.info(f"[stream_process] Processing image {i+1}/{len(images)}, size={len(img)} bytes")
                doc = ProcessedDocument(filename=f"document_{i+1}", status="processing")
                try:
                    is_pdf = img[:4] == b'%PDF'
                    logger.info(f"[stream_process] Image {i+1} is_pdf={is_pdf}")
                    result = await (self.ocr_service.extract_from_pdf(img) if is_pdf 
                                   else self.ocr_service.extract_text(img))
                    
                    logger.info(f"[stream_process] OCR result for image {i+1}: success={result.success}, text_len={len(result.text) if result.text else 0}")
                    
                    if result.success:
                        doc.extracted_data = {"ocr_text": result.text}
                        doc.status = "ready"
                        doc = self._classify_document(doc, result.text, suppliers)
                        
                        # Create a concise summary for each document
                        # Extract key fields for the summary
                        ocr_text = result.text[:2000]  # Limit text length
                        doc_type = doc.document_type.value if doc.document_type else "unknown"
                        
                        document_summaries.append({
                            "doc_num": i + 1,
                            "type": doc_type,
                            "ocr_text": ocr_text,
                            "matched_supplier": doc.matched_supplier.get("name") if doc.matched_supplier else None,
                        })
                        
                        yield AgentEvent(
                            type="ocr", status="completed",
                            message=f"Extracted text from document {i+1} ({doc_type})",
                            data={"chars": len(result.text), "type": doc_type}
                        )
                    else:
                        logger.warning(f"[stream_process] OCR failed for image {i+1}: {result.error}")
                        doc.status = "error"
                        doc.error = result.error
                        yield AgentEvent(type="ocr", status="error", message=f"OCR failed for document {i+1}: {result.error}")
                except Exception as e:
                    logger.error(f"[stream_process] Exception during OCR for image {i+1}: {e}")
                    doc.status = "error"
                    doc.error = str(e)
                    yield AgentEvent(type="ocr", status="error", message=f"OCR failed for document {i+1}: {e}")
                
                processed_docs.append(doc)
            
            logger.info(f"[stream_process] OCR complete, {len(document_summaries)} documents processed successfully")
            
            # Build a structured message for the agent
            if document_summaries:
                full_message += f"\n\n=== {len(document_summaries)} DOCUMENT(S) UPLOADED ===\n"
                full_message += "Process each document and create the appropriate entry.\n\n"
                
                for doc_info in document_summaries:
                    full_message += f"--- Document {doc_info['doc_num']} ({doc_info['type']}) ---\n"
                    if doc_info['matched_supplier']:
                        full_message += f"Matched Supplier: {doc_info['matched_supplier']}\n"
                    full_message += f"OCR Text:\n{doc_info['ocr_text']}\n\n"
                
                full_message += "=== END OF DOCUMENTS ===\n"
                full_message += "\nPlease process each document above and create the appropriate entries (expense claims, invoices, etc.)."
        
        logger.info(f"[stream_process] Building messages, full_message length={len(full_message)}")
        
        # Build messages from history (last 10 messages for context)
        messages: List[BaseMessage] = []
        if history:
            for msg in history[-10:]:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
        
        # Add current message
        messages.append(HumanMessage(content=full_message))
        
        initial_state: AgentState = {
            "messages": messages,
            "conversation_id": conversation_id,
            "user_id": user_id,
            "company_id": company_id,
            "company_name": company_name,
            "accounts": accounts,
            "suppliers": suppliers,
            "processed_documents": processed_docs,
            "thinking_steps": [],
            "events": [],
            "current_agent": "supervisor",
            "should_continue": True,
            "confirm_submission": confirm_submission,
        }
        
        config = {"configurable": {"thread_id": conversation_id}}
        seen_events = set()
        
        logger.info(f"[stream_process] Starting agent graph execution")
        
        try:
            async for state_update in self._compiled.astream(initial_state, config):
                logger.debug(f"[stream_process] State update from nodes: {list(state_update.keys())}")
                for node_name, node_state in state_update.items():
                    if isinstance(node_state, dict):
                        events_in_state = node_state.get("events", [])
                        logger.debug(f"[stream_process] Node {node_name} has {len(events_in_state)} events")
                        for event in events_in_state:
                            key = f"{event.type}:{event.status}:{event.message}"
                            if key not in seen_events:
                                seen_events.add(key)
                                logger.info(f"[stream_process] Yielding event: {event.type}/{event.status}")
                                yield event
            
            logger.info(f"[stream_process] Agent graph execution complete")
            yield AgentEvent(type="done", status="completed", message="Processing complete")
            
        except Exception as e:
            logger.error(f"[stream_process] Streaming error: {e}", exc_info=True)
            yield AgentEvent(type="error", status="error", message=str(e))
