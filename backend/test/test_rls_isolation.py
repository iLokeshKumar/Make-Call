"""
Integration tests for Postgres Row-Level Security (RLS) tenant isolation.

These tests hit the real database to verify that:
  - Tenant A cannot see Tenant B's data
  - Unscoped sessions (admin/migrations) see all data
  - SET LOCAL resets properly across sessions (no pool leak)

Requires:
  - DATABASE_URL pointing to a Postgres instance with RLS policies applied
  - Run `python migrations/apply_rls.py --all` before running these tests

Skip automatically if DATABASE_URL is not set (CI without a DB).

NOTE: Postgres superusers bypass RLS even with FORCE ROW LEVEL SECURITY.
These tests create a temporary non-superuser role (`_rls_test_role`) and
use SET ROLE to simulate a real app connection. The role is dropped in
teardown.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_DB_URL = os.getenv("DATABASE_URL")
pytestmark = pytest.mark.skipif(not _DB_URL, reason="DATABASE_URL not set — skipping RLS integration tests")

_TEST_ROLE = "_rls_test_role"


# Module-scoped fixture: create test data + a non-superuser role

@pytest.fixture(scope="module")
def _db_setup():
    """
    1. Create a non-superuser role (so RLS actually applies).
    2. Create two companies, each with a lead and a product.
    3. Yield (company_a_id, company_b_id).
    4. Cleanup: delete test rows, drop role.
    """
    import psycopg2
    from database import engine, rls_company_id
    from sqlalchemy import text
    from sqlmodel import Session, select
    from models.models import Company, Lead, Product

    # Create non-superuser role via psycopg2 (DDL)
    raw_conn = psycopg2.connect(_DB_URL)
    raw_conn.autocommit = True
    cur = raw_conn.cursor()
    cur.execute(f"SELECT 1 FROM pg_roles WHERE rolname = '{_TEST_ROLE}'")
    if not cur.fetchone():
        cur.execute(f"CREATE ROLE {_TEST_ROLE} NOLOGIN")
    # Grant access to the public schema and all tables so the role can query
    cur.execute(f"GRANT USAGE ON SCHEMA public TO {_TEST_ROLE}")
    cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {_TEST_ROLE}")
    cur.close()
    raw_conn.close()

    # Insert test data as superuser (no RLS restriction)
    token = rls_company_id.set(None)
    with Session(engine) as session:
        co_a = Company(name="RLS Test Co A", slug="rls-test-a")
        co_b = Company(name="RLS Test Co B", slug="rls-test-b")
        session.add_all([co_a, co_b])
        session.flush()

        session.add_all([
            Lead(company_id=co_a.id, name="Alice Alpha", normalized_phone="+910000000001", source="rls_test"),
            Lead(company_id=co_b.id, name="Bob Beta", normalized_phone="+910000000002", source="rls_test"),
            Product(company_id=co_a.id, name="Widget A", sku="RLS-A-001"),
            Product(company_id=co_b.id, name="Widget B", sku="RLS-B-001"),
        ])
        session.commit()
        a_id, b_id = co_a.id, co_b.id
    rls_company_id.reset(token)

    yield a_id, b_id

    token = rls_company_id.set(None)
    with Session(engine) as session:
        for model in (Product, Lead):
            for row in session.exec(
                select(model).where(model.company_id.in_([a_id, b_id]))
            ).all():
                session.delete(row)
        for row in session.exec(
            select(Company).where(Company.id.in_([a_id, b_id]))
        ).all():
            session.delete(row)
        session.commit()
    rls_company_id.reset(token)

    raw_conn = psycopg2.connect(_DB_URL)
    raw_conn.autocommit = True
    cur = raw_conn.cursor()
    cur.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {_TEST_ROLE}")
    cur.execute(f"REVOKE USAGE ON SCHEMA public FROM {_TEST_ROLE}")
    cur.execute(f"DROP ROLE IF EXISTS {_TEST_ROLE}")
    cur.close()
    raw_conn.close()


@pytest.fixture
def company_ids(_db_setup):
    return _db_setup


# Helper: open a session scoped to a specific company_id with SET ROLE
def _scoped_session(cid: int | None, *, use_rls_role: bool = True):
    """
    Context manager that:
      1. Sets rls_company_id ContextVar
      2. Optionally does SET ROLE to a non-superuser so RLS applies
      3. Yields a Session
      4. Resets role and ContextVar
    """
    from contextlib import contextmanager
    from database import engine, rls_company_id
    from sqlalchemy import text
    from sqlmodel import Session

    @contextmanager
    def _ctx():
        token = rls_company_id.set(cid)
        try:
            with Session(engine) as session:
                if use_rls_role:
                    session.execute(text(f"SET ROLE {_TEST_ROLE}"))
                yield session
                if use_rls_role:
                    session.execute(text("RESET ROLE"))
        finally:
            rls_company_id.reset(token)

    return _ctx()


class TestLeadIsolation:
    """Leads table — the most critical tenant-scoped entity."""

    def test_company_a_sees_only_own_leads(self, company_ids):
        a_id, b_id = company_ids
        from sqlmodel import select
        from models.models import Lead

        with _scoped_session(a_id) as session:
            leads = session.exec(select(Lead)).all()
            company_ids_found = {l.company_id for l in leads}
            assert a_id in company_ids_found, f"Company A has no leads, found: {company_ids_found}"
            assert b_id not in company_ids_found, "Company A session saw Company B leads"

    def test_company_b_sees_only_own_leads(self, company_ids):
        a_id, b_id = company_ids
        from sqlmodel import select
        from models.models import Lead

        with _scoped_session(b_id) as session:
            leads = session.exec(select(Lead)).all()
            company_ids_found = {l.company_id for l in leads}
            assert b_id in company_ids_found, f"Company B has no leads, found: {company_ids_found}"
            assert a_id not in company_ids_found, "Company B session saw Company A leads"

    def test_unscoped_superuser_sees_both(self, company_ids):
        """Superuser with no RLS role — should see all rows (admin bypass)."""
        a_id, b_id = company_ids
        from sqlmodel import select
        from models.models import Lead

        with _scoped_session(None, use_rls_role=False) as session:
            leads = session.exec(
                select(Lead).where(Lead.company_id.in_([a_id, b_id]))
            ).all()
            company_ids_found = {l.company_id for l in leads}
            assert a_id in company_ids_found, "Superuser missing Company A leads"
            assert b_id in company_ids_found, "Superuser missing Company B leads"

    def test_null_context_non_superuser_sees_all(self, company_ids):
        """Non-superuser with NULL context — policy says bypass (for webhooks/health)."""
        a_id, b_id = company_ids
        from sqlmodel import select
        from models.models import Lead

        with _scoped_session(None, use_rls_role=True) as session:
            leads = session.exec(
                select(Lead).where(Lead.company_id.in_([a_id, b_id]))
            ).all()
            company_ids_found = {l.company_id for l in leads}
            assert a_id in company_ids_found, "NULL context should bypass RLS"
            assert b_id in company_ids_found, "NULL context should bypass RLS"


class TestProductIsolation:
    """Products table — verifies RLS applies across multiple entity types."""

    def test_company_a_sees_only_own_products(self, company_ids):
        a_id, _ = company_ids
        from sqlmodel import select
        from models.models import Product

        with _scoped_session(a_id) as session:
            products = session.exec(select(Product)).all()
            for p in products:
                assert p.company_id == a_id, f"Product {p.id} belongs to company {p.company_id}, expected {a_id}"

    def test_company_b_sees_only_own_products(self, company_ids):
        _, b_id = company_ids
        from sqlmodel import select
        from models.models import Product

        with _scoped_session(b_id) as session:
            products = session.exec(select(Product)).all()
            for p in products:
                assert p.company_id == b_id, f"Product {p.id} belongs to company {p.company_id}, expected {b_id}"


class TestCrossTenantCount:
    """Verify row counts are correctly filtered even with WHERE on both IDs."""

    def test_scoped_count_less_than_unscoped(self, company_ids):
        a_id, b_id = company_ids
        from sqlalchemy import func
        from sqlmodel import select
        from models.models import Lead

        # Unscoped superuser sees both
        with _scoped_session(None, use_rls_role=False) as session:
            total = session.exec(
                select(func.count(Lead.id)).where(Lead.company_id.in_([a_id, b_id]))
            ).one()

        # Scoped to A — RLS filters out B even though WHERE includes both
        with _scoped_session(a_id) as session:
            a_count = session.exec(
                select(func.count(Lead.id)).where(Lead.company_id.in_([a_id, b_id]))
            ).one()

        assert a_count < total, (
            f"Scoped count ({a_count}) should be less than unscoped ({total}). "
            f"RLS may not be filtering — check FORCE ROW LEVEL SECURITY and role."
        )


class TestContextVarReset:
    """Verify ContextVar reset doesn't leak between scopes."""

    def test_switching_tenants_changes_visibility(self, company_ids):
        a_id, b_id = company_ids
        from sqlmodel import select
        from models.models import Lead

        with _scoped_session(a_id) as session:
            a_leads = session.exec(select(Lead).where(Lead.source == "rls_test")).all()
            a_names = {l.name for l in a_leads}

        with _scoped_session(b_id) as session:
            b_leads = session.exec(select(Lead).where(Lead.source == "rls_test")).all()
            b_names = {l.name for l in b_leads}

        assert "Alice Alpha" in a_names, f"Expected Alice in A, got {a_names}"
        assert "Bob Beta" not in a_names, "Company A leaked Company B lead"
        assert "Bob Beta" in b_names, f"Expected Bob in B, got {b_names}"
        assert "Alice Alpha" not in b_names, "Company B leaked Company A lead"


