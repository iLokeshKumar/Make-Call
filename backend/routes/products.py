import io
import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlmodel import Session, func, select

from auth import PermissionChecker
from database import get_session
from models.models import Product, ProductCreate, ProductUpdate, User, utc_now

logger = logging.getLogger(__name__)

# Column aliases — maps whatever the user puts in the header → our field name
_COL_MAP: dict[str, str] = {
    "name": "name", "product_name": "name", "item_name": "name", "title": "name",
    "sku": "sku", "code": "sku", "item_code": "sku", "product_code": "sku",
    "stock": "stock", "quantity": "stock", "qty": "stock", "inventory": "stock",
    "price": "price", "selling_price": "price", "sale_price": "price", "sp": "price",
    "mrp": "mrp", "maximum_retail_price": "mrp",
    "cost_price": "cost_price", "cost": "cost_price", "purchase_price": "cost_price",
    "min_price": "min_price", "minimum_price": "min_price",
    "currency": "currency",
    "note": "note", "notes": "note", "remarks": "note",
    "brand": "brand", "manufacturer": "brand",
    "category": "category", "cat": "category",
    "subcategory": "subcategory", "sub_category": "subcategory", "subcat": "subcategory",
    "product_line": "product_line", "line": "product_line",
    "model_number": "model_number", "model": "model_number", "model_no": "model_number",
    "description": "description", "desc": "description", "details": "description",
    "hsn_code": "hsn_code", "hsn": "hsn_code",
    "tax_rate": "tax_rate", "tax": "tax_rate", "gst": "tax_rate",
    "unit": "unit", "uom": "unit",
    "reorder_level": "reorder_level", "reorder": "reorder_level",
    "warranty_months": "warranty_months", "warranty": "warranty_months",
    "image_url": "image_url", "image": "image_url",
    "is_active": "is_active", "active": "is_active", "status": "is_active",
}

_DECIMAL_FIELDS = {"price", "mrp", "cost_price", "min_price", "tax_rate"}
_INT_FIELDS = {"stock", "reorder_level", "warranty_months"}
_BOOL_FIELDS = {"is_active"}

_TRUE_VALS = {"1", "true", "yes", "y", "active", "on"}


def _coerce(field: str, raw: Any) -> Any:
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return None
    val = str(raw).strip()
    if field in _DECIMAL_FIELDS:
        try:
            return Decimal(val.replace(",", ""))
        except InvalidOperation:
            return None
    if field in _INT_FIELDS:
        try:
            return int(float(val))
        except (ValueError, TypeError):
            return None
    if field in _BOOL_FIELDS:
        return val.lower() in _TRUE_VALS
    return val or None


def _parse_product_file(content: bytes, filename: str) -> list[dict]:
    """Parse CSV or Excel into a list of raw product dicts."""
    import pandas as pd

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
    buf = io.BytesIO(content)

    if ext in ("xlsx", "xls"):
        df = pd.read_excel(buf, dtype=str)
    else:
        df = pd.read_csv(buf, dtype=str)

    df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

    rows = []
    for _, row in df.iterrows():
        product: dict = {}
        for raw_col, value in row.items():
            field = _COL_MAP.get(str(raw_col).strip().lower())
            if not field:
                continue
            coerced = _coerce(field, value)
            if coerced is not None:
                product[field] = coerced
        if product.get("name"):
            rows.append(product)
    return rows

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


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------

_TEMPLATE_HEADERS = (
    "name,sku,stock,price,mrp,cost_price,currency,brand,category,subcategory,"
    "product_line,model_number,description,hsn_code,tax_rate,unit,"
    "reorder_level,warranty_months,note,is_active\n"
)
_TEMPLATE_SAMPLE = (
    "Laptop Pro 15,LP15-BLK,50,79999,89999,55000,INR,Dell,Electronics,"
    "Laptops,ProSeries,DP15-2024,15 inch laptop with i7 processor,84713000,"
    "18,piece,10,12,Best seller,true\n"
)


@router.get("/products/import/template")
async def download_product_template():
    """Return a CSV template for bulk product upload."""
    return Response(
        content=_TEMPLATE_HEADERS + _TEMPLATE_SAMPLE,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=products_template.csv"},
    )


@router.post("/products/import")
async def import_products_from_file(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    """Bulk-import products from a CSV or Excel file.

    - Rows with a matching SKU are **updated** (upsert by SKU).
    - Rows without a SKU or with a new SKU are **created**.
    - Returns a summary: created / updated / skipped / errors.

    Required column: ``name``.
    Optional columns: sku, stock, price, mrp, cost_price, currency, brand,
    category, subcategory, product_line, model_number, description, hsn_code,
    tax_rate, unit, reorder_level, warranty_months, note, is_active.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB).")

    try:
        rows = _parse_product_file(content, file.filename)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")

    if not rows:
        raise HTTPException(
            status_code=422,
            detail="No valid rows found. Ensure the file has a 'name' column.",
        )

    created = updated = skipped = 0
    errors: list[dict] = []

    for i, row in enumerate(rows, start=2):  # row 1 = header
        name = row.get("name", "").strip()
        if not name:
            skipped += 1
            continue

        sku = row.get("sku")
        existing: Product | None = None

        if sku:
            existing = session.exec(
                select(Product).where(
                    Product.company_id == current_user.company_id,
                    Product.sku == sku,
                )
            ).first()

        try:
            if existing:
                # Update existing product
                for field, value in row.items():
                    if hasattr(existing, field) and value is not None:
                        setattr(existing, field, value)
                existing.updated_at = utc_now()
                existing.updated_by = current_user.id
                session.add(existing)
                updated += 1
            else:
                product = Product(
                    company_id=current_user.company_id,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                    **{k: v for k, v in row.items() if hasattr(Product, k)},
                )
                session.add(product)
                created += 1
        except Exception as exc:
            errors.append({"row": i, "name": name, "error": str(exc)})
            session.rollback()
            continue

    try:
        session.commit()
    except Exception as exc:
        session.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {exc}")

    return {
        "total_rows": len(rows),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Inventory aliases (same data, separate URL namespace)
# ---------------------------------------------------------------------------

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


@router.get("/inventory/import/template")
async def download_inventory_template():
    """Return a CSV template for bulk inventory upload."""
    return await download_product_template()


@router.post("/inventory/import")
async def import_inventory_from_file(
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    """Bulk-import inventory from CSV or Excel. Alias for /products/import."""
    return await import_products_from_file(file=file, session=session, current_user=current_user)
