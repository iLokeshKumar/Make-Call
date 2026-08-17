"""
Workflow Service — runtime execution engine for WorkflowDefinition templates.

A workflow is a sequence of named steps defined in WorkflowDefinition.steps_json.
Each step is a dict with at minimum a "key" field. Optional fields:
  - "delay_seconds": int — how long to wait before the step becomes runnable.

Lifecycle:
  start_workflow()  → creates WorkflowInstance (status=running) + first WorkflowStep
  advance_workflow() → marks current step done, creates next step (or completes instance)
  complete_step()   → marks step done/failed; updates instance.current_step_index
  get_instance()    → fetch a single WorkflowInstance
  list_running_workflows() → all running instances (optionally filtered by entity_type)

The automation worker is expected to:
  1. Query for pending WorkflowStep rows where run_after <= now().
  2. Execute the step's logic.
  3. Call complete_step() with the result.
  4. Call advance_workflow() to move to the next step.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from sqlmodel import Session, select

from models.models import WorkflowDefinition, WorkflowInstance, WorkflowStep, utc_now

logger = logging.getLogger(__name__)


def _get_next_step_delay(step_def: dict) -> int:
    """
    Extract the delay_seconds from a step definition dict.
    Returns 0 if not specified or not a valid integer.
    """
    try:
        return int(step_def.get("delay_seconds", 0) or 0)
    except (TypeError, ValueError):
        return 0


def start_workflow(
    session: Session,
    company_id: int,
    definition_key: str,
    entity_type: str,
    entity_id: int,
    context_json: dict | None = None,
) -> WorkflowInstance:
    """
    Start a new workflow instance for a domain entity.

    Looks up the WorkflowDefinition by company_id + key, creates a
    WorkflowInstance at step index 0 (status=running), then creates the
    first WorkflowStep record.

    Parameters
    ----------
    definition_key : The workflow template key, e.g. "post_sale_onboarding".
    entity_type    : Domain object type, e.g. "order", "lead", "ticket".
    entity_id      : Primary key of the entity.
    context_json   : Optional extra data to store on the instance.

    Raises
    ------
    ValueError if the WorkflowDefinition is not found or has no steps.
    """
    definition = session.exec(
        select(WorkflowDefinition).where(
            WorkflowDefinition.company_id == company_id,
            WorkflowDefinition.key == definition_key,
            WorkflowDefinition.is_active == True,
        )
    ).first()

    if definition is None:
        raise ValueError(
            f"WorkflowDefinition not found: company_id={company_id} key={definition_key}"
        )

    steps_def: list = definition.steps_json or []
    if not steps_def:
        raise ValueError(
            f"WorkflowDefinition '{definition_key}' has no steps defined."
        )

    now = utc_now()
    instance = WorkflowInstance(
        company_id=company_id,
        definition_id=definition.id,
        entity_type=entity_type,
        entity_id=entity_id,
        status="running",
        current_step_index=0,
        context_json=context_json or {},
        started_at=now,
    )
    session.add(instance)
    session.flush()  # obtain instance.id before creating the first step

    first_step_def = steps_def[0]
    delay = _get_next_step_delay(first_step_def)
    first_step = WorkflowStep(
        company_id=company_id,
        instance_id=instance.id,
        step_index=0,
        step_key=first_step_def.get("key", "step_0"),
        status="pending",
        input_json=first_step_def,
        run_after=now + timedelta(seconds=delay),
    )
    session.add(first_step)
    session.commit()
    session.refresh(instance)
    logger.info(
        "[WorkflowService] Started workflow '%s' instance=%s entity=%s:%s",
        definition_key, instance.id, entity_type, entity_id,
    )
    return instance


def advance_workflow(
    session: Session,
    company_id: int,
    instance_id: int,
) -> WorkflowInstance | None:
    """
    Advance the workflow to the next step.

    Finds the WorkflowInstance and its associated WorkflowDefinition. Marks
    the current step as done (if not already), then:
    - If there are more steps: creates the next WorkflowStep and increments
      current_step_index.
    - If no more steps: marks the instance as completed.

    Returns the updated WorkflowInstance, or None if not found.
    """
    instance = session.exec(
        select(WorkflowInstance).where(
            WorkflowInstance.id == instance_id,
            WorkflowInstance.company_id == company_id,
        )
    ).first()

    if instance is None:
        logger.warning("[WorkflowService] advance_workflow: instance %s not found", instance_id)
        return None

    if instance.status != "running":
        logger.warning(
            "[WorkflowService] advance_workflow: instance %s is not running (status=%s)",
            instance_id, instance.status,
        )
        return instance

    definition = session.get(WorkflowDefinition, instance.definition_id)
    if definition is None:
        logger.error(
            "[WorkflowService] advance_workflow: definition %s not found for instance %s",
            instance.definition_id, instance_id,
        )
        return instance

    steps_def: list = definition.steps_json or []
    next_index = instance.current_step_index + 1
    now = utc_now()

    if next_index >= len(steps_def):
        # No more steps — complete the instance
        instance.status = "completed"
        instance.completed_at = now
        session.add(instance)
        session.commit()
        session.refresh(instance)
        logger.info(
            "[WorkflowService] Workflow instance=%s completed (all %d steps done)",
            instance_id, len(steps_def),
        )
        return instance

    # Create the next step
    next_step_def = steps_def[next_index]
    delay = _get_next_step_delay(next_step_def)
    next_step = WorkflowStep(
        company_id=company_id,
        instance_id=instance_id,
        step_index=next_index,
        step_key=next_step_def.get("key", f"step_{next_index}"),
        status="pending",
        input_json=next_step_def,
        run_after=now + timedelta(seconds=delay),
    )
    session.add(next_step)

    instance.current_step_index = next_index
    session.add(instance)
    session.commit()
    session.refresh(instance)
    logger.info(
        "[WorkflowService] Workflow instance=%s advanced to step_index=%s key=%s",
        instance_id, next_index, next_step_def.get("key"),
    )
    return instance


def complete_step(
    session: Session,
    company_id: int,
    instance_id: int,
    step_index: int,
    output_json: dict | None = None,
    error: str | None = None,
) -> WorkflowStep:
    """
    Mark a workflow step as done or failed and update the instance's current index.

    Parameters
    ----------
    step_index  : The zero-based index of the step to complete.
    output_json : Result data from step execution.
    error       : If set, the step is marked "failed"; otherwise "done".

    Raises
    ------
    ValueError if the step is not found.
    """
    step = session.exec(
        select(WorkflowStep).where(
            WorkflowStep.instance_id == instance_id,
            WorkflowStep.step_index == step_index,
            WorkflowStep.company_id == company_id,
        )
    ).first()

    if step is None:
        raise ValueError(
            f"WorkflowStep not found: instance_id={instance_id} step_index={step_index}"
        )

    now = utc_now()
    step.status = "failed" if error else "done"
    step.output_json = output_json
    step.error = error
    step.completed_at = now
    session.add(step)

    # Update instance current index to reflect the completed step
    instance = session.exec(
        select(WorkflowInstance).where(
            WorkflowInstance.id == instance_id,
            WorkflowInstance.company_id == company_id,
        )
    ).first()
    if instance is not None:
        instance.current_step_index = step_index
        if error:
            instance.status = "failed"
            instance.error = error
            instance.completed_at = now
        session.add(instance)

    session.commit()
    session.refresh(step)
    logger.info(
        "[WorkflowService] Completed step instance=%s index=%s status=%s",
        instance_id, step_index, step.status,
    )
    return step


def get_instance(
    session: Session,
    company_id: int,
    instance_id: int,
) -> WorkflowInstance | None:
    """Fetch a WorkflowInstance by ID. Returns None if not found."""
    return session.exec(
        select(WorkflowInstance).where(
            WorkflowInstance.id == instance_id,
            WorkflowInstance.company_id == company_id,
        )
    ).first()


def list_running_workflows(
    session: Session,
    company_id: int,
    entity_type: str | None = None,
) -> list[WorkflowInstance]:
    """
    Return all running WorkflowInstances for a company.

    Parameters
    ----------
    entity_type : Optional filter by entity type (e.g. "order", "lead").
    """
    query = select(WorkflowInstance).where(
        WorkflowInstance.company_id == company_id,
        WorkflowInstance.status == "running",
    )
    if entity_type is not None:
        query = query.where(WorkflowInstance.entity_type == entity_type)

    return session.exec(query.order_by(WorkflowInstance.started_at.asc())).all()
