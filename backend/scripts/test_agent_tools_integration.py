#!/usr/bin/env python3
"""
Test all agent tools against the actual Manager.io API.

This script verifies that:
1. All agent tools make correct API calls
2. Response data is parsed correctly
3. The endpoint-to-key mapping is accurate

Usage:
    python scripts/test_agent_tools_integration.py
"""

import asyncio
import json
import os
import sys
from typing import Dict, List, Any
from dataclasses import dataclass

# Add parent directory to path
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

from app.services.manager_io import ManagerIOClient

# Test credentials from environment
BASE_URL = os.getenv("MANAGER_READ_BASE_URL", "https://localhost:8080/api2")
READ_API_KEY = os.getenv("MANAGER_READ_API_KEY", "")


@dataclass
class ToolTestResult:
    tool_name: str
    success: bool
    record_count: int
    error: str = None
    sample_keys: List[str] = None


async def test_data_tools(client: ManagerIOClient) -> List[ToolTestResult]:
    """Test DATA agent tools."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing DATA Agent Tools")
    print("=" * 60)
    
    # Test get_chart_of_accounts
    print("  get_chart_of_accounts:", end=" ")
    try:
        accounts = await client.get_chart_of_accounts()
        print(f"✅ {len(accounts)} accounts")
        results.append(ToolTestResult("get_chart_of_accounts", True, len(accounts), 
                                       sample_keys=["key", "name", "code"] if accounts else []))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_chart_of_accounts", False, 0, str(e)))
    
    # Test get_suppliers
    print("  get_suppliers:", end=" ")
    try:
        suppliers = await client.get_suppliers()
        print(f"✅ {len(suppliers)} suppliers")
        results.append(ToolTestResult("get_suppliers", True, len(suppliers)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_suppliers", False, 0, str(e)))
    
    # Test get_customers
    print("  get_customers:", end=" ")
    try:
        customers = await client.get_customers()
        print(f"✅ {len(customers)} customers")
        results.append(ToolTestResult("get_customers", True, len(customers)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_customers", False, 0, str(e)))
    
    # Test get_bank_accounts
    print("  get_bank_accounts:", end=" ")
    try:
        banks = await client.get_bank_accounts()
        print(f"✅ {len(banks)} bank accounts")
        results.append(ToolTestResult("get_bank_accounts", True, len(banks)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_bank_accounts", False, 0, str(e)))
    
    # Test get_employees
    print("  get_employees:", end=" ")
    try:
        employees = await client.get_employees()
        print(f"✅ {len(employees)} employees")
        results.append(ToolTestResult("get_employees", True, len(employees)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_employees", False, 0, str(e)))
    
    # Test get_tax_codes
    print("  get_tax_codes:", end=" ")
    try:
        codes = await client.get_tax_codes()
        print(f"✅ {len(codes)} tax codes")
        results.append(ToolTestResult("get_tax_codes", True, len(codes)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_tax_codes", False, 0, str(e)))
    
    # Test get_projects
    print("  get_projects:", end=" ")
    try:
        projects = await client.get_projects()
        print(f"✅ {len(projects)} projects")
        results.append(ToolTestResult("get_projects", True, len(projects)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_projects", False, 0, str(e)))
    
    # Test get_fixed_assets
    print("  get_fixed_assets:", end=" ")
    try:
        assets = await client.get_fixed_assets()
        print(f"✅ {len(assets)} fixed assets")
        results.append(ToolTestResult("get_fixed_assets", True, len(assets)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_fixed_assets", False, 0, str(e)))
    
    return results


async def test_report_tools(client: ManagerIOClient) -> List[ToolTestResult]:
    """Test REPORT agent tools."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing REPORT Agent Tools")
    print("=" * 60)
    
    # Test get_balance_sheet
    print("  get_balance_sheet:", end=" ")
    try:
        report = await client.get_balance_sheet()
        has_data = report and "error" not in report
        print(f"✅ {list(report.keys())[:3] if report else 'empty'}" if has_data else f"⚠️ {report.get('error', 'empty')[:50]}")
        results.append(ToolTestResult("get_balance_sheet", has_data, 1 if has_data else 0))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_balance_sheet", False, 0, str(e)))
    
    # Test get_profit_and_loss
    print("  get_profit_and_loss:", end=" ")
    try:
        report = await client.get_profit_and_loss()
        has_data = report and "error" not in report
        print(f"✅ {list(report.keys())[:3] if report else 'empty'}" if has_data else f"⚠️ {report.get('error', 'empty')[:50]}")
        results.append(ToolTestResult("get_profit_and_loss", has_data, 1 if has_data else 0))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_profit_and_loss", False, 0, str(e)))
    
    # Test get_trial_balance
    print("  get_trial_balance:", end=" ")
    try:
        report = await client.get_trial_balance()
        has_data = report and "error" not in report
        print(f"✅ {list(report.keys())[:3] if report else 'empty'}" if has_data else f"⚠️ {report.get('error', 'empty')[:50]}")
        results.append(ToolTestResult("get_trial_balance", has_data, 1 if has_data else 0))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_trial_balance", False, 0, str(e)))
    
    # Test get_general_ledger_summary
    print("  get_general_ledger_summary:", end=" ")
    try:
        report = await client.get_general_ledger_summary()
        has_data = report and "error" not in report
        print(f"✅ {list(report.keys())[:3] if report else 'empty'}" if has_data else f"⚠️ {report.get('error', 'empty')[:50]}")
        results.append(ToolTestResult("get_general_ledger_summary", has_data, 1 if has_data else 0))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_general_ledger_summary", False, 0, str(e)))
    
    # Test get_cash_flow_statement
    print("  get_cash_flow_statement:", end=" ")
    try:
        report = await client.get_cash_flow_statement()
        has_data = report and "error" not in report
        print(f"✅ {list(report.keys())[:3] if report else 'empty'}" if has_data else f"⚠️ {report.get('error', 'empty')[:50]}")
        results.append(ToolTestResult("get_cash_flow_statement", has_data, 1 if has_data else 0))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_cash_flow_statement", False, 0, str(e)))
    
    # Test get_aged_receivables
    print("  get_aged_receivables:", end=" ")
    try:
        report = await client.get_aged_receivables()
        has_data = report and "error" not in report
        print(f"✅ {list(report.keys())[:3] if report else 'empty'}" if has_data else f"⚠️ {report.get('error', 'empty')[:50]}")
        results.append(ToolTestResult("get_aged_receivables", has_data, 1 if has_data else 0))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_aged_receivables", False, 0, str(e)))
    
    # Test get_aged_payables
    print("  get_aged_payables:", end=" ")
    try:
        report = await client.get_aged_payables()
        has_data = report and "error" not in report
        print(f"✅ {list(report.keys())[:3] if report else 'empty'}" if has_data else f"⚠️ {report.get('error', 'empty')[:50]}")
        results.append(ToolTestResult("get_aged_payables", has_data, 1 if has_data else 0))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_aged_payables", False, 0, str(e)))
    
    return results


