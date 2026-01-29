# Orchestrating Local Large Language Models for Privacy-Preserving Automated Bookkeeping: A Multi-Agent Supervisor Architecture

**Author:** Chun Kit, NG
**Date:** January 2026  
**Repository:** https://github.com/jack-cap/auto-manager

> **Author Note:** This research presents an independent, open-source architectural implementation. The author is not affiliated with, endorsed by, or connected to Manager.io.

---

## Preface: Trust the System, Not the Prediction

> *Stop for a second if you think you can "trust" AI.*
>
> *The reality is that LLMs are probabilistic, not deterministic. They play the odds, and just like humans, they make mistakes.*
>
> *Instead of trusting the model, we must trust the system.*
>
> *We don't blindly trust a new employee without checks and balances; we trust the workflows, reviews, and processes we put in place. The same logic applies to AI.*
>
> *This is why the future of AI isn't just about training better foundation models—it's about the engineering, guardrails, and verification layers we build around them.*
>
> ***Trust the process, not the prediction.***

---

## Abstract

The integration of Artificial Intelligence (AI) into financial accounting is currently hindered by a "Privacy-Utility Paradox"—a well-documented tension in privacy-preserving machine learning where local inference preserves data sovereignty at the cost of model capability (Abadi et al., 2016). Cloud-hosted Large Language Models (LLMs) offer the reasoning capability required for complex bookkeeping but introduce unacceptable data sovereignty risks. Conversely, local models have historically lacked the reliability to handle double-entry logic without supervision.

This paper presents **Auto Manager**, a reference architecture that addresses this tension by orchestrating Small Language Models (SLMs)—specifically Zai GLM 4.7 Flash—within a hierarchical Supervisor-Worker Multi-Agent System (MAS).

**This work shifts the focus from "Trusting the Model" to "Trusting the System."** We argue that in high-stakes domains like finance, reliability should not come from the probabilistic output of a foundation model, but from the engineering guardrails that surround it.

By leveraging LangGraph for stateful orchestration and implementing a strict **Sequential Tool Execution** pattern (Search → Wait → Act), the system is designed to mitigate hallucination patterns typically associated with smaller models. We demonstrate that combining a high-speed local inference engine (LMStudio) with Pydantic-based constraint verification enables privacy-preserving bookkeeping on consumer-grade hardware.

---

## Key Contributions

### 1. A Reference Architecture for Sovereign AI

We present a blueprint for a fully local, air-gapped bookkeeping agent. Unlike SaaS solutions, this architecture ensures **zero data egress**, satisfying strict data sovereignty requirements (GDPR/EU AI Act) by running entirely on consumer hardware (LMStudio/Ollama).

### 2. Reliability via Architectural Constraints

We demonstrate that Small Language Models (SLMs) like GLM 4.7 Flash can achieve improved reliability in complex tasks if the architecture enforces strict workflows. By implementing a **Sequential Tool Execution** pattern (Search → Wait → Act), we architecturally eliminate specific classes of hallucination (such as invalid Foreign Keys) that typically affect smaller models.

### 3. The Deterministic Firewall Pattern

We introduce a verification layer that acts as a firewall between the **Probabilistic Agent** and the **Deterministic Ledger**. This implements a runtime assurance pattern (Schierman et al., 2015) where probabilistic components are wrapped by deterministic monitors—a technique established in safety-critical cyber-physical systems. By validating agent outputs against strict Pydantic schemas before API execution, the system catches and rejects malformed entries (e.g., negative prices, missing UUIDs) before they can corrupt the accounting database.

---

## 1. Introduction

The digitalization of financial services is shifting from deterministic rules-based systems (ERPs) to probabilistic automation via Generative AI. LLMs promise to automate the "last mile" of bookkeeping—interpreting unstructured data like vendor emails and receipts—which has stubbornly resisted traditional automation.

However, the dominant "Model-as-a-Service" paradigm (e.g., GPT-5.2, Claude 4.5) necessitates transmitting sensitive general ledgers to third-party clouds, creating vectors for Personally Identifiable Information (PII) leakage and violating data sovereignty mandates such as the EU AI Act or GDPR.

