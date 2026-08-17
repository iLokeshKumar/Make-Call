import io
import logging
import re
import difflib
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse, Response
from typing import Optional
from sqlmodel import Session, func, select

from auth import PermissionChecker
from database import get_session
from models.models import Product, ProductCreate, ProductUpdate, User, utc_now

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dynamic column detection
# ---------------------------------------------------------------------------

_PRODUCT_FIELDS: frozenset[str] = frozenset({
    "name", "sku", "stock", "price", "mrp", "cost_price", "min_price",
    "currency", "brand", "category", "subcategory", "product_line",
    "model_number", "description", "hsn_code", "tax_rate", "unit",
    "reorder_level", "warranty_months", "note", "image_url", "is_active",
})

# Explicit aliases only for words that don't match a field name directly
_ALIASES: dict[str, str] = {
    "product": "name", "item": "name", "goods": "name", "title": "name",
    "product_name": "name", "item_name": "name", "goods_name": "name", "part_name": "name",
    "product_details": "name",
    "selling_price": "price", "sale_price": "price", "sell_price": "price", "sp": "price",
    "approved_price": "min_price",
    "quantity": "stock", "qty": "stock", "inventory": "stock",
    "maximum_retail_price": "mrp",
    "cost": "cost_price", "purchase_price": "cost_price", "purchase": "cost_price",
    "minimum_price": "min_price",
    "manufacturer": "brand",
    "cat": "category",
    "sub_category": "subcategory", "subcat": "subcategory",
    "model": "model_number", "model_no": "model_number", "part_no": "sku", "part_number": "sku",
    "desc": "description", "details": "description",
    "hsn": "hsn_code",
    "tax": "tax_rate", "gst": "tax_rate", "vat": "tax_rate",
    "uom": "unit",
    "reorder": "reorder_level",
    "warranty": "warranty_months",
    "notes": "note", "remarks": "note", "comments": "note",
    "image": "image_url", "photo": "image_url", "picture": "image_url",
    "active": "is_active", "status": "is_active", "enabled": "is_active",
    "code": "sku", "item_code": "sku", "product_code": "sku",
    "line": "product_line",
}

# Strings that represent missing/empty values in spreadsheets
_NULL_STRINGS: frozenset[str] = frozenset({
    "nan", "none", "null", "n/a", "na", "#n/a", "#na",
    "-", "—", "–", "nil", "",
})

_DECIMAL_FIELDS = {"price", "mrp", "cost_price", "min_price", "tax_rate"}
_RANGE_SEP = re.compile(r"\s*[-–—]\s*")


def _parse_price_range(val: str) -> tuple["Decimal | None", "Decimal | None"]:
    """Parse '₹28,500 - ₹32,000' into (Decimal('28500'), Decimal('32000')).
    Returns (None, None) if not a valid two-part range."""
    parts = _RANGE_SEP.split(val.strip(), maxsplit=1)
    if len(parts) != 2:
        return None, None

    def _clean(s: str) -> "Decimal | None":
        cleaned = re.sub(r"[^\d.]", "", s.replace(",", ""))
        try:
            return Decimal(cleaned) if cleaned else None
        except InvalidOperation:
            return None

    lo, hi = _clean(parts[0]), _clean(parts[1])
    if lo is None or hi is None:
        return None, None
    return (lo, hi) if lo <= hi else (hi, lo)
_INT_FIELDS = {"stock", "reorder_level", "warranty_months"}
_BOOL_FIELDS = {"is_active"}
_TRUE_VALS = {"1", "true", "yes", "y", "active", "on"}

_STOP_WORDS = {"", "per", "in", "of", "the", "a", "an", "and", "or", "by"}


