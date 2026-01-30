"""Business workflow definitions for the bookkeeping agent.

These workflows define the standard processes for common business transactions.
Agents can reference these to understand the proper sequence of steps.
"""

WORKFLOWS = {
    "expense_claim": {
        "name": "Expense Claim",
        "description": "Employee/director pays for business expense out of pocket, company reimburses later",
        "trigger": ["receipt", "expense", "reimbursement", "paid by director", "paid by employee"],
        "accounting": {
            "debit": "Expense account (based on nature: meals, transport, office supplies, etc.)",
            "credit": "Amount due to employee/director (liability)",
        },
        "steps": [
            "1. Identify the payer (who paid out of pocket)",
            "2. Identify the expense type and appropriate expense account",
            "3. Extract date and amount from receipt",
            "4. Create expense claim: payer, date, description, expense account, amount",
        ],
        "required_fields": ["payer", "date", "expense_account", "amount", "description"],
        "no_supplier_needed": True,
        "tool": "create_expense_claim",
    },
    
    "purchase_invoice": {
        "name": "Purchase Invoice (Bill from Supplier)",
        "description": "Company receives invoice from supplier for goods/services on credit",
        "trigger": ["invoice from supplier", "bill", "accounts payable", "we owe"],
        "accounting": {
            "debit": "Expense or Asset account",
            "credit": "Accounts Payable / Supplier",
        },
        "steps": [
            "1. Identify or create the supplier",
            "2. Identify the expense/asset account",
            "3. Extract invoice date, due date, reference number, amount",
            "4. Create purchase invoice",
            "5. Later: Create payment when invoice is paid",
        ],
        "required_fields": ["supplier", "date", "account", "amount"],
        "tool": "create_purchase_invoice",
    },
    
    "payment": {
        "name": "Payment (Money Out)",
        "description": "Company pays money from bank account",
        "trigger": ["pay", "payment", "bank transfer out", "settle invoice"],
        "accounting": {
            "debit": "Expense account OR Accounts Payable (if paying invoice)",
            "credit": "Bank/Cash account",
        },
        "steps": [
            "1. Identify the bank account paying from",
            "2. Identify what we're paying for (expense or settling invoice)",
            "3. Create payment with date, payee, amount",
        ],
        "required_fields": ["bank_account", "date", "payee", "amount"],
        "tool": "create_payment",
    },
    
    "receipt": {
        "name": "Receipt (Money In)",
        "description": "Company receives money into bank account",
        "trigger": ["received", "money in", "customer paid", "deposit"],
        "accounting": {
            "debit": "Bank/Cash account",
            "credit": "Income account OR Accounts Receivable (if receiving for invoice)",
        },
        "steps": [
            "1. Identify the bank account receiving into",
            "2. Identify source (income or customer paying invoice)",
            "3. Create receipt with date, payer, amount",
        ],
        "required_fields": ["bank_account", "date", "payer", "amount"],
        "tool": "create_receipt",
    },
    
    "advisory_engagement": {
        "name": "Advisory/Consulting Engagement",
        "description": "Full cycle: project setup → quotation → invoice → payment receipt",
        "trigger": ["engagement", "consulting", "advisory", "new project", "new client work"],
        "steps": [
            "1. CREATE PROJECT: Set up project for tracking time/costs",
            "2. SALES QUOTATION (optional): Send engagement letter/quote to client",
            "3. SALES INVOICE: Bill the client for services",
            "4. RECEIPT: Record payment when client pays",
        ],
        "sub_workflows": ["create_project", "sales_quotation", "sales_invoice", "receipt"],
    },
    
    "create_project": {
        "name": "Create Project",
        "description": "Set up a project for tracking income and expenses",
        "steps": [
            "1. Define project name and code",
            "2. Optionally link to customer",
            "3. Create project in system",
        ],
        "required_fields": ["name"],
        "tool": "call_manager_api",
        "api_endpoint": "/project-form",
    },
    
    "sales_invoice": {
        "name": "Sales Invoice (Bill to Customer)",
        "description": "Company bills customer for goods/services",
        "trigger": ["invoice to customer", "bill customer", "accounts receivable", "they owe us"],
        "accounting": {
            "debit": "Accounts Receivable / Customer",
            "credit": "Income account",
        },
        "steps": [
            "1. Identify or create the customer",
            "2. Identify the income account",
            "3. Set invoice date, due date, reference",
            "4. Create sales invoice",
            "5. Later: Create receipt when customer pays",
        ],
        "required_fields": ["customer", "date", "account", "amount"],
        "tool": "create_sales_invoice",
    },
    
    "procurement": {
        "name": "Procurement (Company Pays Directly)",
        "description": "Company purchases goods/services and pays directly (not expense claim)",
        "trigger": ["company paid", "direct purchase", "procurement"],
        "steps": [
            "1. If on credit: Create purchase invoice first, then payment later",
            "2. If paid immediately: Create payment directly",
        ],
        "sub_workflows": ["purchase_invoice", "payment"],
    },
    
    "inventory_purchase": {
        "name": "Inventory Purchase",
        "description": "Purchase inventory items for resale",
        "trigger": ["buy inventory", "stock purchase", "goods for resale"],
        "accounting": {
            "debit": "Inventory asset account",
            "credit": "Accounts Payable or Bank",
        },
        "steps": [
            "1. Create or select inventory item",
            "2. Create purchase invoice with inventory item",
            "3. Create goods receipt when items arrive",
            "4. Create payment when invoice is paid",
        ],
        "sub_workflows": ["purchase_invoice", "goods_receipt", "payment"],
    },
    
    "journal_entry": {
        "name": "Journal Entry",
        "description": "Manual accounting adjustment",
        "trigger": ["journal", "adjustment", "accrual", "provision", "correction"],
        "accounting": {
            "debit": "Account to increase (assets/expenses) or decrease (liabilities/income)",
            "credit": "Account to decrease (assets/expenses) or increase (liabilities/income)",
        },
        "steps": [
            "1. Identify accounts to debit and credit",
            "2. Ensure debits = credits",
            "3. Create journal entry with narration",
        ],
        "required_fields": ["date", "debit_account", "credit_account", "amount", "description"],
        "tool": "create_journal_entry",
    },
}