This paper proposes a **Local-First Architecture** that shifts inference to the edge. We present Auto Manager, a proof-of-concept system that explores the feasibility of using quantized (Dettmers et al., 2022) Small Language Models (SLMs) to perform accounting tasks without data ever leaving the user's infrastructure.

### 1.1 Scope and Limitations

This work is an **applied case study**, not a claim of fundamental novelty. The individual components (LangGraph, Pydantic, local LLMs) are established technologies. Our contribution lies in:

1. **Integration**: Combining these components for a specific high-stakes domain (bookkeeping)
2. **Lessons Learned**: Documenting practical constraints discovered during implementation
3. **Open Source**: Providing a working reference implementation for others to build upon

We have not conducted a comprehensive literature review and do not claim this is the first or only approach to local AI bookkeeping. We welcome references to related work.

---

## 2. The Privacy-Utility Gap in Financial AI

### 2.1 The Vulnerability of Cloud Inference

Recent studies (Kim et al., 2023) utilizing the ProPILE framework have demonstrated that LLMs are susceptible to "linkability" attacks, where models can infer redacted PII based on transaction patterns. In bookkeeping, transaction descriptions often contain quasi-identifiers (vendor names, reference IDs) that make anonymization insufficient.

### 2.2 The Regulatory Imperative

With financial AI systems increasingly classified as "High-Risk" under frameworks like the EU AI Act (European Parliament, 2024), the requirement for **Data Residency** (keeping data within specific jurisdictions) is becoming absolute. The GDPR (European Parliament, 2016) further mandates strict controls over personal data processing. Local inference eliminates this compliance burden by ensuring the ledger never crosses a network boundary.

---

## 3. System Architecture: The Supervisor-Worker Pattern

To replicate the judgment of a human accountant using resource-constrained local models, we implemented a Hierarchical Multi-Agent System (HMAS) using LangGraph. This approach draws on foundational MAS research (Wooldridge, 2009) which establishes that complex tasks can be decomposed across specialized agents with defined responsibilities.

### 3.1 Decomposition of Responsibility

Instead of a monolithic agent, the system decomposes the bookkeeping workflow into specialized domains, preventing context window pollution:

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
└───────────────┘   └───────────────┘   └───────────────┘

        ┌─────────────────────┴─────────────────────┐
        ▼                                           ▼
┌───────────────┐                         ┌───────────────┐
│   DOCUMENT    │                         │     ENTRY     │
│  OCR extract  │                         │  Create/edit  │
│  classify     │                         │  entries      │
└───────────────┘                         └───────────────┘
```

**The Supervisor (Router):** Acts as the cognitive "traffic controller." It classifies user intent (e.g., "Report" vs. "Entry" vs. "Inventory") and routes the state to the appropriate sub-agent.

**The Workers (Specialists):**
- **DOCUMENT Agent:** Specialized in OCR (via chandra_ocr) and document classification.
- **ENTRY Agent:** Handles double-entry logic and API interactions.
- **REPORT Agent:** Read-only access to financial statements.
- **DATA Agent:** Queries master data (accounts, suppliers, customers).
- **TRANSACTION Agent:** Queries historical transactions.
- **INVENTORY/INVESTMENT Agents:** Domain-specific logic for stock and portfolio tracking.

### 3.2 Stateful Graph Orchestration

Unlike conversational frameworks (e.g., AutoGen), LangGraph models the workflow as a state machine. This allows for:

- **Cyclic Error Correction:** If an API call fails, the graph can route back to the reasoning node for a retry.
- **Human-in-the-Loop:** The graph state can be paused for manual approval before "commit" operations (database writes), following established HITL design principles (Amershi et al., 2019).
- **Loop Detection:** The system tracks recent tool calls and terminates if the same call is repeated more than twice, preventing infinite loops.

```python
# Simplified LangGraph state definition
class AgentState(TypedDict):
    messages: Annotated[Sequence[BaseMessage], add_messages]
    current_agent: str  # "supervisor", "data", "entry", etc.
    thinking_steps: List[ThinkingStep]
    should_continue: bool