def _normalize_col(col: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", col.strip().lower()).strip("_")


def _map_column(col: str) -> str | None:
    """Dynamically map any column header to a product field name."""
    norm = _normalize_col(col)
    if not norm:
        return None

    # 1. Exact alias match
    if norm in _ALIASES:
        return _ALIASES[norm]

    # 2. Exact field name match
    if norm in _PRODUCT_FIELDS:
        return norm

    # 3. Word-based: all words of a field name are present in the column words
    words = set(norm.split("_")) - _STOP_WORDS
    for field in _PRODUCT_FIELDS:
        field_words = set(field.split("_")) - _STOP_WORDS
        if field_words and field_words.issubset(words):
            return field

    # 4. Alias key words overlap — require multi-word aliases to avoid false positives
    # (e.g. "product" alias should NOT match "product_catalog" which has 2 words)
    for alias, field in _ALIASES.items():
        alias_words = set(alias.split("_")) - _STOP_WORDS
        if not alias_words:
            continue
        if len(alias_words) == 1 and len(words) > 1:
            continue  # single-word alias must be an exact column name, not one word of many
        if alias_words.issubset(words):
            return field

    # 5. Fuzzy fallback
    candidates = list(_ALIASES) + [f for f in _PRODUCT_FIELDS]
    matches = difflib.get_close_matches(norm, candidates, n=1, cutoff=0.78)
    if matches:
        m = matches[0]
        return _ALIASES.get(m) or (m if m in _PRODUCT_FIELDS else None)

    return None


def _coerce(field: str, raw: Any) -> Any:
    # Float NaN from pandas
    if raw is None or (isinstance(raw, float) and raw != raw):
        return None
    val = str(raw).strip()
    if val.lower() in _NULL_STRINGS:
        return None
    if field in _DECIMAL_FIELDS:
        # Strip currency symbols and commas
        cleaned = re.sub(r"[^\d.\-]", "", val.replace(",", ""))
        try:
            return Decimal(cleaned) if cleaned else None
        except InvalidOperation:
            return None
    if field in _INT_FIELDS:
        # Strip trailing non-numeric (e.g. "10 units" → 10)
        m = re.match(r"[\-\d]+", val)
        try:
            return int(float(m.group())) if m else None
        except (ValueError, TypeError):
            return None
    if field in _BOOL_FIELDS:
        return val.lower() in _TRUE_VALS
    return val or None


def _parse_product_file(
    content: bytes, filename: str, sheet_name: str | None = None
) -> list[dict]:
    """Parse CSV or Excel into a list of raw product dicts using dynamic column detection.

    When multiple columns in the source file map to the same product field, the one
    whose rows contain the longest average non-empty value is chosen.  This means a
    "Product Details" column with full product names will automatically beat a
    "Product Name" column that only holds short category codes — with no hardcoding.
    """
    import pandas as pd
    from collections import defaultdict

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "csv"
    buf = io.BytesIO(content)

    if ext in ("xlsx", "xls"):
        df = pd.read_excel(buf, dtype=str, sheet_name=sheet_name if sheet_name else 0)
    else:
        df = pd.read_csv(buf, dtype=str)

    # Collect all candidate columns per field, scored by coverage × avg non-null length.
    # This ensures a column filled in 33/33 rows always beats one filled in 17/33 rows,
    # even if the per-row lengths are identical.
    field_candidates: dict[str, list[tuple[float, str]]] = defaultdict(list)
    total_rows = max(len(df), 1)
    for col in df.columns:
        field = _map_column(str(col))
        if not field:
            continue
        series = df[col].fillna("").astype(str)
        non_null = series[~series.str.lower().isin(_NULL_STRINGS) & (series.str.len() > 0)]
        coverage = len(non_null) / total_rows
        avg_len = float(non_null.str.len().mean()) if len(non_null) > 0 else 0.0
        score = coverage * avg_len
        field_candidates[field].append((score, str(col)))

    # For each field, keep only the highest-scoring candidate column
    col_to_field: dict[str, str] = {
        max(cands, key=lambda x: x[0])[1]: field
        for field, cands in field_candidates.items()
    }

    logger.debug("import column map: %s", col_to_field)

    rows = []
    for _, row in df.iterrows():
        product: dict = {}
        range_derived: set[str] = set()  # fields set by range parsing; protected from overwrite

        for raw_col, value in row.items():
            field = col_to_field.get(str(raw_col))
            if not field:
                continue

            # Detect price-range values like "₹28,500 - ₹32,000"
            if field in _DECIMAL_FIELDS:
                raw_str = str(value).strip() if value is not None else ""
                lo, hi = _parse_price_range(raw_str)
                if lo is not None and hi is not None:
                    product["min_price"] = lo
                    product[field] = hi
                    range_derived.update({"min_price", field})
                    continue

            # Don't let non-range values overwrite fields already set by range parsing
            if field in range_derived:
                continue

            coerced = _coerce(field, value)
            if coerced is not None:
                product[field] = coerced

        # Fallback: rows with only an exact approved/floor price and no range
        if not product.get("price") and product.get("min_price"):
            product["price"] = product["min_price"]

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


@router.post("/products/import/sheets")
async def list_excel_sheets(
    file: UploadFile = File(...),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    """Return the sheet names present in an uploaded Excel file."""
    import pandas as pd

    ext = (file.filename or "").rsplit(".", 1)[-1].lower()
    if ext not in {"xlsx", "xls"}:
        raise HTTPException(status_code=400, detail="Only Excel files have multiple sheets.")
    content = await file.read()
    xl = pd.ExcelFile(io.BytesIO(content))
    return JSONResponse({"sheets": xl.sheet_names})


@router.post("/products/import")
async def import_products_from_file(
    file: UploadFile = File(...),
    sheet_name: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    """Bulk-import products from a CSV or Excel file.

    - Rows with a matching SKU are **updated** (upsert by SKU).
    - Rows without a SKU or with a new SKU are **created**.
    - Returns a summary: created / updated / skipped / errors.
    - For Excel files with multiple sheets, pass ``sheet_name`` to select one.

    Required column: ``name`` (or any column the dynamic mapper can infer as the product name).
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported.")

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB).")

    sn = sheet_name.strip() if sheet_name and sheet_name.strip() else None
    try:
        rows = _parse_product_file(content, file.filename, sheet_name=sn)
    except Exception as exc:
        logger.warning("import_products: parse failed for %s: %s", file.filename, exc)
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")

    if not rows:
        logger.warning("import_products: no valid rows found in %s", file.filename)
        raise HTTPException(
            status_code=422,
            detail="No valid rows found — could not detect a product name column. "
                   "Accepted column names: 'Product', 'Name', 'Item', 'Title', or similar.",
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


@router.delete("/inventory/bulk")
async def bulk_delete_inventory_products(
    ids: list[int] = Body(..., embed=True),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("product.manage")),
):
    if not ids:
        raise HTTPException(status_code=400, detail="No IDs provided.")
    products = session.exec(
        select(Product).where(
            Product.company_id == current_user.company_id,
            Product.id.in_(ids),
        )
    ).all()
    for p in products:
        session.delete(p)
    session.commit()
    return {"deleted": len(products)}


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
