"""Pool management admin API routes.

Provides endpoints for managing account pools at scale:
- Overview of all pool-enabled providers
- Paginated key listing with search/filter
- Batch import / batch actions
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.api.base.admin_adapter import AdminApiAdapter
from src.api.base.context import ApiRequestContext
from src.api.base.pipeline import ApiRequestPipeline
from src.core.crypto import crypto_service
from src.core.exceptions import NotFoundException
from src.core.logger import logger
from src.database import get_db
from src.models.database import Provider, ProviderAPIKey
from src.services.provider.pool import redis_ops as pool_redis
from src.services.provider.pool.config import parse_pool_config

from .schemas import (
    BatchActionRequest,
    BatchActionResponse,
    BatchImportError,
    BatchImportRequest,
    BatchImportResponse,
    PoolKeyDetail,
    PoolKeysPageResponse,
    PoolOverviewItem,
    PoolOverviewResponse,
)

router = APIRouter(prefix="/api/admin/pool", tags=["pool-management"])
pipeline = ApiRequestPipeline()


# ---------------------------------------------------------------------------
# GET /api/admin/pool/overview
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=PoolOverviewResponse)
async def pool_overview(
    request: Request,
    db: Session = Depends(get_db),
) -> PoolOverviewResponse:
    """Return all pool-enabled providers with summary stats."""
    adapter = AdminPoolOverviewAdapter()
    return await pipeline.run(adapter=adapter, http_request=request, db=db, mode=adapter.mode)


# ---------------------------------------------------------------------------
# GET /api/admin/pool/{provider_id}/keys
# ---------------------------------------------------------------------------


@router.get("/{provider_id}/keys", response_model=PoolKeysPageResponse)
async def list_pool_keys(
    provider_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    search: str = Query("", description="Search by key name"),
    status: str = Query("all", description="all/active/cooldown/inactive"),
    db: Session = Depends(get_db),
) -> PoolKeysPageResponse:
    """Server-side paginated account list for a pool-enabled provider."""
    adapter = AdminListPoolKeysAdapter(
        provider_id=provider_id,
        page=page,
        page_size=page_size,
        search=search,
        status=status,
    )
    return await pipeline.run(adapter=adapter, http_request=request, db=db, mode=adapter.mode)


# ---------------------------------------------------------------------------
# POST /api/admin/pool/{provider_id}/keys/batch-import
# ---------------------------------------------------------------------------


@router.post("/{provider_id}/keys/batch-import", response_model=BatchImportResponse)
async def batch_import_keys(
    provider_id: str,
    body: BatchImportRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BatchImportResponse:
    """Batch import keys into a provider's pool."""
    adapter = AdminBatchImportKeysAdapter(provider_id=provider_id, body=body)
    return await pipeline.run(adapter=adapter, http_request=request, db=db, mode=adapter.mode)


# ---------------------------------------------------------------------------
# POST /api/admin/pool/{provider_id}/keys/batch-action
# ---------------------------------------------------------------------------

ALLOWED_ACTIONS = {"enable", "disable", "delete", "clear_cooldown", "reset_cost"}


