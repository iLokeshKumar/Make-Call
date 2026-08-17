from httpx import AsyncClient, ASGITransport
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from database import get_session
from main import app
from models.models import Company, User
from auth import get_password_hash

@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()

@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as s:
        yield s

@pytest.fixture(name="client")
async def client_fixture(session):
    def _get_session_override():
        yield session

    app.dependency_overrides[get_session] = _get_session_override
    
    # Seed company and user for authentication tests
    company = Company(id=1, name="Test Company", slug="test-company")
    session.add(company)
    session.commit()
    
    user = User(
        id=1,
        company_id=1,
        email="admin@test.com",
        username_normalized="admin@test.com",
        password_hash=get_password_hash("correctpassword"),
        is_active=True,
        email_verified=True,
    )
    session.add(user)
    session.commit()
    
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
        
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    response = await client.post("/token", data={
        "username": "admin@test.com",
        "password": "correctpassword"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()

@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    response = await client.post("/token", data={
        "username": "admin@test.com",
        "password": "wrongpassword"
    })
    assert response.status_code == 401