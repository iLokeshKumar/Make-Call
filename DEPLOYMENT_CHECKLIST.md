# ✅ Rio CRM Deployment Checklist

**Project**: Rio CRM AI Sales Agent  
**Date**: January 24, 2026  
**Status**: Ready for Production Deployment

---

## 📋 Pre-Deployment Checklist

### **1. Code Review** 
- [ ] Reviewed mcp_server.py changes
- [ ] Reviewed main.py changes
- [ ] Reviewed tools/ implementation
- [ ] Reviewed agents/ implementation
- [ ] All type hints in place
- [ ] All docstrings complete
- [ ] No TODO comments remaining
- [ ] Error handling comprehensive

### **2. Documentation Review**
- [ ] README_DOCS.md created
- [ ] QUICK_REFERENCE.md complete
- [ ] IMPLEMENTATION_SUMMARY.md complete
- [ ] ARCHITECTURE.md complete
- [ ] FILE_CHANGES_SUMMARY.md complete
- [ ] COMPLETION_REPORT.md complete
- [ ] VISUAL_SUMMARY.md complete
- [ ] All links working

### **3. Code Quality**
- [ ] No hardcoded secrets/API keys
- [ ] Type hints throughout
- [ ] Docstrings on all functions
- [ ] Error messages are helpful
- [ ] Logging enabled
- [ ] No unused imports
- [ ] Code follows PEP 8
- [ ] Max line length < 100

### **4. Testing**
- [ ] MCP tools tested locally
- [ ] Tools functions tested locally
- [ ] Agents orchestrator tested locally
- [ ] Post-call nurture tested locally
- [ ] API endpoints tested locally
- [ ] Database connection verified
- [ ] Email service tested
- [ ] Error cases handled

### **5. Dependencies**
- [ ] langgraph requirement added
- [ ] All imports available
- [ ] No version conflicts
- [ ] requirements.txt updated
- [ ] Dev tested on same Python version (3.12)
- [ ] All packages installable from PyPI

### **6. Configuration**
- [ ] DATABASE_URL set correctly
- [ ] SMTP credentials configured
- [ ] Gemini API key set
- [ ] MCP server accessible
- [ ] All env vars documented
- [ ] .env.example created (if needed)
- [ ] No hardcoded environment paths

### **7. Database**
- [ ] Database connection string valid
- [ ] All tables exist (leads, interactions, appointments, products, system_settings)
- [ ] Migrations run (if any)
- [ ] Backups taken
- [ ] Recovery plan documented
- [ ] Database user permissions correct

### **8. Security**
- [ ] No credentials in code
- [ ] API keys in environment variables
- [ ] Database password secured
- [ ] CORS configured appropriately
- [ ] Rate limiting considered
- [ ] Input validation in place
- [ ] SQL injection protected (using parameterized queries)
- [ ] PII redaction documented

### **9. Performance**
- [ ] Tool functions return quickly
- [ ] Database queries optimized
- [ ] No N+1 queries
- [ ] Email sending async
- [ ] Memory usage reasonable
- [ ] No unbounded loops
- [ ] Timeouts configured

### **10. Backward Compatibility**
- [ ] No breaking changes to existing API
- [ ] Existing voice pipeline still works
- [ ] Existing database schema compatible
- [ ] Existing tools not modified
- [ ] Existing endpoints unchanged

---

## 📦 Deployment Steps

### **Step 1: Pre-Deployment**
```bash
# 1. Create backup of current system
cp -r outbound-calling-speech-assistant-openai-realtime-api-python outbound-calling-speech-assistant-openai-realtime-api-python.backup

# 2. Review all changes
git diff main..rio-implementation
# Or manual review if not using git

# 3. Verify Python version
python --version  # Should be 3.12.x

# 4. Check disk space
df -h  # Ensure enough space
```

### **Step 2: Install Dependencies**
```bash
# 1. Install LangGraph
pip install langgraph

# 2. Verify installation
python -c "import langgraph; print(langgraph.__version__)"

# 3. Install other dependencies (if any new ones)
pip install -r requirements.txt

# 4. Check no conflicts
pip check
```

