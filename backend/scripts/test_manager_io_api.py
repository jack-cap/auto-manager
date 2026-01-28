#!/usr/bin/env python3
"""Test script to verify Manager.io API connectivity and ManagerIOClient methods.

This tests the ManagerIOClient wrapper class to ensure all methods work correctly.

Usage:
    python scripts/test_manager_io_api.py
    python scripts/test_manager_io_api.py -v  # verbose mode with sample data
    python scripts/test_manager_io_api.py --url <URL> --key <KEY>  # custom credentials
"""

import argparse
import asyncio
import os
import sys
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch settings before importing app modules
os.environ.setdefault("ENCRYPTION_KEY", "test-key-for-testing-only-32chars!")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test.db")

from pathlib import Path
from dotenv import load_dotenv

# Load test credentials from .env.test
SCRIPT_DIR = Path(__file__).parent
load_dotenv(SCRIPT_DIR / ".env.test")

# Default test credentials from environment
DEFAULT_BASE_URL = os.getenv("MANAGER_READ_BASE_URL", "https://localhost:8080/api2")
DEFAULT_API_KEY = os.getenv("MANAGER_READ_API_KEY", "")

# WRITE: Blank company for testing writes
WRITE_API_KEY = os.getenv("MANAGER_WRITE_API_KEY", "")

from app.services.manager_io import (
    ManagerIOClient,
    ManagerIOError,
    ManagerIOAuthenticationError,
    ManagerIOConnectionError,
)


async def test_connection(client: ManagerIOClient) -> bool:
    """Test basic API connectivity."""
    print("\n" + "=" * 60)
    print("Testing API Connection...")
    print("=" * 60)
    
    try:
        accounts = await client.get_chart_of_accounts()
        print(f"✅ Connection successful!")
        print(f"   Retrieved {len(accounts)} accounts from chart of accounts")
        return True
    except ManagerIOAuthenticationError as e:
        print(f"❌ Authentication failed: {e}")
        print("   Check your API key is correct")
        return False
    except ManagerIOConnectionError as e:
        print(f"❌ Connection failed: {e}")
        print("   Check the URL is correct and Manager.io is running")
        return False
    except ManagerIOError as e:
        print(f"❌ API error: {e}")
        return False


async def test_reference_data(client: ManagerIOClient) -> None:
    """Test fetching reference data."""
    print("\n" + "=" * 60)
    print("Testing Reference Data Endpoints...")
    print("=" * 60)
    
    tests = [
        ("Chart of Accounts", client.get_chart_of_accounts),
        ("Suppliers", client.get_suppliers),
        ("Customers", client.get_customers),
        ("Bank Accounts", client.get_bank_accounts),
        ("Employees", client.get_employees),
        ("Tax Codes", client.get_tax_codes),
        ("Inventory Items", client.get_inventory_items),
        ("Fixed Assets", client.get_fixed_assets),
        ("Projects", client.get_projects),
        ("Investments", client.get_investments),
    ]
    
    for name, func in tests:
        try:
            result = await func()
            count = len(result) if isinstance(result, list) else "N/A"
            print(f"✅ {name}: {count} records")
        except ManagerIOError as e:
            print(f"❌ {name}: {e}")
        except Exception as e:
            print(f"⚠️  {name}: Unexpected error - {e}")


async def test_transaction_data(client: ManagerIOClient) -> None:
    """Test fetching transaction data."""
    print("\n" + "=" * 60)
    print("Testing Transaction Endpoints...")
    print("=" * 60)
    
    tests = [
        ("Payments", lambda: client.get_payments(skip=0, take=5)),
        ("Receipts", lambda: client.get_receipts(skip=0, take=5)),
        ("Expense Claims", lambda: client.get_expense_claims(skip=0, take=5)),
        ("Transfers", lambda: client.get_transfers(skip=0, take=5)),
        ("Journal Entries", lambda: client.get_journal_entries(skip=0, take=5)),
        ("Sales Invoices", lambda: client.get_sales_invoices(skip=0, take=5)),
        ("Purchase Invoices", lambda: client.get_purchase_invoices(skip=0, take=5)),
        ("Credit Notes", lambda: client.get_credit_notes(skip=0, take=5)),
        ("Debit Notes", lambda: client.get_debit_notes(skip=0, take=5)),
    ]
    
    for name, func in tests:
        try:
            result = await func()
            count = len(result.items) if hasattr(result, 'items') else "N/A"
            total = result.total if hasattr(result, 'total') else "?"
            print(f"✅ {name}: {count} records (total: {total})")
        except ManagerIOError as e:
            print(f"❌ {name}: {e}")
        except Exception as e:
            print(f"⚠️  {name}: Unexpected error - {e}")


