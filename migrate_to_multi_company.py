"""
Migration script to add multi-company support.
Run this after updating models.py to add company_id fields.
"""

import os
import sys
from pathlib import Path

# Add the backend directory to the path
backend_dir = Path(__file__).parent / "backend"
sys.path.insert(0, str(backend_dir))

from sqlmodel import SQLModel, create_engine, Session, select
from models.models import Company, User, Lead, Interaction, LatencyLog
from database import engine

def create_companies():
    """Create sample companies"""
    with Session(engine) as session:
        # Check if companies already exist
        existing = session.exec(select(Company)).first()
        if existing:
            print("Companies already exist, skipping creation")
            return

        # Create sample companies
        companies = [
            Company(
                name="Demo Company",
                domain="demo.example.com",
                website="https://demo.example.com",
                primary_color="#6366f1",
                subscription_tier="starter",
                max_users=5,
                features_enabled="leads,crm,calls"
            ),
            Company(
                name="Acme Corp",
                domain="acme.com",
                website="https://acme.com",
                primary_color="#10b981",
                subscription_tier="pro",
                max_users=25,
                features_enabled="leads,crm,calls,analytics"
            )
        ]

        for company in companies:
            session.add(company)
        session.commit()

        print(f"Created {len(companies)} companies")

def migrate_users():
    """Assign existing users to companies"""
    with Session(engine) as session:
        # Get the first company for existing users
        company = session.exec(select(Company).limit(1)).first()
        if not company:
            print("No companies found, create companies first")
            return

        # Update all users to have company_id
        users = session.exec(select(User)).all()
        for user in users:
            if not hasattr(user, 'company_id') or user.company_id is None:
                user.company_id = company.id
                session.add(user)

        session.commit()
        print(f"Assigned {len(users)} users to company {company.name}")

def migrate_leads():
    """Assign existing leads to companies"""
    with Session(engine) as session:
        # Get users and their company_ids
        user_companies = session.exec(select(User.id, User.company_id)).all()
        user_company_map = {user_id: company_id for user_id, company_id in user_companies}

        # Update leads based on created_by user
        leads = session.exec(select(Lead)).all()
        for lead in leads:
            if not hasattr(lead, 'company_id') or lead.company_id is None:
                # Try to find the user who created this lead
                creator_username = lead.created_by
                creator = session.exec(select(User).where(User.username == creator_username)).first()
                if creator and creator.company_id:
                    lead.company_id = creator.company_id
                else:
                    # Fallback to first company
                    company = session.exec(select(Company).limit(1)).first()
                    if company:
                        lead.company_id = company.id
                session.add(lead)

        session.commit()
        print(f"Assigned {len(leads)} leads to companies")

def migrate_interactions():
    """Assign existing interactions to companies"""
    with Session(engine) as session:
        # Get users and their company_ids
        user_companies = session.exec(select(User.id, User.company_id)).all()
        user_company_map = {user_id: company_id for user_id, company_id in user_companies}

        # Update interactions based on user_id
        interactions = session.exec(select(Interaction)).all()
        for interaction in interactions:
            if not hasattr(interaction, 'company_id') or interaction.company_id is None:
                if interaction.user_id and interaction.user_id in user_company_map:
                    interaction.company_id = user_company_map[interaction.user_id]
                else:
                    # Fallback to first company
                    company = session.exec(select(Company).limit(1)).first()
                    if company:
                        interaction.company_id = company.id
                session.add(interaction)

        session.commit()
        print(f"Assigned {len(interactions)} interactions to companies")

def migrate_latency_logs():
    """Assign existing latency logs to companies"""
    with Session(engine) as session:
        # Get users and their company_ids
        user_companies = session.exec(select(User.id, User.company_id)).all()
        user_company_map = {user_id: company_id for user_id, company_id in user_companies}

        # Update latency logs based on user_id
        logs = session.exec(select(LatencyLog)).all()
        for log in logs:
            if not hasattr(log, 'company_id') or log.company_id is None:
                if log.user_id and log.user_id in user_company_map:
                    log.company_id = user_company_map[log.user_id]
                else:
                    # Fallback to first company
                    company = session.exec(select(Company).limit(1)).first()
                    if company:
                        log.company_id = company.id
                session.add(log)

        session.commit()
        print(f"Assigned {len(logs)} latency logs to companies")

def main():
    print("Starting multi-company migration...")

    # Create tables if they don't exist
    SQLModel.metadata.create_all(engine)
    print("Database tables created/updated")

    # Run migrations
    create_companies()
    migrate_users()
    migrate_leads()
    migrate_interactions()
    migrate_latency_logs()

    print("Multi-company migration completed!")

if __name__ == "__main__":
    main()