```

---

## 4. Methodology: Orchestrating Zai GLM 4.7 Flash

A core contribution of this work is demonstrating that Zai GLM 4.7 Flash, a high-efficiency SLM, can perform complex financial reasoning when properly constrained.

### 4.1 Reasoning Density vs. Model Size

While historically requiring 70B+ parameter models, financial reasoning is achievable with smaller models if the action space is constrained. Recent surveys on Small Language Models (Wang et al., 2025; Lu et al., 2024) demonstrate that SLMs can match larger models on domain-specific tasks when properly guided. Advances in quantization techniques (Dettmers et al., 2022) have further enabled running large models on consumer hardware. GLM 4.7 Flash, a 30B-A3B MoE model leveraging sparse activation (Shazeer et al., 2017), provides an optimal balance of token throughput (essential for batch processing receipts) and instruction-following capability.

### 4.2 Mitigating Hallucination via Sequential Tool Execution

Small models often "hallucinate" database IDs (UUIDs) or invent foreign keys—a well-documented phenomenon in LLM research (Zhang et al., 2023). To solve this, we enforced a **Sequential Lookup Pattern** within the Entry Agent's system prompt, implementing a variant of the ReAct paradigm (Yao et al., 2022) which interleaves reasoning and action:

**The Anti-Hallucination Workflow:**

1. **Constraint:** The agent is forbidden from guessing UUIDs.
2. **Step 1 (Search):** Call `search_employee("director")` → Wait for API response.
3. **Step 2 (Select):** The agent receives the actual UUID from the local database.
4. **Step 3 (Act):** Call `create_expense_claim(payer_key=UUID, ...)` using the retrieved ID.

This "Look-Before-You-Leap" architecture effectively grounds the SLM in the reality of the database schema, reducing foreign key errors to near zero.

### 4.3 Single Tool Execution Constraint

A critical discovery during implementation: local LLM inference servers (specifically LMStudio) often fail to parse multiple parallel tool calls, returning only the first tool call and dropping subsequent ones. This causes the model to enter confusion loops.

**Solution:** The ENTRY agent prompt explicitly enforces:

```
=== CRITICAL: ONE TOOL AT A TIME ===
Call ONE tool, wait for the result, then call the next tool.
DO NOT try to call multiple tools in parallel.
```

This constraint, while reducing theoretical throughput, dramatically improves reliability with local inference. This finding aligns with Schick et al. (2023) who demonstrated that constrained tool-calling patterns improve model reliability.


### 4.4 Semantic Account Matching

Traditional string-matching for account lookup fails on minor variations (e.g., "audit fees" vs "audit fee"). Our solution: return the **entire Chart of Accounts** grouped by type and let the LLM perform semantic matching. This approach leverages the LLM's implicit semantic space—a capability that builds on semantic embedding techniques (Reimers & Gurevych, 2019) for short-text categorization:

```python
@tool
async def search_account(description: str) -> str:
    """Get the Chart of Accounts to find the appropriate account."""
    accounts = await manager_client.get_chart_of_accounts()
    
    return {
        "looking_for": description,
        "expense_accounts": [a for a in accounts if a.code.startswith("5")],
        "income_accounts": [a for a in accounts if a.code.startswith("4")],
        "asset_accounts": [a for a in accounts if a.code.startswith("1")],
        # ... grouped by type
    }
```

The LLM's semantic understanding ("audit fee" ≈ "professional fees") outperforms fuzzy string matching.

---

## 5. Implementation Details

The Auto Manager stack consists of:

| Layer | Component | Function |
|-------|-----------|----------|
| **Orchestration** | LangGraph | Manages state, enforces sequential logic, handles routing |
| **Inference** | Zai GLM 4.7 Flash | High-speed local reasoning core (via LMStudio) |
| **Vision** | Chandra_OCR | Local vision model for text extraction from receipts/PDFs |
| **Safety** | Pydantic | Validates structured outputs against strict schemas |
| **Backend** | FastAPI | Provides interface between agents and Manager.io API |
| **Frontend** | Next.js | User interface for document upload and chat |

### 5.1 Document Processing Pipeline

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Upload     │───▶│  OCR Extract │───▶│  Supervisor  │───▶│    ENTRY     │
│  (Image/PDF) │    │  (Chandra)   │    │   Routes     │    │   Agent      │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
                                                                   │
                    ┌──────────────┐    ┌──────────────┐           │
                    │   Manager.io │◀───│   Validate   │◀──────────┘
                    │     API      │    │  (Pydantic)  │
                    └──────────────┘    └──────────────┘
```