async def test_reports(client: ManagerIOClient) -> None:
    """Test fetching reports."""
    print("\n" + "=" * 60)
    print("Testing Report Endpoints...")
    print("=" * 60)
    
    tests = [
        ("Balance Sheet", lambda: client.get_balance_sheet()),
        ("Profit & Loss", lambda: client.get_profit_and_loss()),
        ("Trial Balance", lambda: client.get_trial_balance()),
        ("Cash Flow Statement", lambda: client.get_cash_flow_statement()),
        ("General Ledger Summary", lambda: client.get_general_ledger_summary()),
        ("Aged Receivables", lambda: client.get_aged_receivables()),
        ("Aged Payables", lambda: client.get_aged_payables()),
    ]
    
    for name, func in tests:
        try:
            result = await func()
            status = "Retrieved" if result else "Empty"
            # Show some info about the result
            if isinstance(result, dict):
                keys = list(result.keys())[:5]
                print(f"✅ {name}: {status} (keys: {keys})")
            else:
                print(f"✅ {name}: {status}")
        except ManagerIOError as e:
            print(f"❌ {name}: {e}")
        except Exception as e:
            print(f"⚠️  {name}: Unexpected error - {e}")


async def test_generic_api(client: ManagerIOClient) -> None:
    """Test the generic API call method."""
    print("\n" + "=" * 60)
    print("Testing Generic API Call...")
    print("=" * 60)
    
    try:
        # Test a simple GET
        result = await client.call_api("GET", "/divisions", params={"pageSize": 5})
        if result and "error" not in result:
            print(f"✅ Generic GET /divisions: {list(result.keys())}")
        elif "error" in result:
            print(f"⚠️  Generic GET /divisions: {result.get('error')}")
        else:
            print("⚠️  Generic GET /divisions: Empty response")
    except Exception as e:
        print(f"❌ Generic API call failed: {e}")


async def show_sample_data(client: ManagerIOClient) -> None:
    """Show sample data from key endpoints."""
    print("\n" + "=" * 60)
    print("Sample Data Preview...")
    print("=" * 60)
    
    # Show first 3 accounts
    try:
        accounts = await client.get_chart_of_accounts()
        print("\nChart of Accounts (first 3):")
        for acc in accounts[:3]:
            print(f"  - {acc.code}: {acc.name} (Key: {acc.key[:8]}...)")
    except Exception as e:
        print(f"  Could not fetch accounts: {e}")
    
    # Show first 3 suppliers
    try:
        suppliers = await client.get_suppliers()
        print("\nSuppliers (first 3):")
        for sup in suppliers[:3]:
            print(f"  - {sup.name} (Key: {sup.key[:8]}...)")
    except Exception as e:
        print(f"  Could not fetch suppliers: {e}")
    
    # Show first 3 customers
    try:
        customers = await client.get_customers()
        print("\nCustomers (first 3):")
        for cust in customers[:3]:
            print(f"  - {cust.name} (Key: {cust.key[:8]}...)")
    except Exception as e:
        print(f"  Could not fetch customers: {e}")
    
    # Show bank balances
    try:
        banks = await client.get_bank_accounts()
        print("\nBank Accounts:")
        for bank in banks:
            balance = bank.get("actualBalance", {})
            if isinstance(balance, dict):
                bal_str = f"{balance.get('currency', '')} {balance.get('value', 0):,.2f}"
            else:
                bal_str = str(balance)
            print(f"  - {bank.get('name')}: {bal_str}")
    except Exception as e:
        print(f"  Could not fetch bank accounts: {e}")


async def main(base_url: str, api_key: str, verbose: bool = False) -> None:
    """Run all tests."""
    print("=" * 60)
    print("Manager.io ManagerIOClient Test Script")
    print("=" * 60)
    print(f"Base URL: {base_url}")
    print(f"API Key: {api_key[:20]}...{api_key[-8:]}" if len(api_key) > 28 else "API Key: [hidden]")
    
    client = ManagerIOClient(base_url=base_url, api_key=api_key)
    
    try:
        # Test connection first
        if not await test_connection(client):
            print("\n❌ Connection test failed. Please check your credentials.")
            return
        
        # Run other tests
        await test_reference_data(client)
        await test_transaction_data(client)
        await test_reports(client)
        await test_generic_api(client)
        
        if verbose:
            await show_sample_data(client)
    finally:
        await client.close()
    
    print("\n" + "=" * 60)
    print("Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Manager.io API connectivity")
    parser.add_argument("--url", help="Manager.io API base URL (default: test server)")
    parser.add_argument("--key", help="Manager.io API key (default: test key)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Show sample data")
    args = parser.parse_args()
    
    # Get credentials from args, environment, or defaults
    base_url = args.url or os.environ.get("MANAGER_IO_BASE_URL") or DEFAULT_BASE_URL
    api_key = args.key or os.environ.get("MANAGER_IO_API_KEY") or DEFAULT_API_KEY
    
    asyncio.run(main(base_url, api_key, args.verbose))
