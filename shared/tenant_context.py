"""
Tenant context helpers shared across services.

The backend uses PostgreSQL session settings plus ContextVars so every request,
worker task, and background flush can carry the active tenant boundary.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Dict, Iterator, Optional


DEFAULT_TENANT_ID = "00000000-0000-7000-8000-000000000001"
DEFAULT_TENANT_SLUG = "default"


tenant_id_ctx_var: ContextVar[Optional[str]] = ContextVar("tenant_id", default=None)
tenant_slug_ctx_var: ContextVar[Optional[str]] = ContextVar("tenant_slug", default=None)
user_role_id_ctx_var: ContextVar[Optional[str]] = ContextVar("user_role_id", default=None)
user_email_ctx_var: ContextVar[Optional[str]] = ContextVar("tenant_user_email", default=None)


def get_current_tenant_id() -> Optional[str]:
    return tenant_id_ctx_var.get()


def get_current_tenant_slug() -> Optional[str]:
    return tenant_slug_ctx_var.get()


def get_current_user_role_id() -> Optional[str]:
    return user_role_id_ctx_var.get()


def get_current_user_email() -> Optional[str]:
    return user_email_ctx_var.get()


def get_tenant_context() -> Dict[str, Optional[str]]:
    return {
        "tenant_id": get_current_tenant_id(),
        "tenant_slug": get_current_tenant_slug(),
        "user_role_id": get_current_user_role_id(),
        "user_email": get_current_user_email(),
    }


def set_tenant_context(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    user_role_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> Dict[str, Token]:
    return {
        "tenant_id": tenant_id_ctx_var.set(tenant_id),
        "tenant_slug": tenant_slug_ctx_var.set(tenant_slug),
        "user_role_id": user_role_id_ctx_var.set(user_role_id),
        "user_email": user_email_ctx_var.set(user_email),
    }


def reset_tenant_context(tokens: Dict[str, Token]) -> None:
    if not tokens:
        return
    tenant_id_ctx_var.reset(tokens["tenant_id"])
    tenant_slug_ctx_var.reset(tokens["tenant_slug"])
    user_role_id_ctx_var.reset(tokens["user_role_id"])
    user_email_ctx_var.reset(tokens["user_email"])


@contextmanager
def tenant_context(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    user_role_id: Optional[str] = None,
    user_email: Optional[str] = None,
) -> Iterator[None]:
    tokens = set_tenant_context(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        user_role_id=user_role_id,
        user_email=user_email,
    )
    try:
        yield
    finally:
        reset_tenant_context(tokens)
