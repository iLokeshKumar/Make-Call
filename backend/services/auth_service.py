from typing import Iterable, Set

from sqlmodel import Session, select

from models.models import Permission, Role, RolePermission, UserRole


def get_user_permission_keys(session: Session, user_id: int) -> Set[str]:
    role_ids = session.exec(
        select(UserRole.role_id).where(UserRole.user_id == user_id)
    ).all()

    if not role_ids:
        return set()

    permission_keys = session.exec(
        select(RolePermission.permission_key).where(RolePermission.role_id.in_(role_ids))
    ).all()

    return set(permission_keys)


def user_has_permission(session: Session, user_id: int, permission_key: str) -> bool:
    return permission_key in get_user_permission_keys(session, user_id)


def create_default_permissions(session: Session) -> None:
    defaults = [
        ("lead.read_own", "lead", "Read own leads"),
        ("lead.read_company", "lead", "Read all company leads"),
        ("lead.create", "lead", "Create leads"),
        ("lead.update_own", "lead", "Update own leads"),
        ("lead.update_company", "lead", "Update all company leads"),
        ("lead.delete_own", "lead", "Delete own leads"),
        ("lead.delete_company", "lead", "Delete all company leads"),
        ("interaction.read_own", "interaction", "Read own interactions"),
        ("interaction.read_company", "interaction", "Read all company interactions"),
        ("product.read", "product", "Read products"),
        ("product.manage", "product", "Manage products"),
        ("appointment.read", "appointment", "Read appointments"),
        ("appointment.manage", "appointment", "Manage appointments"),
        ("outcome.read", "outcome", "Read outcomes"),
        ("outcome.manage", "outcome", "Manage outcomes"),
        ("user.invite", "user", "Invite users"),
        ("user.read", "user", "Read users"),
        ("user.manage", "user", "Manage users"),
        ("role.read", "role", "Read roles"),
        ("role.manage", "role", "Manage roles"),
        ("settings.read_company", "settings", "Read company settings"),
        ("settings.manage_company", "settings", "Manage company settings"),
        ("integrations.read_company", "integrations", "Read company integrations"),
        ("integrations.manage_company", "integrations", "Manage company integrations"),
        ("analytics.read_company", "analytics", "Read analytics"),
        ("campaign.read", "campaign", "Read campaigns"),
        ("campaign.manage", "campaign", "Manage campaigns"),
        ("campaign.launch", "campaign", "Launch campaigns"),
        ("call_task.read", "call_task", "Read call tasks"),
        ("call_task.manage", "call_task", "Manage call tasks"),
        ("requirements.read", "requirements", "Read lead requirements"),
        ("requirements.manage", "requirements", "Manage lead requirements"),
        ("quote.read", "quote", "Read quotes"),
        ("quote.manage", "quote", "Manage quotes"),
        ("quote.send", "quote", "Send quotes"),
    ]

    existing = {
        p.key for p in session.exec(select(Permission)).all()
    }

    for key, module, description in defaults:
        if key not in existing:
            session.add(Permission(key=key, module=module, description=description))

    session.commit()


def create_default_roles_for_company(session: Session, company_id: int, actor_user_id: int) -> dict[str, Role]:
    owner = Role(
        company_id=company_id,
        name="company_owner",
        description="Full access",
        is_system=True,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    admin = Role(
        company_id=company_id,
        name="company_admin",
        description="Administrative access",
        is_system=True,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    sales = Role(
        company_id=company_id,
        name="sales_representative",
        description="Sales access",
        is_system=True,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )

    session.add(owner)
    session.add(admin)
    session.add(sales)
    session.commit()
    session.refresh(owner)
    session.refresh(admin)
    session.refresh(sales)

    return {
        "company_owner": owner,
        "company_admin": admin,
        "sales_representative": sales,
    }


def attach_permissions_to_role(session: Session, role_id: int, permission_keys: Iterable[str]) -> None:
    for key in permission_keys:
        session.add(RolePermission(role_id=role_id, permission_key=key))
    session.commit()


def seed_default_role_permissions(session: Session, roles: dict[str, Role]) -> None:
    all_permissions = {
        p.key for p in session.exec(select(Permission)).all()
    }

    admin_permissions = set(all_permissions)
    sales_permissions = {
        "lead.read_own",
        "lead.create",
        "lead.update_own",
        "interaction.read_own",
        "product.read",
        "appointment.read",
    }

    attach_permissions_to_role(session, roles["company_owner"].id, all_permissions)
    attach_permissions_to_role(session, roles["company_admin"].id, admin_permissions)
    attach_permissions_to_role(session, roles["sales_representative"].id, sales_permissions)

def user_has_any_permission(session: Session, user_id: int, permission_keys: Iterable[str]) -> bool:
    user_permissions = get_user_permission_keys(session, user_id)
    return any(key in user_permissions for key in permission_keys)
