import json
import logging
import os
from pathlib import Path
from typing import Optional

from sqlmodel import Session, select

from models.models import AgentTemplate, VoiceAgent, VoiceAgentRuntimeConfig, VoiceAgentPromptVersion, User, utc_now

logger = logging.getLogger(__name__)


def list_templates(session: Session, category: Optional[str] = None, industry: Optional[str] = None) -> list:
    q = select(AgentTemplate).where(AgentTemplate.is_active == True)
    if category:
        q = q.where(AgentTemplate.category == category)
    if industry:
        q = q.where(AgentTemplate.industry == industry)
    return session.exec(q.order_by(AgentTemplate.category, AgentTemplate.name)).all()


def get_template(session: Session, template_id: int) -> Optional[AgentTemplate]:
    return session.get(AgentTemplate, template_id)


def get_template_by_key(session: Session, key: str) -> Optional[AgentTemplate]:
    return session.exec(
        select(AgentTemplate).where(AgentTemplate.key == key)
    ).first()


def create_template(session: Session, data) -> AgentTemplate:
    existing = get_template_by_key(session, data.key)
    if existing:
        raise ValueError(f"Template with key '{data.key}' already exists")

    tmpl = AgentTemplate(
        key=data.key,
        name=data.name,
        description=data.description,
        category=data.category,
        industry=data.industry,
        is_public=data.is_public,
        config_json=data.config_json,
        system_prompt=data.system_prompt,
        instructions=data.instructions,
        tags=data.tags,
    )
    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    logger.info("[AgentTemplate] Created %r (%s)", data.key, data.category)
    return tmpl


def update_template(session: Session, template_id: int, data) -> Optional[AgentTemplate]:
    tmpl = get_template(session, template_id)
    if not tmpl:
        return None
    for field in ("name", "description", "category", "industry", "is_public", "is_active",
                  "config_json", "system_prompt", "instructions", "tags"):
        val = getattr(data, field, None)
        if val is not None:
            setattr(tmpl, field, val)
    tmpl.updated_at = utc_now()
    session.add(tmpl)
    session.commit()
    session.refresh(tmpl)
    return tmpl


def delete_template(session: Session, template_id: int) -> bool:
    tmpl = get_template(session, template_id)
    if not tmpl:
        return False
    session.delete(tmpl)
    session.commit()
    return True


def deploy_template(session: Session, company_id: int, user_id: int, template_id: int, agent_name: Optional[str] = None) -> VoiceAgent:
    """Clone a template into a new VoiceAgent for the company."""
    tmpl = get_template(session, template_id)
    if not tmpl:
        raise ValueError("Template not found")

    name = agent_name or tmpl.name
    agent = VoiceAgent(
        company_id=company_id,
        name=name,
        description=tmpl.description,
        agent_type="prompt",
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)

    runtime = VoiceAgentRuntimeConfig(
        company_id=company_id,
        agent_id=agent.id,
        runtime_json=tmpl.config_json.get("runtime", {}),
        stt_provider=tmpl.config_json.get("stt_provider"),
        llm_provider=tmpl.config_json.get("llm_provider"),
        tts_provider=tmpl.config_json.get("tts_provider"),
        language=tmpl.config_json.get("language", "en-IN"),
        ai_verbosity=tmpl.config_json.get("ai_verbosity", "2"),
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(runtime)

    prompt = VoiceAgentPromptVersion(
        company_id=company_id,
        agent_id=agent.id,
        version=1,
        name="Deployed from template",
        system_prompt=tmpl.system_prompt or "",
        instructions=tmpl.instructions,
        is_active=True,
        created_by=user_id,
        updated_by=user_id,
        published_at=utc_now(),
    )
    session.add(prompt)
    session.commit()

    tmpl.usage_count = (tmpl.usage_count or 0) + 1
    session.add(tmpl)
    session.commit()

    logger.info("[AgentTemplate] Deployed template %r as agent %r (id=%s)", tmpl.key, name, agent.id)
    return agent


def seed_templates_from_directory(session: Session, directory: str = "seeds/agent_templates") -> int:
    """Load JSON template files from the seed directory and create any that don't exist."""
    seed_dir = Path(directory)
    if not seed_dir.exists():
        logger.info("[AgentTemplate] Seed directory %s not found, skipping", directory)
        return 0

    count = 0
    for path in sorted(seed_dir.glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
            existing = get_template_by_key(session, data["key"])
            if existing:
                logger.debug("[AgentTemplate] Skipping existing seed %r", data["key"])
                continue
            tmpl = AgentTemplate(
                key=data["key"],
                name=data["name"],
                description=data.get("description"),
                category=data.get("category", "general"),
                industry=data.get("industry"),
                is_public=data.get("is_public", True),
                config_json=data.get("config_json", {}),
                system_prompt=data.get("system_prompt", ""),
                instructions=data.get("instructions"),
                tags=data.get("tags", []),
            )
            session.add(tmpl)
            session.commit()
            count += 1
            logger.info("[AgentTemplate] Seeded template %r from %s", data["key"], path.name)
        except Exception as exc:
            logger.warning("[AgentTemplate] Failed to seed %s: %s", path.name, exc)
    return count
