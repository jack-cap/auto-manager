# Auto Manager

AI-powered bookkeeping automation for Manager.io using LangGraph agents, FastAPI, and Next.js.

## Overview

This application integrates with Manager.io ([self-hosted accounting software](https://www.manager.io/server-edition)) to automate document processing. Users upload financial documents (receipts, invoices), and an AI agent extracts data, categorizes expenses, identifies suppliers, and posts entries to Manager.io.

## Tech Stack

- **Frontend**: Next.js 14+ with TypeScript and Tailwind CSS
- **Backend**: FastAPI with Python 3.11+
- **Database**: PostgreSQL (production) / SQLite (development)
- **Cache**: Redis
- **AI/ML**: LangGraph multi-agent system with LiteLLM for model routing
- **OCR**: chandra_ocr vision model via LMStudio

## Project Structure

```
├── frontend/           # Next.js TypeScript frontend
│   ├── app/           # Next.js App Router pages
│   ├── components/    # React components
│   ├── lib/           # Utility libraries and API client
│   └── types/         # TypeScript type definitions
├── backend/           # FastAPI Python backend
│   ├── app/
│   │   ├── api/       # API route handlers
│   │   ├── core/      # Configuration and utilities
│   │   ├── models/    # Database and Pydantic models
│   │   └── services/  # Business logic services
│   └── tests/         # Backend tests
├── docker-compose.yml # Development environment
└── .env.example       # Environment variable template
```

## Multi-Agent Architecture

The bookkeeping assistant uses a **LangGraph-based multi-agent system** with a supervisor routing pattern. This architecture provides focused toolsets for each domain, improving LLM performance and reducing context confusion.

### Agent Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         SUPERVISOR                              │
│  Routes requests to specialized agents based on intent          │
│  Keywords: DIRECT, DATA, REPORT, TRANSACTION, INVENTORY,        │
│            INVESTMENT, DOCUMENT, ENTRY                          │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│    DIRECT     │   │     DATA      │   │    REPORT     │
│  No tools     │   │  Master data  │   │  Financial    │
│  Simple Q&A   │   │  queries      │   │  reports      │
└───────────────┘   └───────────────┘   └───────────────┘
        
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  TRANSACTION  │   │   INVENTORY   │   │  INVESTMENT   │
│  Query txns   │   │  Stock mgmt   │   │  Portfolio    │
│  payments,    │   │  goods,       │   │  tracking,    │
│  receipts     │   │  transfers    │   │  forex        │
└───────────────┘   └───────────────┘   └───────────────┘

        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
┌───────────────┐                         ┌───────────────┐
│   DOCUMENT    │                         │     ENTRY     │
│  OCR extract  │                         │  Create/edit  │
│  classify     │                         │  entries      │
└───────────────┘                         └───────────────┘
```

### Agent Details

| Agent | Purpose | Key Tools |
|-------|---------|-----------|
| **DIRECT** | Simple Q&A, greetings, follow-up questions | None (direct LLM response) |
| **DATA** | Query master data | `get_chart_of_accounts`, `get_suppliers`, `get_customers`, `get_bank_accounts`, `get_employees`, `get_tax_codes`, `get_projects`, `get_fixed_assets`, `get_current_context` |
| **REPORT** | Financial reports | `get_balance_sheet`, `get_profit_and_loss`, `get_trial_balance`, `get_general_ledger_summary`, `get_cash_flow_statement`, `get_aged_receivables`, `get_aged_payables` |
| **TRANSACTION** | Query transactions | `get_recent_transactions`, `get_payments`, `get_receipts`, `get_expense_claims`, `get_purchase_invoices`, `get_sales_invoices`, `get_credit_notes`, `get_debit_notes` |
| **INVENTORY** | Inventory management | `get_inventory_items`, `get_inventory_kits`, `get_goods_receipts`, `get_delivery_notes`, `create_goods_receipt`, `create_inventory_write_off`, `create_inventory_transfer` |
| **INVESTMENT** | Investment tracking | `get_investments`, `get_investment_transactions`, `get_investment_market_prices`, `create_investment_account`, `handle_forex` |
| **DOCUMENT** | Document processing | `classify_document`, `extract_document_fields`, `search_supplier`, `search_account`, `match_vendor_to_supplier` |
| **ENTRY** | Create/modify entries | `search_employee`, `search_account`, `get_bank_accounts`, `create_supplier`, `create_customer`, `create_expense_claim`, `create_purchase_invoice`, `create_sales_invoice`, `create_payment`, `create_receipt`, `create_journal_entry`, `create_transfer`, `create_credit_note`, `create_debit_note`, `amend_entry`, `delete_entry`, `extract_fields_from_ocr` |

### Entry Creation Workflows

The ENTRY agent handles all accounting entry creation with proper double-entry bookkeeping:

#### Expense Claim (Employee Reimbursement)
```
DR: Expense account (e.g., Meals, Transportation)
CR: Amount due to employee/director

Tool: create_expense_claim(payer_key, date, description, account_key, amount)
Note: NO supplier needed - this is for employee out-of-pocket expenses
```

#### Purchase Invoice (Bill from Supplier)
```
DR: Expense or Asset account
CR: Accounts Payable (supplier)

Tool: create_purchase_invoice(supplier_key, date, description, account_key, amount)
Later: create_payment when paid
```

#### Payment - Two Modes

**Mode 1: Paying a Purchase Invoice**
```
DR: Accounts Payable (clears the liability)
CR: Bank account

Tool: create_payment(bank_account_key, date, payee, amount, 
                     supplier_key=X, purchase_invoice_key=Y)
Note: Do NOT pass account_key - the invoice already recorded the expense
```

**Mode 2: Direct Payment (no invoice)**
```
DR: Expense account
CR: Bank account

Tool: create_payment(bank_account_key, date, payee, amount, account_key=expense_account)
```

#### Sales Invoice (Bill to Customer)
```
DR: Accounts Receivable (customer)
CR: Income account

Tool: create_sales_invoice(customer_key, date, description, account_key, amount)
Later: create_receipt when customer pays
```

#### Receipt - Two Modes

**Mode 1: Receiving for a Sales Invoice**
```
DR: Bank account
CR: Accounts Receivable (clears the receivable)

Tool: create_receipt(bank_account_key, date, payer, amount,
                     customer_key=X, sales_invoice_key=Y)
Note: Do NOT pass account_key - the invoice already recorded the income
```

**Mode 2: Direct Receipt (no invoice)**
```
DR: Bank account
CR: Income account

Tool: create_receipt(bank_account_key, date, payer, amount, account_key=income_account)
```

### UUID Lookup Workflow

The ENTRY agent follows a strict sequential workflow:

1. **Search for UUIDs first** - Always call `search_employee`, `search_account`, or `get_bank_accounts` before creating entries
2. **One tool at a time** - Call one tool, wait for result, then call next (required for local LLMs)
3. **Semantic account matching** - `search_account` returns the full Chart of Accounts grouped by type; the LLM chooses the best match

Example workflow for expense claim:
```
Step 1: search_employee("director") → Get employee UUID
Step 2: search_account("transportation") → Get full COA, choose best account
Step 3: create_expense_claim(payer_key=UUID, account_key=UUID, ...)
```

### Document Processing Flow

When documents (receipts, invoices) are uploaded:

1. **OCR Extraction** - chandra_ocr model extracts text from images/PDFs
2. **Supervisor Routing** - Detects document markers, routes to ENTRY agent
3. **Field Extraction** - `extract_fields_from_ocr` parses vendor, amount, date
4. **UUID Lookup** - Search for employee, account UUIDs
5. **Entry Creation** - Create appropriate entry (expense claim, invoice, etc.)
6. **Confirmation** - Summarize created entries, ready for follow-up questions

## Getting Started

### Prerequisites

- Node.js 20+
- Python 3.11+
- Docker and Docker Compose (optional, for containerized development)
- Redis (for caching)
- PostgreSQL (for production) or SQLite (for development)
- LMStudio with chandra_ocr model (for OCR)

### Development Setup

1. **Clone the repository**

2. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

3. **Start with Docker Compose** (recommended)
   
   Use the provided management script:
   ```bash
   # Start services
   ./docker-manage.sh up
   
   # Stop services
   ./docker-manage.sh down
   
   # Clean rebuild (removes images, rebuilds without cache)
   ./docker-manage.sh rebuild
   
   # View logs
   ./docker-manage.sh logs
   ```

   Or use docker-compose directly:
   ```bash
   docker-compose up -d
   ```

4. **Backend setup** (manual)
   ```bash
   cd backend
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements-dev.txt
   uvicorn app.main:app --reload
   ```

5. **Frontend setup** (manual)
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

### Access the Application

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Documentation: http://localhost:8000/api/docs

> Tip: 
> To verify your Manager.io connection settings before starting the full app, run the test script: python backend/scripts/test_manager_io_api.py.

## LLM Configuration

The application supports multiple LLM providers through LiteLLM:

- **Local**: Ollama, LMStudio
- **Cloud**: OpenAI, Anthropic, etc.

Configure your preferred provider in `.env`:
```
DEFAULT_LLM_PROVIDER=lmstudio
DEFAULT_LLM_MODEL=zai-org/glm-4.7-flash
LMSTUDIO_URL=http://host.docker.internal:1234/v1 #for using docker
```

For OCR, ensure LMStudio is running with the chandra model loaded:
```
OCR_MODEL=chandra
```

### Local LLM Notes

When using local LLMs (e.g., glm-4.7-flash via LMStudio):
- Tool calls are processed **one at a time** (parallel tool calls may fail)
- The ENTRY agent prompt enforces sequential tool calling
- Larger context models (32K+) work better for complex multi-document processing

## Manager.io API Integration

The application integrates with Manager.io's REST API. See https://manager.readme.io/ for full api references.

Key API patterns:
- **List endpoints**: `GET /suppliers`, `GET /payments`, etc.
- **Form endpoints**: `POST /supplier-form` (create), `GET /supplier-form/{key}` (read)
- **Report endpoints**: Two-step - POST form to get key, then GET view with key

## Verified API Payloads

While the Multi-Agent system supports a wide range of actions, the following specific API payloads have been unit-tested against the Manager.io local instance.

### 1. General Ledger & Reporting
To generate financial statements (P&L, Balance Sheet), the agent will collect the general ledger summary and group the relevant accounting items.

2. Purchase Cycle (Invoice + Payment)
A. Create Purchase Invoice Endpoint
B. Make Payment (Linked to Invoice) Endpoint

3. Expense Claim
Used for out-of-pocket expenses by employees/directors.

Note on Untested Payloads: 
Other functions (Inventory Transfers, Fixed Asset depreciation, etc.) are implemented in the ENTRY agent based on standard Manager.io API patterns but have not yet been tested with live payloads.

## Usage Guide

- Access the Dashboard: Open http://localhost:3000.

- Connect Manager.io: Ensure your .env credentials are correct. The dashboard will show your current connection status.

- Chat & Upload:

   - Navigate to the Chat tab.

   - Click the Paperclip Icon to upload a receipt (PDF/Image).

   - Prompt the AI: Type instructions like "Process this invoice" or "Book this receipt as a travel expense for John".

   - Review: The AI will extract details, find the matching UUIDs, and confirm when the entry is posted to Manager.io.


## License

MIT

## Legal Disclaimer

This project is an unofficial automation tool and is not affiliated with, endorsed by, or connected to Manager.io. 

"Manager.io" is a trademark of its respective owner. This software uses the Manager.io API to interact with your self-hosted instance. Users are responsible for ensuring their use complies with Manager.io's terms of service.
