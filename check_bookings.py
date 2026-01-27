#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Check if demo bookings were saved to database"""

from database import engine
from sqlalchemy import text

print("=" * 80)
print("CHECKING APPOINTMENT TABLE FOR RECENT BOOKINGS")
print("=" * 80)

with engine.connect() as conn:
    print("\n[APPOINTMENTS] Recent Appointments (last 10):")
    result = conn.execute(text("""
        SELECT id, lead_id, appointment_time, status, created_at 
        FROM appointment 
        ORDER BY created_at DESC 
        LIMIT 10
    """))
    
    rows = result.fetchall()
    if rows:
        for row in rows:
            print(f"  ID: {row[0]} | Lead: {row[1]} | Time: {row[2]} | Status: {row[3]} | Created: {row[4]}")
    else:
        print("  [NO APPOINTMENTS FOUND]")
    
    print("\n[LEAD] Lead #2 Details (from recent call):")
    result = conn.execute(text("""
        SELECT id, name, phone, email, status 
        FROM lead 
        WHERE id = 2
    """))
    
    row = result.fetchone()
    if row:
        print(f"  ID: {row[0]} | Name: {row[1]} | Phone: {row[2]} | Email: {row[3]} | Status: {row[4]}")
    else:
        print("  [LEAD NOT FOUND]")
    
    print("\n[INTERACTION] Interaction #84 Details (from recent call):")
    result = conn.execute(text("""
        SELECT id, lead_id, type, content, transcript, timestamp
        FROM interaction
        WHERE id = 84
    """))
    
    row = result.fetchone()
    if row:
        transcript_preview = (row[4][:100] + "...") if row[4] else "None"
        print(f"  ID: {row[0]} | Lead: {row[1]} | Type: {row[2]} | Timestamp: {row[5]}")
        print(f"  Transcript: {transcript_preview}")
    else:
        print("  [INTERACTION NOT FOUND]")

print("\n" + "=" * 80)
