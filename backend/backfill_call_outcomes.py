"""
One-off backfill: replay apply_lead_only_outcome on historical completed call
interactions that were never post-processed (no normalized_outcome in metadata).

Strategy: per-lead, only the LATEST completed call drives stage/status. Older
calls get their metadata.normalized_outcome stamped (for traceability) but do
not affect lead state. This avoids the forward-only trap where an early
"not_interested" call locks a lead into closed_lost even though later calls
re-engaged the customer.

Safe to re-run — skips interactions already marked with normalized_outcome.

Usage:
    cd backend
    python backfill_call_outcomes.py                # dry run, all companies
    python backfill_call_outcomes.py --apply        # actually write
    python backfill_call_outcomes.py --apply --lead 1
"""
import argparse
import sys
from collections import defaultdict

from sqlmodel import Session, select

from database import engine, rls_company_id
from models.models import Interaction, User
from services.call.outcome_service import (
    apply_lead_only_outcome,
    normalize_call_outcome,
)


def find_candidates(session: Session, lead_id: int | None = None) -> list[Interaction]:
    query = select(Interaction).where(
        Interaction.type == "call",
        Interaction.status == "completed",
    )
    if lead_id is not None:
        query = query.where(Interaction.lead_id == lead_id)
    query = query.order_by(Interaction.started_at.asc())
    rows = session.exec(query).all()

    out: list[Interaction] = []
    for row in rows:
        meta = row.metadata_json or {}
        if meta.get("normalized_outcome"):
            continue
        if not row.lead_id:
            continue
        out.append(row)
    return out


def pick_actor(session: Session, company_id: int) -> User | None:
    return session.exec(
        select(User).where(User.company_id == company_id).order_by(User.id.asc())
    ).first()


def stamp_metadata(session: Session, interaction_id: int, raw_status: str, transcript: str | None) -> str:
    """Mark an interaction as classified without touching the lead."""
    inter = session.get(Interaction, interaction_id)
    if not inter:
        return ""
    outcome = normalize_call_outcome(raw_status, transcript, inter)
    inter.metadata_json = {
        **(inter.metadata_json or {}),
        "normalized_outcome": outcome,
        "provider_status": raw_status,
        "backfilled": True,
    }
    session.add(inter)
    return outcome


def run(apply: bool, lead_id: int | None) -> int:
    with Session(engine) as session:
        candidates = find_candidates(session, lead_id=lead_id)

    print(f"Found {len(candidates)} completed call interactions missing normalized_outcome")
    if not candidates:
        return 0

    by_lead: dict[tuple[int, int], list[Interaction]] = defaultdict(list)
    for c in candidates:
        by_lead[(c.company_id, c.lead_id)].append(c)

    companies: dict[int, list[tuple[int, list[Interaction]]]] = defaultdict(list)
    for (company_id, lead_id_key), rows in by_lead.items():
        rows_sorted = sorted(rows, key=lambda r: r.started_at)
        companies[company_id].append((lead_id_key, rows_sorted))

    total_leads = 0
    total_older_stamped = 0
    total_advanced = 0

    for company_id, leads in companies.items():
        print(f"\nCompany {company_id}: {len(leads)} leads to backfill")
        rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                actor = pick_actor(session, company_id)
                if not actor:
                    print(f"  SKIP — no user found in company {company_id}")
                    continue

                for lead_id_key, rows in leads:
                    latest = rows[-1]
                    older = rows[:-1]

                    raw_status = (latest.metadata_json or {}).get("provider_call_status") or "completed"
                    transcript = latest.transcript

                    if not apply:
                        print(
                            f"  [DRY] lead={lead_id_key} latest_interaction={latest.id} "
                            f"older_to_stamp={len(older)}"
                        )
                        total_leads += 1
                        total_older_stamped += len(older)
                        continue

                    for o in older:
                        o_raw = (o.metadata_json or {}).get("provider_call_status") or "completed"
                        stamp_metadata(session, o.id, o_raw, o.transcript)
                        total_older_stamped += 1

                    try:
                        result = apply_lead_only_outcome(
                            session=session,
                            company_id=company_id,
                            actor_user_id=actor.id,
                            lead_id=lead_id_key,
                            interaction_id=latest.id,
                            raw_status=raw_status,
                            transcript=transcript,
                        )
                        total_leads += 1
                        if result.get("stage_advanced"):
                            total_advanced += 1
                        print(
                            f"  lead={lead_id_key} latest={latest.id} older_stamped={len(older)} "
                            f"outcome={result.get('normalized_outcome')} "
                            f"stage={result.get('ism_stage')} advanced={result.get('stage_advanced')}"
                        )
                    except Exception as exc:
                        print(f"  ERROR lead={lead_id_key} latest={latest.id}: {exc}")

                if apply:
                    session.commit()
        finally:
            rls_company_id.set(None)

    print(
        f"\nSummary: leads={total_leads} older_stamped={total_older_stamped} "
        f"advanced={total_advanced} apply={apply}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Write changes (default: dry run)")
    parser.add_argument("--lead", type=int, default=None, help="Scope to one lead_id")
    args = parser.parse_args()
    return run(apply=args.apply, lead_id=args.lead)


if __name__ == "__main__":
    sys.exit(main())