async def test_transaction_tools(client: ManagerIOClient) -> List[ToolTestResult]:
    """Test TRANSACTION agent tools."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing TRANSACTION Agent Tools")
    print("=" * 60)
    
    # Test get_payments
    print("  get_payments:", end=" ")
    try:
        resp = await client.get_payments(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_payments", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_payments", False, 0, str(e)))
    
    # Test get_receipts
    print("  get_receipts:", end=" ")
    try:
        resp = await client.get_receipts(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_receipts", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_receipts", False, 0, str(e)))
    
    # Test get_expense_claims
    print("  get_expense_claims:", end=" ")
    try:
        resp = await client.get_expense_claims(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_expense_claims", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_expense_claims", False, 0, str(e)))
    
    # Test get_purchase_invoices
    print("  get_purchase_invoices:", end=" ")
    try:
        resp = await client.get_purchase_invoices(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_purchase_invoices", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_purchase_invoices", False, 0, str(e)))
    
    # Test get_sales_invoices
    print("  get_sales_invoices:", end=" ")
    try:
        resp = await client.get_sales_invoices(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_sales_invoices", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_sales_invoices", False, 0, str(e)))
    
    # Test get_journal_entries
    print("  get_journal_entries:", end=" ")
    try:
        resp = await client.get_journal_entries(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_journal_entries", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_journal_entries", False, 0, str(e)))
    
    # Test get_transfers
    print("  get_transfers:", end=" ")
    try:
        resp = await client.get_transfers(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_transfers", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_transfers", False, 0, str(e)))
    
    # Test get_credit_notes
    print("  get_credit_notes:", end=" ")
    try:
        resp = await client.get_credit_notes(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_credit_notes", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_credit_notes", False, 0, str(e)))
    
    # Test get_debit_notes
    print("  get_debit_notes:", end=" ")
    try:
        resp = await client.get_debit_notes(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_debit_notes", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_debit_notes", False, 0, str(e)))
    
    # Test get_sales_orders
    print("  get_sales_orders:", end=" ")
    try:
        resp = await client.get_sales_orders(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_sales_orders", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_sales_orders", False, 0, str(e)))
    
    # Test get_purchase_orders
    print("  get_purchase_orders:", end=" ")
    try:
        resp = await client.get_purchase_orders(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_purchase_orders", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_purchase_orders", False, 0, str(e)))
    
    return results


async def test_inventory_tools(client: ManagerIOClient) -> List[ToolTestResult]:
    """Test INVENTORY agent tools."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing INVENTORY Agent Tools")
    print("=" * 60)
    
    # Test get_inventory_items
    print("  get_inventory_items:", end=" ")
    try:
        items = await client.get_inventory_items()
        print(f"✅ {len(items)} items")
        results.append(ToolTestResult("get_inventory_items", True, len(items)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_inventory_items", False, 0, str(e)))
    
    # Test get_inventory_kits
    print("  get_inventory_kits:", end=" ")
    try:
        kits = await client.get_inventory_kits()
        print(f"✅ {len(kits)} kits")
        results.append(ToolTestResult("get_inventory_kits", True, len(kits)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_inventory_kits", False, 0, str(e)))
    
    # Test get_goods_receipts
    print("  get_goods_receipts:", end=" ")
    try:
        resp = await client.get_goods_receipts(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_goods_receipts", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_goods_receipts", False, 0, str(e)))
    
    # Test get_delivery_notes
    print("  get_delivery_notes:", end=" ")
    try:
        resp = await client.get_delivery_notes(skip=0, take=5)
        print(f"✅ {len(resp.items)} items (total: {resp.total})")
        results.append(ToolTestResult("get_delivery_notes", True, resp.total))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_delivery_notes", False, 0, str(e)))
    
    return results


async def test_investment_tools(client: ManagerIOClient) -> List[ToolTestResult]:
    """Test INVESTMENT agent tools."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing INVESTMENT Agent Tools")
    print("=" * 60)
    
    # Test get_investments
    print("  get_investments:", end=" ")
    try:
        investments = await client.get_investments()
        print(f"✅ {len(investments)} investments")
        results.append(ToolTestResult("get_investments", True, len(investments)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_investments", False, 0, str(e)))
    
    # Test get_investment_market_prices
    print("  get_investment_market_prices:", end=" ")
    try:
        prices = await client.get_investment_market_prices()
        print(f"✅ {len(prices)} prices")
        results.append(ToolTestResult("get_investment_market_prices", True, len(prices)))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("get_investment_market_prices", False, 0, str(e)))
    
    return results


async def test_generic_api(client: ManagerIOClient) -> List[ToolTestResult]:
    """Test generic API call."""
    results = []
    
    print("\n" + "=" * 60)
    print("Testing Generic API Tool")
    print("=" * 60)
    
    # Test call_api
    print("  call_api (GET /divisions):", end=" ")
    try:
        resp = await client.call_api("GET", "/divisions", params={"pageSize": 5})
        if resp and "error" not in resp:
            print(f"✅ {list(resp.keys())}")
            results.append(ToolTestResult("call_api", True, 1))
        else:
            print(f"⚠️ {resp.get('error', 'empty')[:50]}")
            results.append(ToolTestResult("call_api", False, 0, resp.get('error')))
    except Exception as e:
        print(f"❌ {e}")
        results.append(ToolTestResult("call_api", False, 0, str(e)))
    
    return results


async def main():
    """Run all agent tool tests."""
    print("=" * 70)
    print("AGENT TOOLS INTEGRATION TEST")
    print("=" * 70)
    print(f"Base URL: {BASE_URL}")
    print(f"Testing all agent tools against live API...")
    
    client = ManagerIOClient(base_url=BASE_URL, api_key=READ_API_KEY)
    
    all_results = []
    
    try:
        all_results.extend(await test_data_tools(client))
        all_results.extend(await test_report_tools(client))
        all_results.extend(await test_transaction_tools(client))
        all_results.extend(await test_inventory_tools(client))
        all_results.extend(await test_investment_tools(client))
        all_results.extend(await test_generic_api(client))
    finally:
        await client.close()
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    successful = [r for r in all_results if r.success]
    failed = [r for r in all_results if not r.success]
    
    print(f"Total tools tested: {len(all_results)}")
    print(f"Successful: {len(successful)} ✅")
    print(f"Failed/Warning: {len(failed)} ❌")
    
    if failed:
        print("\nFailed/Warning tools:")
        for r in failed:
            print(f"  - {r.tool_name}: {r.error[:60] if r.error else 'Unknown'}")
    
    print("\n" + "=" * 70)
    print("DONE!")
    print("=" * 70)
    
    return len(failed) == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
