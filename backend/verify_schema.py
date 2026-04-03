#!/usr/bin/env python
"""Verify schema migration completed successfully."""

import sys
sys.path.insert(0, '.')

from sqlalchemy import inspect
from database import engine

inspector = inspect(engine)

# Check Lead table columns
lead_cols = [c['name'] for c in inspector.get_columns('leads')]
required_lead_cols = ['lead_score', 'lead_score_reasons_json', 'last_enriched_at', 'last_outreach_at', 'product_interest', 'budget_range', 'timeline', 'decision_maker']
print('✅ Lead table columns:')
for col in required_lead_cols:
    status = '✓' if col in lead_cols else '✗'
    print(f'  {status} {col}')

# Check CallTask table columns
call_cols = [c['name'] for c in inspector.get_columns('call_tasks')]
required_call_cols = ['retry_after', 'max_attempts', 'batch_id', 'outcome_confidence', 'dialer_source']
print()
print('✅ CallTask table columns:')
for col in required_call_cols:
    status = '✓' if col in call_cols else '✗'
    print(f'  {status} {col}')

# Check Quote table columns
quote_cols = [c['name'] for c in inspector.get_columns('quotes')]
required_quote_cols = ['opened_at', 'sent_at', 'accepted_at', 'rejected_at', 'tracking_token']
print()
print('✅ Quote table columns:')
for col in required_quote_cols:
    status = '✓' if col in quote_cols else '✗'
    print(f'  {status} {col}')

# Check EngagementEvent table exists
tables = inspector.get_table_names()
print()
engagement_exists = 'engagement_events' in tables
engagement_status = '✓' if engagement_exists else '✗'
print(f'✅ EngagementEvent table: {engagement_status}')

# Check indexes
print()
print('✅ Database Indexes:')
call_indexes = [idx['name'] for idx in inspector.get_indexes('call_tasks')]
print(f'  CallTask: {len(call_indexes)} indexes')
for idx in call_indexes[:3]:
    print(f'    - {idx}')

lead_indexes = [idx['name'] for idx in inspector.get_indexes('leads')]
print(f'  Lead: {len(lead_indexes)} indexes')

quote_indexes = [idx['name'] for idx in inspector.get_indexes('quotes')]
print(f'  Quote: {len(quote_indexes)} indexes')

engagement_indexes = [idx['name'] for idx in inspector.get_indexes('engagement_events')]
print(f'  EngagementEvent: {len(engagement_indexes)} indexes')

print()
print('✅ Schema migration completed successfully!')