@router.post("/{provider_id}/keys/batch-action", response_model=BatchActionResponse)
async def batch_action_keys(
    provider_id: str,
    body: BatchActionRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> BatchActionResponse:
    """Batch enable/disable/delete/clear_cooldown/reset_cost on pool keys."""
    adapter = AdminBatchActionKeysAdapter(provider_id=provider_id, body=body)
    return await pipeline.run(adapter=adapter, http_request=request, db=db, mode=adapter.mode)


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class AdminPoolOverviewAdapter(AdminApiAdapter):
    async def handle(self, context: ApiRequestContext) -> Any:  # type: ignore[override]
        db = context.db
        providers = (
            db.query(Provider)
            .filter(Provider.is_active.is_(True))
            .order_by(Provider.provider_priority.asc())
            .all()
        )

        items: list[PoolOverviewItem] = []
        for p in providers:
            pid = str(p.id)
            pcfg = parse_pool_config(getattr(p, "config", None))

            # Non-pool providers: skip Redis + key queries entirely.
            if pcfg is None:
                items.append(
                    PoolOverviewItem(
                        provider_id=pid,
                        provider_name=p.name,
                        provider_type=str(getattr(p, "provider_type", "custom") or "custom"),
                        pool_enabled=False,
                    )
                )
                continue

            keys = db.query(ProviderAPIKey).filter(ProviderAPIKey.provider_id == pid).all()
            key_ids = [str(k.id) for k in keys]

            cooldown_count = 0
            if key_ids:
                cooldowns = await pool_redis.batch_get_cooldowns(pid, key_ids)
                cooldown_count = sum(1 for v in cooldowns.values() if v is not None)

            items.append(
                PoolOverviewItem(
                    provider_id=pid,
                    provider_name=p.name,
                    provider_type=str(getattr(p, "provider_type", "custom") or "custom"),
                    total_keys=len(keys),
                    active_keys=sum(1 for k in keys if k.is_active),
                    cooldown_count=cooldown_count,
                    pool_enabled=True,
                )
            )

        return PoolOverviewResponse(items=items)


@dataclass
class AdminListPoolKeysAdapter(AdminApiAdapter):
    provider_id: str = ""
    page: int = 1
    page_size: int = 50
    search: str = ""
    status: str = "all"

    async def handle(self, context: ApiRequestContext) -> Any:  # type: ignore[override]
        db = context.db
        provider = db.query(Provider).filter(Provider.id == self.provider_id).first()
        if not provider:
            raise NotFoundException("Provider not found", "provider")

        pcfg = parse_pool_config(getattr(provider, "config", None))
        pid = str(provider.id)

        # Base query
        q = db.query(ProviderAPIKey).filter(ProviderAPIKey.provider_id == pid)

        if self.search:
            escaped = self.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.filter(ProviderAPIKey.name.ilike(f"%{escaped}%"))

        if self.status == "active":
            q = q.filter(ProviderAPIKey.is_active.is_(True))
        elif self.status == "inactive":
            q = q.filter(ProviderAPIKey.is_active.is_(False))
        # "cooldown" filtering is done post-query (Redis state)

        total = q.count()

        # For cooldown filtering we need to fetch all, then filter, then paginate.
        # Limit scan range to avoid loading the entire table into memory.
        if self.status == "cooldown":
            _max_scan = 2000
            all_keys = q.order_by(ProviderAPIKey.created_at.desc()).limit(_max_scan).all()
            key_ids = [str(k.id) for k in all_keys]
            cooldowns = await pool_redis.batch_get_cooldowns(pid, key_ids) if key_ids else {}
            all_keys = [k for k in all_keys if cooldowns.get(str(k.id)) is not None]
            total = len(all_keys)
            offset = (self.page - 1) * self.page_size
            keys = all_keys[offset : offset + self.page_size]
        else:
            offset = (self.page - 1) * self.page_size
            keys = (
                q.order_by(ProviderAPIKey.created_at.desc())
                .offset(offset)
                .limit(self.page_size)
                .all()
            )

        # Batch fetch Redis state (parallel where possible)
        key_ids = [str(k.id) for k in keys]
        if key_ids:
            _lru_coro = (
                pool_redis.get_lru_scores(pid, key_ids)
                if pcfg and pcfg.lru_enabled
                else asyncio.sleep(0, result={})
            )
            _cost_coro = (
                pool_redis.batch_get_cost_totals(pid, key_ids, pcfg.cost_window_seconds)
                if pcfg
                else asyncio.sleep(0, result={})
            )
            cooldowns, cooldown_ttls, lru_scores, cost_totals = await asyncio.gather(
                pool_redis.batch_get_cooldowns(pid, key_ids),
                pool_redis.batch_get_cooldown_ttls(pid, key_ids),
                _lru_coro,
                _cost_coro,
            )
        else:
            cooldowns, cooldown_ttls, lru_scores, cost_totals = {}, {}, {}, {}

        # Sticky session count per key is expensive (SCAN+MGET per key).
        # Only compute when the page is small enough to avoid timeout.
        sticky_counts: dict[str, int] = {}
        if key_ids and len(key_ids) <= 30:
            counts = await asyncio.gather(
                *(pool_redis.get_key_sticky_count(pid, kid) for kid in key_ids)
            )
            sticky_counts = dict(zip(key_ids, counts))

        key_details: list[PoolKeyDetail] = []
        for k in keys:
            kid = str(k.id)
            cd_reason = cooldowns.get(kid)
            cd_ttl = cooldown_ttls.get(kid) if cd_reason else None

            key_details.append(
                PoolKeyDetail(
                    key_id=kid,
                    key_name=k.name or "",
                    is_active=bool(k.is_active),
                    auth_type=str(getattr(k, "auth_type", "api_key") or "api_key"),
                    cooldown_reason=cd_reason,
                    cooldown_ttl_seconds=cd_ttl,
                    cost_window_usage=cost_totals.get(kid, 0),
                    cost_limit=pcfg.cost_limit_per_key_tokens if pcfg else None,
                    sticky_sessions=sticky_counts.get(kid, 0),
                    lru_score=lru_scores.get(kid),
                    created_at=(
                        k.created_at.isoformat() if getattr(k, "created_at", None) else None
                    ),
                    last_used_at=(
                        k.last_used_at.isoformat() if getattr(k, "last_used_at", None) else None
                    ),
                )
            )

        return PoolKeysPageResponse(
            total=total,
            page=self.page,
            page_size=self.page_size,
            keys=key_details,
        )


@dataclass
class AdminBatchImportKeysAdapter(AdminApiAdapter):
    provider_id: str = ""
    body: BatchImportRequest = field(default_factory=lambda: BatchImportRequest(keys=[]))

    async def handle(self, context: ApiRequestContext) -> Any:  # type: ignore[override]
        db = context.db
        provider = db.query(Provider).filter(Provider.id == self.provider_id).first()
        if not provider:
            raise NotFoundException("Provider not found", "provider")

        imported = 0
        skipped = 0
        errors: list[BatchImportError] = []
        now = datetime.now(timezone.utc)

        for idx, item in enumerate(self.body.keys):
            if not item.api_key.strip():
                errors.append(BatchImportError(index=idx, reason="api_key is empty"))
                continue

            try:
                encrypted_key = crypto_service.encrypt(item.api_key)
                new_key = ProviderAPIKey(
                    id=str(uuid.uuid4()),
                    provider_id=self.provider_id,
                    name=item.name or f"imported-{idx}",
                    api_key=encrypted_key,
                    auth_type=item.auth_type or "api_key",
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                db.add(new_key)
                imported += 1
            except Exception as exc:
                logger.warning("batch import key #{} failed: {}", idx, exc)
                errors.append(BatchImportError(index=idx, reason=str(exc)))

        if imported > 0:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.error("batch import commit failed: {}", exc)
                return BatchImportResponse(
                    imported=0,
                    skipped=skipped,
                    errors=[BatchImportError(index=-1, reason=f"commit failed: {exc}")],
                )

        admin_name = context.user.username if context.user else "admin"
        logger.info(
            "Pool batch import by {}: provider={}, imported={}, skipped={}, errors={}",
            admin_name,
            self.provider_id[:8],
            imported,
            skipped,
            len(errors),
        )

        return BatchImportResponse(imported=imported, skipped=skipped, errors=errors)


@dataclass
class AdminBatchActionKeysAdapter(AdminApiAdapter):
    provider_id: str = ""
    body: BatchActionRequest = field(
        default_factory=lambda: BatchActionRequest(key_ids=[], action="")
    )

    async def handle(self, context: ApiRequestContext) -> Any:  # type: ignore[override]
        from fastapi import HTTPException

        if self.body.action not in ALLOWED_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Invalid action: {self.body.action}. "
                    f"Allowed: {', '.join(sorted(ALLOWED_ACTIONS))}"
                ),
            )

        db = context.db
        provider = db.query(Provider).filter(Provider.id == self.provider_id).first()
        if not provider:
            raise NotFoundException("Provider not found", "provider")

        pid = str(provider.id)
        affected = 0

        keys = (
            db.query(ProviderAPIKey)
            .filter(
                ProviderAPIKey.provider_id == pid,
                ProviderAPIKey.id.in_(self.body.key_ids),
            )
            .all()
        )

        for key in keys:
            kid = str(key.id)

            if self.body.action == "enable":
                key.is_active = True
                affected += 1

            elif self.body.action == "disable":
                key.is_active = False
                affected += 1

            elif self.body.action == "delete":
                db.delete(key)
                affected += 1

            elif self.body.action == "clear_cooldown":
                await pool_redis.clear_cooldown(pid, kid)
                affected += 1

            elif self.body.action == "reset_cost":
                await pool_redis.clear_cost(pid, kid)
                affected += 1

        if self.body.action in {"enable", "disable", "delete"}:
            try:
                db.commit()
            except Exception as exc:
                db.rollback()
                logger.error("batch action commit failed: {}", exc)
                return BatchActionResponse(affected=0, message=f"commit failed: {exc}")

        action_labels = {
            "enable": "enabled",
            "disable": "disabled",
            "delete": "deleted",
            "clear_cooldown": "cooldown cleared",
            "reset_cost": "cost reset",
        }

        admin_name = context.user.username if context.user else "admin"
        affected_ids = [str(k.id)[:8] for k in keys]
        logger.info(
            "Pool batch action by {}: provider={}, action={}, affected={}, key_ids={}",
            admin_name,
            self.provider_id[:8],
            self.body.action,
            affected,
            affected_ids,
        )

        return BatchActionResponse(
            affected=affected,
            message=f"{affected} keys {action_labels.get(self.body.action, self.body.action)}",
        )
