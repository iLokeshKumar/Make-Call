"""Auth route modules."""
# Import router from parent auth.py for backward compatibility
import sys
from pathlib import Path

# Add parent directory to path to import auth.py
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

try:
    # Import from auth.py (not this package)
    import importlib.util
    spec = importlib.util.spec_from_file_location("auth_module", parent_dir / "auth.py")
    if spec and spec.loader:
        auth_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(auth_module)
        router = auth_module.router
except Exception:
    # Fallback: create empty router
    from fastapi import APIRouter
    router = APIRouter(tags=["Authentication"])

