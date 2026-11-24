"""Gateway REST route modules (spec section 9)."""

from declaw.gateway.routes.audit import router as audit_router
from declaw.gateway.routes.auth import auth_router
from declaw.gateway.routes.documents import router as documents_router
from declaw.gateway.routes.plugins import router as plugins_router
from declaw.gateway.routes.settings import router as settings_router
from declaw.gateway.routes.status import router as status_router
from declaw.gateway.routes.tasks import router as tasks_router

__all__ = [
    "audit_router",
    "auth_router",
    "documents_router",
    "plugins_router",
    "settings_router",
    "status_router",
    "tasks_router",
]
