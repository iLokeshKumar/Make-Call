"""
One-off: reset a lead's ism_stage/status/qualification_status/next_action fields
and clear backfilled normalized_outcome stamps so the backfill can be re-run cleanly.

Usage:
    python reset_lead_state.py --lead 1 --apply
"""
import argparse
import sys

from sqlmodel import Session, select

from database import engine, rls_company_id
from models.models import Interaction, Lead


def run(lead_id: int, apply: bool) -> int:
    with Session(engine) as session:
        lead = session.get(Lead, lead_id)
        if not lead:
            print(f"Lead {lead_id} not found")
            return 1
        print(
            f"Before — company={lead.company_id} ism_stage={lead.ism_stage} status={lead.status} "
            f"qs={lead.qualification_status} next_action={lead.next_action}"
        )
        rls_company_id.set(lead.company_id)
        try:
            interactions = session.exec(
                select(Interaction).where(
                    Interaction.lead_id == lead_id,
                    Interaction.company_id == lead.company_id,
                )
            ).all()
            backfilled = [i for i in interactions if (i.metadata_json or {}).get("normalized_outcome")]
            print(f"Found {len(backfilled)} interactions with normalized_outcome — will clear to let backfill re-run")

            if not apply:
                print("DRY RUN — pass --apply to write")
                return 0

            lead.ism_stage = "new"
            lead.status = "new"
            lead.qualification_status = "unqualified"
            lead.next_action = None
            lead.next_action_due_at = None
            session.add(lead)

            for i in backfilled:
                meta = dict(i.metadata_json or {})
                meta.pop("normalized_outcome", None)
                meta.pop("backfilled", None)
                i.metadata_json = meta
                session.add(i)

            session.commit()
            session.refresh(lead)
            print(
                f"After  — ism_stage={lead.ism_stage} status={lead.status} "
                f"qs={lead.qualification_status} next_action={lead.next_action}"
            )
        finally:
            rls_company_id.set(None)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lead", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    return run(lead_id=args.lead, apply=args.apply)


if __name__ == "__main__":
    sys.exit(main())
