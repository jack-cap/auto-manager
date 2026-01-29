# Auto Manager

> **Trust the System, Not the Prediction.**

Privacy-preserving AI bookkeeping automation using local LLMs. Process receipts and invoices without sending your financial data to the cloud.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Paper](https://img.shields.io/badge/Paper-PAPER.md-blue)](PAPER.md)

## Why Auto Manager?

Cloud AI services like GPT-5.2 and Claude are powerful, but they require sending your sensitive financial data to third-party servers. For businesses handling confidential ledgers, this creates unacceptable privacy and compliance risks (GDPR, EU AI Act).

**Auto Manager runs entirely on your hardware.** Your invoices, receipts, and general ledger never leave your infrastructure.

### Key Features

- 🔒 **100% Local Inference** - All AI processing happens on your machine via LMStudio/Ollama
- 📄 **Document Processing** - Upload receipts/invoices, AI extracts and categorizes automatically  
- 🤖 **Multi-Agent Architecture** - Specialized agents for different accounting tasks
- ✅ **Validation Layer** - Pydantic schemas catch errors before they hit your ledger
- 🔗 **Manager.io Integration** - Direct API integration with self-hosted Manager.io

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         SUPERVISOR                              │
│  Routes requests to specialized agents based on intent          │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│    DIRECT     │   │     DATA      │   │    REPORT     │
│  Simple Q&A   │   │  Master data  │   │  Financials   │
└───────────────┘   └───────────────┘   └───────────────┘
        
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│  TRANSACTION  │   │   INVENTORY   │   │  INVESTMENT   │
│  Query txns   │   │  Stock mgmt   │   │  Portfolio    │
└───────────────┘   └───────────────┘   └───────────────┘

        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
┌───────────────┐                         ┌────────────────┐
│   DOCUMENT    │                         │      ENTRY     │
│  OCR/classify │                         │ Create entries │
└───────────────┘                         └────────────────┘
```

The system uses a **Supervisor-Worker pattern** built on LangGraph. Each agent has focused tools for its domain, preventing context pollution and improving reliability.

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Next.js 14+, TypeScript, Tailwind CSS |
| **Backend** | FastAPI, Python 3.11+ |
| **Orchestration** | LangGraph |
| **Inference** | LMStudio / Ollama (GLM 4.7 Flash recommended) |
| **OCR** | Chandra vision model |
| **Validation** | Pydantic |
| **Accounting** | Manager.io (self-hosted) |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+
- [LMStudio](https://lmstudio.ai/) with GLM 4.7 Flash model
- [Manager.io Server Edition](https://www.manager.io/server-edition) (self-hosted)
- Docker (optional)

### Installation

1. **Clone and configure**
   ```bash
   git clone https://github.com/jack-cap/auto-manager.git
   cd auto-manager
   cp .env.example .env
   # Edit .env with your Manager.io API credentials
   ```

2. **Start with Docker** (recommended)
   ```bash
   ./docker-manage.sh up
   ```

   Or manually:
   ```bash
   # Backend
   cd backend && python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   uvicorn app.main:app --reload

   # Frontend (new terminal)
   cd frontend && npm install && npm run dev
   ```

3. **Configure LMStudio**
   - Load `zai-org/glm-4.7-flash` model
   - Start local server on port 1234
   - Load `chandra` model for OCR

4. **Access the app**
   - Frontend: http://localhost:3000
   - API Docs: http://localhost:8000/api/docs

## Usage

1. **Upload a document** - Click the paperclip icon in chat to upload a receipt or invoice
2. **Give instructions** - "Book this as a travel expense for John" or "Create a purchase invoice"
3. **Review and confirm** - The AI extracts details, looks up accounts, and creates the entry
4. **Check Manager.io** - Entry appears in your accounting software

### Example Interaction

```
User: "I have a receipt from Uber for $45.50 on January 15, paid by the director"

Agent Flow:
1. search_employee("director") → Gets UUID
2. search_account("transportation") → Finds "Local taxi or uber" account
3. create_expense_claim(payer=UUID, account=UUID, amount=45.50)

Response: "Created expense claim for $45.50 (Uber) charged to Local taxi or uber,
           reimbursable to John Director."
```

## Configuration

```env
# LLM Settings
DEFAULT_LLM_PROVIDER=lmstudio
DEFAULT_LLM_MODEL=zai-org/glm-4.7-flash
LMSTUDIO_URL=http://localhost:1234/v1

# Manager.io
MANAGER_API_URL=https://your-manager-instance/api2
MANAGER_API_KEY=your-api-key

# OCR
OCR_MODEL=chandra
```

## Documentation

- **[PAPER.md](PAPER.md)** - Technical paper describing the architecture, methodology, and design decisions
- **[Manager.io API Reference](.kiro/steering/manager-io-api.md)** - API patterns and tested payloads

## How It Works

### The "Trust the System" Philosophy

LLMs are probabilistic—they make mistakes. Instead of hoping the model gets it right, we build guardrails:

1. **Sequential Tool Execution** - One tool call at a time, wait for result, then proceed (prevents hallucinated UUIDs)
2. **Mandatory Lookups** - Agent must search for employee/account UUIDs before creating entries
3. **Pydantic Validation** - All payloads validated against strict schemas before API calls
4. **Loop Detection** - Terminates if same tool called repeatedly (prevents infinite loops)

### Why Local LLMs Work

Modern Small Language Models (SLMs) like GLM 4.7 Flash can handle complex reasoning when properly constrained. The key insights:

- **Constrained action space** - Focused tools per agent reduces confusion
- **Semantic matching** - LLM chooses accounts from full Chart of Accounts (handles "audit fee" ≈ "professional fees")
- **Quantization** - 8-bit inference enables running on consumer hardware (24GB+ RAM recommended)

## Limitations

- Requires 24GB+ RAM for optimal performance
- Tightly coupled to Manager.io API structure
- Local LLMs process one tool call at a time (slower than cloud)
- Not tested for production workloads—use at your own risk

## Contributing

Contributions welcome! Areas of interest:

- Bank reconciliation automation
- Additional accounting software integrations
- Performance benchmarking vs cloud LLMs
- Test coverage improvements

## License

MIT License - see [LICENSE](LICENSE)

## Acknowledgments

This project builds on excellent open-source work:

- **[LangGraph](https://github.com/langchain-ai/langgraph)** - State machine orchestration for LLM applications
- **[Chandra](https://github.com/datalab-to/chandra)** ([HuggingFace](https://huggingface.co/datalab-to/chandra)) - Layout-aware document OCR model
- **[LMStudio](https://lmstudio.ai/)** - Local LLM inference server
- **[Ollama](https://ollama.com/)** - Run LLM on locally
- **[GLM-4.7-Flash](https://z.ai/blog/glm-4.7)** - The foundation model powering our agents ([HuggingFace](https://huggingface.co/zai-org/GLM-4.7-Flash))

## Disclaimer

This project is an independent, open-source implementation. It is **not affiliated with, endorsed by, or connected to Manager.io**. "Manager.io" is a trademark of its respective owner. Users are responsible for ensuring compliance with Manager.io's terms of service.

---

**Author:** Chun Kit, NG  
**Repository:** https://github.com/jack-cap/auto-manager
