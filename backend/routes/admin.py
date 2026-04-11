from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from auth import get_current_user, PermissionChecker
from database import get_session
from models.models import (
    Permission,
    Role,
    RoleCreate,
    RolePermission,
    RoleUpdate,
    AssignRoleRequest,
    User,
    UserRole,
    UserUpdateStatus,
)
from models.models import utc_now

router = APIRouter(prefix="/admin", tags=["Admin"])

# all company users

@router.get("/users")
async def list_company_users(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("user.read")),
):
    users = session.exec(
        select(User).where(User.company_id == current_user.company_id)
    ).all()

    result = []
    for user in users:
        role_ids = session.exec(
            select(UserRole.role_id).where(UserRole.user_id == user.id)
        ).all()

        role_names = []
        if role_ids:
            roles = session.exec(
                select(Role).where(Role.id.in_(role_ids))
            ).all()
            role_names = [r.name for r in roles]

        result.append({
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_active": user.is_active,
            "email_verified": user.email_verified,
            "roles": role_names,
            "created_at": user.created_at,
        })

    return result

# Listing available permissions

@router.get("/permissions")
async def list_permissions(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("role.read")),
):
    permissions = session.exec(select(Permission)).all()
    return permissions

# show company roles

@router.get("/roles")
async def list_roles(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("role.read")),
):
    roles = session.exec(
        select(Role).where(Role.company_id == current_user.company_id)
    ).all()

    result = []
    for role in roles:
        permission_keys = session.exec(
            select(RolePermission.permission_key).where(RolePermission.role_id == role.id)
        ).all()

        result.append({
            "id": role.id,
            "name": role.name,
            "description": role.description,
            "is_system": role.is_system,
            "permission_keys": permission_keys,
        })

    return result

# Creating custom role

# Only company admins / owners with role.manage can do

@router.post("/roles")
async def create_role(
    data: RoleCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("role.manage")),
):
    existing = session.exec(
        select(Role).where(
            Role.company_id == current_user.company_id,
            Role.name == data.name.strip(),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Role name already exists")

    valid_permissions = {
        p.key for p in session.exec(select(Permission)).all()
    }

    invalid_permissions = [key for key in data.permission_keys if key not in valid_permissions]
    if invalid_permissions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid permission keys: {', '.join(invalid_permissions)}",
        )

    role = Role(
        company_id=current_user.company_id,
        name=data.name.strip(),
        description=data.description,
        is_system=False,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(role)
    session.commit()
    session.refresh(role)

    for key in data.permission_keys:
        session.add(RolePermission(role_id=role.id, permission_key=key))
    session.commit()

    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "permission_keys": data.permission_keys,
    }

# Updating custom role

@router.put("/roles/{role_id}")
async def update_role(
    role_id: int,
    data: RoleUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("role.manage")),
):
    role = session.exec(
        select(Role).where(
            Role.id == role_id,
            Role.company_id == current_user.company_id,
        )
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    if role.is_system and data.name and data.name != role.name:
        raise HTTPException(status_code=400, detail="System role name cannot be changed")

    if data.name:
        duplicate = session.exec(
            select(Role).where(
                Role.company_id == current_user.company_id,
                Role.name == data.name.strip(),
                Role.id != role.id,
            )
        ).first()
        if duplicate:
            raise HTTPException(status_code=400, detail="Role name already exists")
        role.name = data.name.strip()

    if data.description is not None:
        role.description = data.description

    role.updated_at = utc_now()
    role.updated_by = current_user.id
    session.add(role)
    session.commit()

    if data.permission_keys is not None:
        valid_permissions = {
            p.key for p in session.exec(select(Permission)).all()
        }
        invalid_permissions = [key for key in data.permission_keys if key not in valid_permissions]
        if invalid_permissions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid permission keys: {', '.join(invalid_permissions)}",
            )

        existing_permissions = session.exec(
            select(RolePermission).where(RolePermission.role_id == role.id)
        ).all()
        for item in existing_permissions:
            session.delete(item)
        session.commit()

        for key in data.permission_keys:
            session.add(RolePermission(role_id=role.id, permission_key=key))
        session.commit()

    updated_permission_keys = session.exec(
        select(RolePermission.permission_key).where(RolePermission.role_id == role.id)
    ).all()

    return {
        "id": role.id,
        "name": role.name,
        "description": role.description,
        "is_system": role.is_system,
        "permission_keys": updated_permission_keys,
    }

# Assign role to user

# Important:

# - user must belong to same company
# - role must belong to same company

@router.post("/users/{user_id}/roles")
async def assign_role_to_user(
    user_id: int,
    data: AssignRoleRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("user.manage")),
):
    user = session.exec(
        select(User).where(
            User.id == user_id,
            User.company_id == current_user.company_id,
        )
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    role = session.exec(
        select(Role).where(
            Role.id == data.role_id,
            Role.company_id == current_user.company_id,
        )
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    existing = session.exec(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
        )
    ).first()
    if existing:
        return {"message": "Role already assigned"}

    session.add(UserRole(user_id=user.id, role_id=role.id))
    session.commit()

    return {"message": "Role assigned successfully"}

# Remove role from user

@router.delete("/users/{user_id}/roles/{role_id}")
async def remove_role_from_user(
    user_id: int,
    role_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("user.manage")),
):
    user = session.exec(
        select(User).where(
            User.id == user_id,
            User.company_id == current_user.company_id,
        )
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    role = session.exec(
        select(Role).where(
            Role.id == role_id,
            Role.company_id == current_user.company_id,
        )
    ).first()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")

    mapping = session.exec(
        select(UserRole).where(
            UserRole.user_id == user.id,
            UserRole.role_id == role.id,
        )
    ).first()
    if not mapping:
        raise HTTPException(status_code=404, detail="Role assignment not found")

    session.delete(mapping)
    session.commit()
    return {"message": "Role removed successfully"}

# Activate or deactivate user

@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: int,
    data: UserUpdateStatus,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("user.manage")),
):
    user = session.exec(
        select(User).where(
            User.id == user_id,
            User.company_id == current_user.company_id,
        )
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = data.is_active
    user.updated_at = utc_now()
    user.updated_by = current_user.id
    session.add(user)
    session.commit()

    return {"message": "User status updated"}


# ── Automation Worker health ──────────────────────────────────────────────────

@router.get("/worker/health")
async def worker_health(
    current_user: User = Depends(PermissionChecker("user.read")),
):
    """Return the latest automation-worker cycle metrics (no DB hit needed)."""
    from services.automation_worker_service import get_worker_health, pause_worker, resume_worker
    return get_worker_health()


@router.post("/worker/pause")
async def worker_pause(
    current_user: User = Depends(PermissionChecker("user.manage")),
):
    from services.automation_worker_service import pause_worker
    return pause_worker()


@router.post("/worker/resume")
async def worker_resume(
    current_user: User = Depends(PermissionChecker("user.manage")),
):
    from services.automation_worker_service import resume_worker
    return resume_worker()