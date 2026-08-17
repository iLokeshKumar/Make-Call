import sys
import asyncio

def apply_windows_async_fix():
    """Must be called before ANY async code or psycopg import on Windows."""
    if sys.platform.startswith("win"):
        try:
            # Check if loop already exists — if so, we can't change policy
            try:
                asyncio.get_running_loop()
                # Loop already running — too late to change policy
                return
            except RuntimeError:
                pass  # No loop running yet — safe to set policy

            policy = asyncio.WindowsSelectorEventLoopPolicy()
            asyncio.set_event_loop_policy(policy)
            print("[startup] WindowsSelectorEventLoopPolicy applied", file=sys.stderr)
        except Exception as e:
            import sys as _sys
            print(
                f"[startup] WARN: failed to set WindowsSelectorEventLoopPolicy: {e!r}",
                file=_sys.stderr,
            )