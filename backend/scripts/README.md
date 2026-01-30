# Manager.io API Test Scripts

This folder contains test scripts for the Manager.io API integration.

## Scripts

### `test_all_endpoints.py` - Comprehensive Endpoint Tester
Tests all GET endpoints from the OpenAPI spec automatically.

```bash
python scripts/test_all_endpoints.py              # Test all GET endpoints
python scripts/test_all_endpoints.py --endpoint /receipts  # Test specific endpoint
```

**Output:**
- `test_results/endpoint_test_report.json` - Full test report
- `test_results/endpoint_metadata.json` - Endpoint metadata for agent use
- `test_results/working_endpoints.txt` - List of working endpoints

### `test_crud_operations.py` - CRUD Operations Tester
Tests Create, Read, Update, Delete operations using the blank test company.

```bash
python scripts/test_crud_operations.py            # Run all CRUD tests (creates & deletes)
python scripts/test_crud_operations.py --keep     # Keep created records for inspection
```

**Tests:**
- Supplier CRUD
- Customer CRUD
- Project CRUD
- Journal Entry CRUD
- Report Form/View pattern

### `test_manager_io_api.py` - ManagerIOClient Tester
Tests the `ManagerIOClient` wrapper class methods.

```bash
python scripts/test_manager_io_api.py             # Run all tests
python scripts/test_manager_io_api.py -v          # Verbose mode with sample data
python scripts/test_manager_io_api.py --url <URL> --key <KEY>  # Custom credentials
```

### `test_manager_openapi.py` - OpenAPI Spec Fetcher
Fetches and saves the OpenAPI specification from the Manager.io API.

```bash
python scripts/test_manager_openapi.py
```

**Output:**
- `manager_openapi.json` - The full OpenAPI 3.0 specification

### `test_agent_tools_integration.py` - Agent Tools Integration Tester
Tests all agent tools against the live API to verify correct API calls and response parsing.

```bash
python scripts/test_agent_tools_integration.py
```

**Tests:**
- DATA agent tools (accounts, suppliers, customers, etc.)
- REPORT agent tools (balance sheet, P&L, trial balance, etc.)
- TRANSACTION agent tools (payments, receipts, invoices, etc.)
- INVENTORY agent tools (items, goods receipts, etc.)
- INVESTMENT agent tools (investments, market prices)
- Generic API tool

## Files

### `manager_openapi.json`
The complete OpenAPI 3.0 specification for the Manager.io API (692 endpoints).
Use this as reference for available endpoints and their schemas.

## Test Results Summary

### GET Endpoints (test_all_endpoints.py)
- **148 working** ✅
- **7 failing** ❌ - Manager.io server bugs (500 errors)

### Agent Tools (test_agent_tools_integration.py)
- **33 out of 33 tools working** ✅
- All report tools now work via derived fallbacks

### CRUD Operations (test_crud_operations.py)
- **24 out of 24 operations working** ✅

### Working Reports
These reports work correctly using the form/view pattern:
- `get_general_ledger_summary` ✅
- `get_aged_receivables` ✅
- `get_aged_payables` ✅

### READ-ONLY: 
- Has real data for reading/testing queries
- Configure in `scripts/.env.test` as `MANAGER_READ_API_KEY`

### WRITE: 
- Blank company for testing write operations (POST, PUT, DELETE)
- Configure in `scripts/.env.test` as `MANAGER_WRITE_API_KEY`

**Base URL**: Configure in `scripts/.env.test` as `MANAGER_READ_BASE_URL`

## Setup

1. Copy `scripts/.env.test.example` to `scripts/.env.test`
2. Fill in your API keys
3. Run the tests

## Quick Reference

| Endpoint | Response Key | Sample Fields |
|----------|--------------|---------------|
| `/receipts` | `receipts` | date, receivedIn, description, paidBy, amount |
| `/payments` | `payments` | date, paidFrom, description, payee, amount |
| `/expense-claims` | `expenseClaims` | date, payee, description, accounts, amount |
| `/purchase-invoices` | `purchaseInvoices` | issueDate, reference, supplier, invoiceAmount, status |
| `/sales-invoices` | `salesInvoices` | issueDate, reference, customer, invoiceAmount, status |
| `/journal-entries` | `journalEntries` | date, narration, accounts, debit, credit |
| `/chart-of-accounts` | `chartOfAccounts` | key, code, name |
| `/suppliers` | `suppliers` | key, code, name, accountsPayable, status |
| `/customers` | `customers` | key, name, accountsReceivable, status |
| `/bank-and-cash-accounts` | `bankAndCashAccounts` | key, name, actualBalance |

See `test_results/endpoint_metadata.json` for the complete mapping.
