from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, func, select

from auth import PermissionChecker
from database import get_session
from models.models import Product, ProductCreate, ProductUpdate, User, utc_now

router = APIRouter(prefix="/crm", tags=["CRM"])


@router.post("/products", response_model=Product)
async def create_product(
    data: ProductCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    sku = data.sku.strip() if data.sku else None
    if sku:
        existing = session.exec(
            select(Product).where(
                Product.company_id == current_user.company_id,
                Product.sku == sku,
            )
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="SKU already exists in this company")

    product = Product(
        company_id=current_user.company_id,
        name=data.name.strip(),
        sku=sku,
        stock=data.stock,
        price=data.price,
        currency=data.currency,
        note=data.note,
        is_active=data.is_active,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.get("/products")
async def list_products(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=1000),
    is_active: bool | None = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.read")),
):
    query = select(Product).where(Product.company_id == current_user.company_id)
    count_query = select(func.count()).select_from(Product).where(Product.company_id == current_user.company_id)

    if is_active is not None:
        query = query.where(Product.is_active == is_active)
        count_query = count_query.where(Product.is_active == is_active)

    total = session.exec(count_query).one()
    items = session.exec(
        query.order_by(Product.created_at.desc()).offset((page - 1) * limit).limit(limit)
    ).all()
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/products/{product_id}", response_model=Product)
async def get_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.read")),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == current_user.company_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


@router.put("/products/{product_id}", response_model=Product)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == current_user.company_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    payload = data.model_dump(exclude_unset=True)
    if "sku" in payload:
        payload["sku"] = payload["sku"].strip() if payload["sku"] else None
        if payload["sku"] and payload["sku"] != product.sku:
            duplicate = session.exec(
                select(Product).where(
                    Product.company_id == current_user.company_id,
                    Product.sku == payload["sku"],
                    Product.id != product.id,
                )
            ).first()
            if duplicate:
                raise HTTPException(status_code=400, detail="SKU already exists in this company")

    if "name" in payload and payload["name"] is not None:
        payload["name"] = payload["name"].strip()

    for key, value in payload.items():
        setattr(product, key, value)

    product.updated_at = utc_now()
    product.updated_by = current_user.id
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    product = session.exec(
        select(Product).where(
            Product.id == product_id,
            Product.company_id == current_user.company_id,
        )
    ).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    session.delete(product)
    session.commit()
    return {"message": "Product deleted"}


# Inventory aliases (same data, separate URL namespace)

@router.get("/inventory")
async def list_inventory(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=1000),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.read")),
):
    return await list_products(page=page, limit=limit, is_active=None, session=session, current_user=current_user)


@router.post("/inventory", response_model=Product)
async def create_inventory_product(
    data: ProductCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    return await create_product(data=data, session=session, current_user=current_user)


@router.put("/inventory/{product_id}", response_model=Product)
async def update_inventory_product(
    product_id: int,
    data: ProductUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    return await update_product(product_id=product_id, data=data, session=session, current_user=current_user)


@router.delete("/inventory/{product_id}")
async def delete_inventory_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    return await delete_product(product_id=product_id, session=session, current_user=current_user)