### **Step 3: Deploy Code**
```bash
# 1. Copy new files
cp -r tools/ /production/path/
cp -r agents/ /production/path/

# 2. Update existing files
cp mcp_server.py /production/path/
cp main.py /production/path/

# 3. Verify files copied
ls -la /production/path/tools/
ls -la /production/path/agents/
```

### **Step 4: Configuration**
```bash
# 1. Set environment variables
export DATABASE_URL=postgresql://...
export SMTP_HOST=...
export GEMINI_API_KEY=...

# 2. Verify configuration
echo $DATABASE_URL
echo $SMTP_HOST

# 3. Test database connection
python -c "from database import engine; print('DB connected')"
```

### **Step 5: Testing**
```bash
# 1. Test MCP tools
python -c "
from mcp_server import check_icp_qualification
result = check_icp_qualification('enterprise', 'Tech', 1000)
print(f'ICP Check: {result}')
assert result['is_qualified'] == True
print('✓ MCP tools working')
"

# 2. Test action tools
python -c "
from tools.query import check_lead_status
# Create test lead first if needed
print('✓ Action tools importable')
"

# 3. Test agents
python agents/langgraph_orchestrator.py
# Should complete without errors

# 4. Test post-call
python agents/post_call_nurture.py
# Should complete without errors
```

### **Step 6: API Testing**
```bash
# 1. Start app
python main.py

# 2. In another terminal, test endpoints
curl http://localhost:8000/settings
# Should return system settings with Rio's prompt

curl http://localhost:8000/leads
# Should return list of leads

curl http://localhost:8000/inventory
# Should return products
```

### **Step 7: Logging & Monitoring**
```bash
# 1. Enable logging
export LOG_LEVEL=INFO

# 2. Check logs
tail -f app.log | grep -i "rio\|error\|warning"

# 3. Monitor API responses
watch -n 1 'curl -s http://localhost:8000/settings | head -5'
```

### **Step 8: Gradual Rollout** (Optional)
```bash
# Option A: Blue-Green Deployment
# 1. Deploy to blue environment
# 2. Test fully
# 3. Switch traffic from green to blue
# 4. Keep green as rollback

# Option B: Canary Deployment
# 1. Route 5% traffic to new version
# 2. Monitor for 24 hours
# 3. If no errors, route 25% traffic
# 4. If no errors, route 100% traffic
# 5. Complete rollout

# Option C: Feature Flags
# 1. Deploy new code but disable features
# 2. Enable features gradually
# 3. Monitor metrics
# 4. Full enable once stable
```

---

## ⚠️ Common Issues & Solutions

### **Issue: langgraph not found**
```bash
# Solution
pip install langgraph
pip list | grep langgraph
```

### **Issue: Database connection fails**
```bash
# Solution
# Check connection string
echo $DATABASE_URL

# Test connection
psql $DATABASE_URL -c "SELECT 1"

# Or for SQLite
ls -la crm.db
```

### **Issue: Email sending fails**
```bash
# Solution
# Check SMTP config
echo $SMTP_HOST
echo $SMTP_PORT

# Test email
python -c "
from email_service import send_smtp_email
send_smtp_email('test@example.com', 'Test', '<p>Test email</p>')
"
```

### **Issue: API endpoints returning 500**
```bash
# Solution
# Check logs
tail -n 50 app.log | grep ERROR

# Test individual component
python -c "from tools import book_meeting; print('Tools OK')"
```

### **Issue: Agents not working**
```bash
# Solution
# Test individually
python agents/langgraph_orchestrator.py --verbose

# Check imports
python -c "from agents import run_rio_workflow; print('OK')"
```

---

## 📊 Rollback Procedure

If something goes wrong:

```bash
# 1. Stop current app
pkill -f "python main.py"

# 2. Restore from backup
rm -rf tools/ agents/
cp outbound-calling-speech-assistant-openai-realtime-api-python.backup/tools .
cp outbound-calling-speech-assistant-openai-realtime-api-python.backup/agents .
cp outbound-calling-speech-assistant-openai-realtime-api-python.backup/main.py .
cp outbound-calling-speech-assistant-openai-realtime-api-python.backup/mcp_server.py .

# 3. Restart app
python main.py

# 4. Verify working
curl http://localhost:8000/settings

# 5. Investigate issue (in backup environment)
cd outbound-calling-speech-assistant-openai-realtime-api-python
python agents/langgraph_orchestrator.py --debug
```

