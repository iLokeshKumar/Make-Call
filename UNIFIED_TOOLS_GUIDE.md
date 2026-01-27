# 🎯 Unified MCP Tools for Gemini & Mistral

## ✅ What Changed

Created a **unified tool adapter** so both Gemini and Mistral use the same MCP tools.

### New File: `tool_adapter.py`
- **`get_mistral_tools()`** - Converts MCP tools to Mistral function calling format
- **`execute_mcp_tool()`** - Executes MCP tools regardless of which LLM calls them
- **TOOL_DESCRIPTIONS** - Documentation for each tool

### Updated: `main.py`
- Imported `tool_adapter` module
- Mistral pipeline now uses `get_mistral_tools()` instead of old tool definitions
- `run_tool()` function now calls unified `execute_mcp_tool()`
- Both Gemini & Mistral route through same tool executor

---

## 📊 Architecture

```
┌─────────────────────────────────────────────┐
│         Voice Call (Twilio)                 │
└────────────┬────────────────────────────────┘
             │
             ├─────────────────┬──────────────┐
             │                 │              │
      ┌──────▼──────┐   ┌──────▼──────┐   ┌──▼─────────┐
      │   Gemini    │   │   Mistral   │   │  Future    │
      │  (Primary)  │   │(Alternative)│   │   LLMs     │
      └──────┬──────┘   └──────┬──────┘   └──┬─────────┘
             │                 │              │
             └─────────────────┼──────────────┘
                               │
                    ┌──────────▼──────────┐
                    │  tool_adapter.py    │
                    │ (Unified Executor)  │
                    └──────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
         ┌──────▼────────┐  ┌──▼──────────┐ ┌─▼──────────────┐
         │ICP Check      │  │Get Product  │ │Check Guardrails│
         │(Qualification)│  │Info (Price) │ │(Discount Limit)│
         └───────────────┘  └─────────────┘ └────────────────┘
                │
         ┌──────▼────────┐
         │ Book Meeting  │
         │(Demo/Follow-up)
         └───────────────┘
```

---

## 🛠️ Tools Available (Both LLMs)

### 1. **check_icp_qualification**
- **What**: Validate if a company is ideal customer (ICP)
- **Inputs**: company_size, industry, employee_count
- **Output**: qualification score, priority, recommendation

### 2. **get_product_info**
- **What**: Fetch accurate product details from database
- **Inputs**: product_name
- **Output**: price, stock, features, lead_time_days
- **Why**: Prevents AI hallucination on pricing

### 3. **check_guardrails**
- **What**: Check discount limits against business rules
- **Inputs**: requested_discount_percent
- **Output**: approved/denied, max_allowed, needs_manager_approval

### 4. **book_meeting**
- **What**: Schedule demo, meeting, or follow-up
- **Inputs**: lead_id, proposed_time, meeting_type
- **Output**: confirmation, appointment_id, calendar_url

---

## 🔄 How It Works

### When Gemini calls a tool:
```
Gemini → MCP Protocol → tool_adapter.execute_mcp_tool() → Result
```

### When Mistral calls a tool:
```
Mistral → Function Calling → tool_adapter.execute_mcp_tool() → Result
```

### Both converge to same executor:
```python
async def execute_mcp_tool(tool_name, arguments):
    if tool_name == "check_icp_qualification":
        return check_icp_qualification(...)
    elif tool_name == "get_product_info":
        return get_product_info(...)
    # etc...
```

---

## ✨ Benefits

✅ **No Duplicated Code** - Single tool implementation  
✅ **Easy to Add LLMs** - Just add format converter, reuse executor  
✅ **Consistent Behavior** - Both LLMs get same results  
✅ **Type Safe** - All tools have proper type hints  
✅ **Well Documented** - Each tool has description & usage guide  
✅ **Error Handling** - Unified error handling for all LLMs  

---

## 🚀 Usage

### In Mistral Pipeline:
```python
# Get tools in Mistral format
mistral_tools = get_mistral_tools()

# Call tool
result = await execute_mcp_tool("check_icp_qualification", {
    "company_size": "Enterprise",
    "industry": "Tech",
    "employee_count": 5000
})
```

### In Gemini Pipeline:
```python
# Gemini uses MCP protocol natively
# But can also use the same executor if needed
result = await execute_mcp_tool("get_product_info", {
    "product_name": "Pro Server 3000"
})
```

---

## 📋 Tool Mapping Reference

| Old Mistral Tools | New Unified Tools |
|---|---|
| check_inventory | get_product_info |
| query_knowledge_base | *(moved to agents)* |
| update_lead_tool | *(moved to agents)* |
| send_email_tool | *(moved to agents)* |
| book_demo_tool | book_meeting |
| query_mcp_resource | *(moved to agents)* |

**Note**: Post-call automation (CRM updates, emails, summaries) handled by agents layer, not LLM tools.

---

## ✅ Testing

To verify everything works:

```bash
# Test 1: Import adapter
python -c "from tool_adapter import get_mistral_tools; print('✓')"

# Test 2: Check syntax
python -m py_compile tool_adapter.py

# Test 3: Load main app
python -c "from main import app; print('✓ Ready for voice calls')"
```

---

## 🎊 Result

Both Gemini and Mistral now use the **same professional tool set**:
- ✅ ICP qualification
- ✅ Product information (no hallucination)
- ✅ Guardrails enforcement
- ✅ Meeting booking

**Status**: Ready for production deployment! 🚀