1. **Upload:** User uploads receipt/invoice image or PDF
2. **OCR:** Chandra vision model extracts text locally
3. **Routing:** Supervisor detects document markers, routes to ENTRY agent
4. **Processing:** ENTRY agent extracts fields, looks up UUIDs, creates entry
5. **Validation:** Pydantic validates payload structure before API call
6. **Commit:** Entry posted to Manager.io accounting software

### 5.2 Constraint-Based Verification

We implemented a verification layer inspired by the REDSQL methodology (Ren et al., 2025), which demonstrates that constraint-based verification can significantly improve reliability in LLM-generated outputs. Before any write operation is transmitted to the accounting software, the payload is validated against Pydantic models:

```python
class ExpenseClaimLine(BaseModel):
    account: str  # UUID - validated format
    line_description: str
    qty: float = Field(gt=0)
    purchase_unit_price: float = Field(gt=0)

class ExpenseClaimData(BaseModel):
    date: str  # YYYY-MM-DD format
    paid_by: str  # Employee UUID
    payee: str
    lines: List[ExpenseClaimLine] = Field(min_length=1)
```

This ensures that even if the LLM generates a malformed request, it is caught by the validation layer, preventing data corruption.

---

## 6. Discussion and Future Work

### 6.1 Observations (Not Validated Claims)

Based on our implementation experience, we observe that:

1. **Local Inference Is Feasible:** Modern SLMs like GLM 4.7 Flash appear capable of handling double-entry logic when wrapped in a supervisor architecture. However, we have not conducted rigorous benchmarking against cloud alternatives.

2. **Architecture Matters:** Anecdotally, reliability improved significantly after implementing sequential constraints and loop detection. Quantitative measurement of error rates before/after would strengthen this observation.

3. **Semantic Matching:** Letting the LLM choose accounts from a full list appears to handle variations (e.g., "audit fee" vs "audit fees") better than our initial string-matching approach. Formal evaluation is needed.

4. **Constraints Enable Autonomy:** Adding constraints (one tool at a time, mandatory UUID lookup) seemed to reduce failure modes. This aligns with the "Trust the System" philosophy but requires empirical validation.

> **Note:** These are qualitative observations from development, not rigorously tested claims. Future work should include systematic evaluation with defined metrics.

### 6.2 What We Haven't Tested

To make stronger claims, the following experiments would be needed:

| Claim | Required Evidence |
|-------|-------------------|
| "Reduced hallucination" | Error rate comparison: with/without sequential constraints |
| "Better than cloud" | Accuracy comparison: local SLM vs GPT-5/Claude on same tasks |
| "Semantic > String matching" | Account categorization accuracy on labeled dataset |
| "Production ready" | Long-term reliability metrics, edge case coverage |

### 6.3 Research Gaps

1. **Adversarial Robustness:** Local agents function within a trusted perimeter, but susceptibility to "prompt injection" via malicious invoice text remains an open research area (Liu et al., 2023).

2. **Procedural Corpora:** There is a lack of open-source datasets for procedural accounting logic (Standard Operating Procedures), limiting the ability to fine-tune models specifically for GAAP/IFRS compliance.

3. **Bank Reconciliation:** Automated matching of bank statement entries to recorded transactions remains an area for future development.

### 6.4 Limitations

- **Hardware Requirements:** While running on consumer hardware, performance degrades significantly below 24GB RAM
- **Context Window:** Complex multi-document scenarios may exceed the model's effective context window
- **API Dependency:** System is tightly coupled to Manager.io's API structure

---

## 7. Conclusion

The Auto Manager project explores whether local AI can handle financial bookkeeping without cloud dependency. While we cannot claim definitive superiority over cloud solutions without rigorous benchmarking, our implementation suggests that:

1. **Local inference is technically feasible** for bookkeeping tasks on consumer hardware
2. **Architectural constraints** (sequential execution, validation layers) appear to improve reliability
3. **Privacy preservation** is achievable by keeping all data on-premises

The central thesis—**"Trust the System, Not the Prediction"**—proposes that reliability in AI systems should come from engineering guardrails rather than model capability alone. By forcing sequential tool execution, mandatory UUID lookups, and Pydantic validation, we aim to transform probabilistic model outputs into deterministic, verifiable actions.

This work provides a **reference implementation** for others exploring local AI in high-stakes domains. We welcome feedback, criticism, and pointers to related work we may have missed.

### Call to Action

If you're working on similar problems or have conducted research in this space, we'd appreciate:
- References to related academic work
- Suggestions for evaluation methodologies
- Contributions to the open-source implementation

---

## References

Abadi, M., Chu, A., Goodfellow, I., McMahan, H.B., Mironov, I., Talwar, K. and Zhang, L. (2016) 'Deep learning with differential privacy', *CCS '16: Proceedings of the 2016 ACM SIGSAC Conference on Computer and Communications Security*, pp. 308-318.

Amershi, S., Weld, D., Vorvoreanu, M., Fourney, A., Nushi, B., Collisson, P. et al. (2019) 'Guidelines for human-AI interaction', *CHI '19: Proceedings of the 2019 CHI Conference on Human Factors in Computing Systems*, pp. 1-13.

Datalab.to (n.d.) *Chandra: Layout-aware document OCR*. Available at: https://huggingface.co/datalab-to/chandra (Accessed: January 2026).

Dettmers, T., Lewis, M., Belkada, Y. and Zettlemoyer, L. (2022) 'LLM.int8(): 8-bit Matrix Multiplication for Transformers at Scale', *NeurIPS 2022: Advances in Neural Information Processing Systems*. (Validates the feasibility of running large models on consumer hardware).

European Parliament and Council (2016) *Regulation (EU) 2016/679 (General Data Protection Regulation)*. Official Journal of the European Union, L119, pp. 1-88.

European Parliament and Council (2024) *Regulation (EU) 2024/1689 laying down harmonised rules on artificial intelligence (AI Act)*. Official Journal of the European Union.

Kim, S., Yun, S., Lee, H., Gubri, M., Yoon, S. and Kwon, S.J. (2023) 'ProPILE: Probing privacy leakage in large language models', *Advances in Neural Information Processing Systems (NeurIPS)*, 36.

LangChain AI (n.d.) *LangGraph: Cyclic state-based orchestration for LLM applications*. Available at: https://langchain-ai.github.io/langgraph/ (Accessed: January 2026).

Liu, Y., Deng, G., Xu, Z., Li, Y., Zheng, Y., Zhang, Y. et al. (2023) 'Prompt injection attack against LLM-integrated applications', *arXiv preprint*, arXiv:2306.05499.

LMStudio (n.d.) *LMStudio: Local inference server*. Available at: https://lmstudio.ai/ (Accessed: January 2026).

Lu, Z., Pu, H., Wang, F., Hu, Z. and Wang, L. (2024) 'Small language models: Survey, measurements, and beyond', *arXiv preprint*, arXiv:2409.15790.

Manager.io (n.d.) *Manager.io API documentation*. Available at: https://manager.readme.io/ (Accessed: January 2026).

Pydantic (n.d.) *Data validation using Python type annotations*. Available at: https://docs.pydantic.dev/ (Accessed: January 2026).

Reimers, N. and Gurevych, I. (2019) 'Sentence-BERT: Sentence embeddings using Siamese BERT-networks', *Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing (EMNLP)*, pp. 3982-3992.

Ren, T., Ke, C., Fan, Y., Jing, Y., He, Z., Zhang, K. and Wang, X.S. (2025) 'REDSQL: The power of constraints in natural language to SQL translation', *Proceedings of the VLDB Endowment*, 18(9), pp. 2097-2110.

Schierman, J.D., DeVore, M., Richards, N.D., Gandhi, N., Cooper, J., Horneman, K.R. et al. (2015) *Runtime assurance framework development for highly adaptive flight control systems*. Air Force Research Laboratory Report AFRL-RQ-WP-TR-2016-0001.