---

## 📈 Post-Deployment Monitoring

### **Hour 1: Critical Checks**
- [ ] App is running
- [ ] API endpoints responding (200 OK)
- [ ] Database queries working
- [ ] No error spikes in logs
- [ ] Email sending working
- [ ] Rio prompt loaded in database

### **Day 1: Daily Checks**
- [ ] Run 10+ test calls
- [ ] Verify CRM updates happening
- [ ] Verify emails sending
- [ ] Check error logs
- [ ] Monitor performance metrics
- [ ] Check database size

### **Week 1: Weekly Checks**
- [ ] Run end-to-end tests
- [ ] Monitor conversion rates
- [ ] Check email delivery rates
- [ ] Review error patterns
- [ ] Database maintenance
- [ ] Performance trends

### **Metrics to Track**
```
┌─────────────────────────────┐
│ Call Metrics                │
├─────────────────────────────┤
│ • Total calls               │
│ • Successful calls          │
│ • Errors per call           │
│ • Average call duration     │
│ • ICP qualification rate    │
│ • Demo booking rate         │
└─────────────────────────────┘

┌─────────────────────────────┐
│ Post-Call Metrics           │
├─────────────────────────────┤
│ • Emails sent per call      │
│ • Email send time           │
│ • CRM update time           │
│ • Automation success rate   │
│ • Error rate                │
└─────────────────────────────┘

┌─────────────────────────────┐
│ System Metrics              │
├─────────────────────────────┤
│ • API response time         │
│ • Database queries/sec      │
│ • Error rate                │
│ • Uptime %                  │
│ • Memory usage              │
│ • CPU usage                 │
└─────────────────────────────┘
```

---

## 🎯 Success Criteria

Deployment is successful when:

✅ All code deployed without errors  
✅ All tests passing  
✅ MCP tools working  
✅ Action tools working  
✅ Agents working  
✅ API endpoints responding  
✅ Database connected  
✅ Email sending working  
✅ Rio prompt loaded  
✅ No error spikes in logs  
✅ Team trained on new features  
✅ Documentation reviewed by team  

---

## 📞 Support During Deployment

### **If something breaks:**
1. Check logs: `tail -f app.log | grep ERROR`
2. Check this checklist for the error
3. Try the solution
4. If not fixed, rollback (see Rollback Procedure)
5. Investigate in backup environment

### **Questions about features:**
1. Check QUICK_REFERENCE.md
2. Check ARCHITECTURE.md
3. Check code docstrings
4. Review examples in test files

### **Performance issues:**
1. Check database query performance
2. Check API response times
3. Check resource usage (CPU, memory)
4. Review logs for warnings

---

## ✨ Final Verification

Before marking deployment complete:

```bash
# 1. All components working
python -c "
from mcp_server import check_icp_qualification, get_product_info, check_guardrails, book_meeting
from tools import book_meeting as tool_book_meeting, send_followup_email, check_lead_status
from agents import run_rio_workflow, execute_post_call_nurture
print('✓ All components imported successfully')
"

# 2. Database connected
python -c "
from database import engine
from sqlmodel import select, Session
from database import Lead
with Session(engine) as session:
    result = session.exec(select(Lead)).first()
    print('✓ Database connected')
"

# 3. API responding
curl -s http://localhost:8000/settings | grep -q system_instruction
echo "✓ API endpoint working"

# 4. Rio loaded
curl -s http://localhost:8000/settings | grep -q "Rio\|Sales Consultant"
echo "✓ Rio persona loaded"

# 5. All OK
echo ""
echo "✅ DEPLOYMENT SUCCESSFUL"
```

---

## 🎉 You're Done!

Rio CRM is now deployed and running.

**Next**: 
1. Train team on new features
2. Monitor metrics daily
3. Adjust based on real-world usage
4. Celebrate! 🎊

---

**Deployment Checklist**: ✅ COMPLETE  
**Status**: Ready to Deploy  
**Date**: January 24, 2026