def get_workflow(name: str) -> dict:
    """Get a workflow definition by name."""
    return WORKFLOWS.get(name, {})


def find_workflow_by_trigger(text: str) -> list:
    """Find workflows that match trigger keywords in the text."""
    text_lower = text.lower()
    matches = []
    
    for name, workflow in WORKFLOWS.items():
        triggers = workflow.get("trigger", [])
        for trigger in triggers:
            if trigger.lower() in text_lower:
                matches.append((name, workflow))
                break
    
    return matches


def get_workflow_prompt(workflow_name: str) -> str:
    """Generate a prompt snippet explaining a workflow."""
    workflow = WORKFLOWS.get(workflow_name)
    if not workflow:
        return ""
    
    lines = [
        f"## {workflow['name']}",
        f"{workflow['description']}",
        "",
    ]
    
    if "accounting" in workflow:
        lines.append("Accounting treatment:")
        lines.append(f"  DR: {workflow['accounting']['debit']}")
        lines.append(f"  CR: {workflow['accounting']['credit']}")
        lines.append("")
    
    if "steps" in workflow:
        lines.append("Steps:")
        for step in workflow["steps"]:
            lines.append(f"  {step}")
        lines.append("")
    
    if "required_fields" in workflow:
        lines.append(f"Required: {', '.join(workflow['required_fields'])}")
    
    if workflow.get("no_supplier_needed"):
        lines.append("Note: No supplier needed for this transaction type.")
    
    return "\n".join(lines)


def get_all_workflows_summary() -> str:
    """Get a summary of all workflows for agent reference."""
    lines = ["# Available Business Workflows", ""]
    
    for name, workflow in WORKFLOWS.items():
        lines.append(f"- **{workflow['name']}**: {workflow['description']}")
        if "trigger" in workflow:
            lines.append(f"  Keywords: {', '.join(workflow['trigger'][:3])}")
    
    return "\n".join(lines)
