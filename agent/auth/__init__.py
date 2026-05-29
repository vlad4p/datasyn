"""OAuth login (Google, GitHub) and signed session cookies for the Datasyn brain."""

from agent.auth.config import auth_settings
from agent.auth.deps import require_user
from agent.auth.routes import router as auth_router

__all__ = ["auth_router", "auth_settings", "require_user"]