class TestSetLocalTransactionScope:
    """Verify SET LOCAL resets after commit/rollback (no connection pool leak)."""

    def test_rls_resets_after_session_close(self, company_ids):
        a_id, b_id = company_ids
        from database import engine, rls_company_id
        from sqlalchemy import text
        from sqlmodel import Session, select
        from models.models import Lead

        # scoped to A
        token1 = rls_company_id.set(a_id)
        with Session(engine) as s1:
            s1.execute(text(f"SET ROLE {_TEST_ROLE}"))
            leads_a = s1.exec(select(Lead).where(Lead.source == "rls_test")).all()
            s1.execute(text("RESET ROLE"))
        rls_company_id.reset(token1)

        # scoped to B — if SET LOCAL leaked, we'd still see A's data
        token2 = rls_company_id.set(b_id)
        with Session(engine) as s2:
            s2.execute(text(f"SET ROLE {_TEST_ROLE}"))
            leads_b = s2.exec(select(Lead).where(Lead.source == "rls_test")).all()
            s2.execute(text("RESET ROLE"))
        rls_company_id.reset(token2)

        a_cids = {l.company_id for l in leads_a}
        b_cids = {l.company_id for l in leads_b}

        assert a_id in a_cids, f"Session 1 should see Company A, got {a_cids}"
        assert b_id not in a_cids, "SET LOCAL leaked from session 1 to session 2"
        assert b_id in b_cids, f"Session 2 should see Company B, got {b_cids}"
        assert a_id not in b_cids, "SET LOCAL leaked from session 2 to session 1"
