from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, SQLModel

from auth import PermissionChecker
from database import get_session
from models.models import User

router = APIRouter(prefix="/crm", tags=["CRM"])


class ApolloImportRequest(SQLModel):
    job_titles: list[str] = []
    locations: list[str] = []
    companies: list[str] = []
    keywords: str = ""
    limit: int = 25


class LushaQuery(SQLModel):
    first_name: str
    last_name: str = ""
    company: str = ""


class LushaImportRequest(SQLModel):
    queries: list[LushaQuery]


class ZoomInfoImportRequest(SQLModel):
    job_titles: list[str] = []
    locations: list[str] = []
    companies: list[str] = []
    departments: list[str] = []
    keywords: str = ""
    limit: int = 25


@router.get("/leads/import/template")
async def download_import_template():
    """Return a CSV template for manual bulk upload. No auth required — static file."""
    from fastapi.responses import Response
    headers_row = "name,normalized_phone,email,company_name,job_title,industry,city,state,country,notes\n"
    sample = "John Smith,+919876543210,john@example.com,Acme Corp,VP Sales,SaaS,Mumbai,Maharashtra,India,\n"
    return Response(
        content=headers_row + sample,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads_template.csv"},
    )


@router.post("/leads/import/file")
async def import_leads_from_file(
    file: UploadFile = File(...),
    source_tag: str = Form(default="csv_import"),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Upload a CSV or Excel file to bulk-import leads."""
    from services.lead_import_service import bulk_create_leads, parse_file_upload
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file uploaded")
    allowed = {".csv", ".xlsx", ".xls"}
    ext = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in allowed:
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported")

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")

    try:
        lead_dicts = parse_file_upload(content, file.filename, source_tag)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}")

    if not lead_dicts:
        raise HTTPException(status_code=422, detail="No valid rows found in file. Check column headers.")

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result


@router.post("/leads/import/apollo")
async def import_leads_from_apollo(
    body: ApolloImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Search Apollo.io and import matching contacts as leads."""
    from credentials_service import get_company_credential
    from services.lead_import_service import bulk_create_leads, search_apollo_leads
    api_key = get_company_credential(session, current_user.company_id, "APOLLO_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Apollo API key not configured. Add it in Settings → Integrations.")

    try:
        lead_dicts = search_apollo_leads(
            api_key=api_key,
            job_titles=body.job_titles or None,
            locations=body.locations or None,
            companies=body.companies or None,
            keywords=body.keywords or None,
            limit=min(body.limit, 100),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not lead_dicts:
        return {"imported": 0, "skipped": 0, "errors": [], "message": "Apollo returned no results for these filters."}

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result


@router.post("/leads/import/lusha")
async def import_leads_from_lusha(
    body: LushaImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Lookup contacts on Lusha and import as leads."""
    from credentials_service import get_company_credential
    from services.lead_import_service import bulk_create_leads, search_lusha_leads
    api_key = get_company_credential(session, current_user.company_id, "LUSHA_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Lusha API key not configured. Add it in Settings → Integrations.")

    if not body.queries:
        raise HTTPException(status_code=400, detail="Provide at least one name/company query")

    try:
        lead_dicts = search_lusha_leads(
            api_key=api_key,
            queries=[q.dict() for q in body.queries],
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Lusha API error: {exc}")

    if not lead_dicts:
        return {"imported": 0, "skipped": 0, "errors": [], "message": "Lusha returned no results."}

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result


@router.post("/leads/import/zoominfo")
async def import_leads_from_zoominfo(
    body: ZoomInfoImportRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("lead.create")),
):
    """Search ZoomInfo and import matching contacts as leads."""
    from credentials_service import get_company_credential
    from services.lead_import_service import bulk_create_leads, search_zoominfo_leads

    client_id = get_company_credential(session, current_user.company_id, "ZOOMINFO_CLIENT_ID")
    private_key = get_company_credential(session, current_user.company_id, "ZOOMINFO_API_KEY")
    if not client_id or not private_key:
        raise HTTPException(
            status_code=400,
            detail="ZoomInfo credentials not configured. Add ZOOMINFO_CLIENT_ID and ZOOMINFO_API_KEY in Settings → Integrations.",
        )

    try:
        lead_dicts = search_zoominfo_leads(
            client_id=client_id,
            private_key=private_key,
            job_titles=body.job_titles or None,
            locations=body.locations or None,
            companies=body.companies or None,
            departments=body.departments or None,
            keywords=body.keywords or None,
            limit=min(body.limit, 100),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    if not lead_dicts:
        return {"imported": 0, "skipped": 0, "errors": [], "message": "ZoomInfo returned no results for these filters."}

    result = bulk_create_leads(session, current_user.company_id, current_user.id, lead_dicts)
    return result
