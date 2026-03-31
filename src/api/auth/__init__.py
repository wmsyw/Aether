"""Authentication route group."""

from fastapi import APIRouter

from .routes import router as auth_router
from .passkey_routes import router as passkey_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(passkey_router)

__all__ = ["router"]