Schick, T., Dwivedi-Yu, J., Dessì, R., Raileanu, R., Lomeli, M., Zettlemoyer, L. et al. (2023) 'Toolformer: Language models can teach themselves to use tools', *arXiv preprint*, arXiv:2302.04761.

Shazeer, N., Mirhoseini, A., Maziarz, K., Davis, A., Le, Q., Hinton, G. and Dean, J. (2017) 'Outrageously large neural networks: The sparsely-gated mixture-of-experts layer', *arXiv preprint*, arXiv:1701.06538.

Wang, F., Ding, L., Rao, J., Liu, Y., Shen, L. and Bing, L. (2025) 'A comprehensive survey of small language models in the era of large language models', *ACM Computing Surveys*, 57(8).

Wooldridge, M. (2009) *An introduction to multiagent systems*. 2nd edn. Chichester: Wiley.

Wu, Q., Bansal, G., Zhang, J., Wu, Y., Li, B., Zhu, E. et al. (2023) 'AutoGen: Enabling next-gen LLM applications via multi-agent conversation', *arXiv preprint*, arXiv:2308.08155.

Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K. and Cao, Y. (2022) 'ReAct: Synergizing reasoning and acting in language models', *arXiv preprint*, arXiv:2210.03629.

Zhang, Y., Li, Y., Cui, L., Cai, D., Liu, L., Fu, T. et al. (2023) 'Siren's song in the AI ocean: A survey on hallucination in large language models', *arXiv preprint*, arXiv:2309.01219.

Zhipu AI (2025) 'GLM-4.7: Advancing the coding capability'. Available at: https://z.ai/blog/glm-4.7 (Accessed: 22 December 2025). Technical foundation: GLM-4.5 Team, arXiv:2508.06471.
---

## Appendix A: Tool Inventory

### ENTRY Agent Tools

| Tool | Purpose |
|------|---------|
| `search_employee` | Get all employees/directors for expense claim payer lookup |
| `search_account` | Get full Chart of Accounts grouped by type |
| `get_bank_accounts` | Get bank/cash accounts for payment/receipt |
| `create_supplier` | Create new supplier before purchase invoice |
| `create_customer` | Create new customer before sales invoice |
| `create_expense_claim` | Record employee reimbursement |
| `create_purchase_invoice` | Record bill from supplier |
| `create_sales_invoice` | Record bill to customer |
| `create_payment` | Record money out (direct or invoice payment) |
| `create_receipt` | Record money in (direct or invoice receipt) |
| `create_journal_entry` | Manual adjusting entries |
| `create_transfer` | Inter-account transfers |
| `extract_fields_from_ocr` | Parse vendor, amount, date from OCR text |

### DATA Agent Tools

| Tool | Purpose |
|------|---------|
| `get_chart_of_accounts` | Full account listing |
| `get_suppliers` | Supplier master data |
| `get_customers` | Customer master data |
| `get_employees` | Employee master data |
| `get_bank_accounts` | Bank/cash account listing |
| `get_tax_codes` | Tax code configuration |
| `get_projects` | Project tracking |
| `get_current_context` | Current date, timezone, company info |

---

## Appendix B: Sample Interaction

**User:** "I have a receipt from Uber for $45.50 on January 15, paid by the director"

**System Flow:**
```
1. SUPERVISOR: Detects "receipt" + "paid by" → Routes to ENTRY

2. ENTRY Agent:
   Step 1: search_employee("director")
   Result: [{"key": "abc-123", "name": "John Director"}]
   
   Step 2: search_account("transportation")
   Result: {expense_accounts: [{"key": "xyz-456", "name": "Local taxi or uber"}]}
   
   Step 3: create_expense_claim(
     payer_key="abc-123",
     date="2025-01-15",
     description="Uber ride",
     account_key="xyz-456",
     amount=45.50,
     payee="Uber"
   )
   Result: "Successfully created expense claim. Key: def-789"

3. Response: "Created expense claim for $45.50 (Uber) on Jan 15, 
              charged to Local taxi or uber, reimbursable to John Director."
```
