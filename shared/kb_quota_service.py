from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import text

from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session
from shared.tenant_context import get_current_tenant_id

logger = get_otel_logger("kb_quota_service", "shared")

DEFAULT_MONTHLY_LIMIT_KB = 20 * 1024
KB_PER_MB = 1024
KB_QUOTA_EXCEEDED_CODE = "kb_quota_exceeded"
VALID_QUOTA_CYCLES = {"daily", "monthly"}


@dataclass
class TenantQuotaWindow:
    tenant_id: str
    tenant_created_at: datetime
    cycle_start_at: datetime
    cycle_end_at: datetime


class KBQuotaService:
    async def get_current_tenant_quota_summary(self) -> Dict[str, Any]:
        tenant_id = get_current_tenant_id()
        if not tenant_id:
            raise HTTPException(
                status_code=400, detail="Active tenant context is required"
            )
        return await self.get_tenant_quota_summary(tenant_id)

    async def get_tenant_quota_summary(self, tenant_id: str) -> Dict[str, Any]:
        logger.info(f"🔍 [KB_QUOTA] Getting quota summary for tenant_id={tenant_id}")

        tenant = await self._get_tenant_row(tenant_id)
        logger.info(f"🔍 [KB_QUOTA] Tenant row: {tenant}")
        if not tenant:
            logger.error(f"❌ [KB_QUOTA] Tenant not found: {tenant_id}")
            raise HTTPException(status_code=404, detail="Tenant not found")

        config = await self._get_or_create_quota_config(tenant_id)
        quota_cycle = self._normalize_quota_cycle(config.get("quota_cycle"))
        now = datetime.now(timezone.utc)
        window = self._build_quota_window(tenant_id, tenant["created_at"], now, quota_cycle)

        logger.info(
            f"🔍 [KB_QUOTA] Quota window: cycle_start={window.cycle_start_at}, cycle_end={window.cycle_end_at}"
        )

        override = await self._get_or_create_monthly_override(tenant_id, window)
        logger.info(f"🔍 [KB_QUOTA] Override config: {override}")

        limit_kb = int(override["quota_limit_kb"] or config.get("quota_limit_kb") or DEFAULT_MONTHLY_LIMIT_KB)
        storage_limit_kb = int(config.get("storage_quota_limit_kb") or limit_kb)
        limit_bytes = limit_kb * 1024
        storage_limit_bytes = storage_limit_kb * 1024
        live_usage_bytes = await self._get_live_usage_bytes(tenant_id)
        gross_usage_bytes = await self._get_usage_bytes_for_window(tenant_id, window)
        usage_bytes = min(live_usage_bytes, storage_limit_bytes)
        gross_capped_bytes = min(gross_usage_bytes, limit_bytes)
        logger.info(
            f"🔍 [KB_QUOTA] Usage bytes: live={live_usage_bytes}, gross={gross_usage_bytes}, capped_live={usage_bytes}, upload_limit={limit_bytes}, storage_limit={storage_limit_bytes}"
        )
        remaining_bytes = max(storage_limit_bytes - usage_bytes, 0)
        gross_remaining_bytes = max(limit_bytes - gross_capped_bytes, 0)
        quota_limit_mb = round(limit_kb / KB_PER_MB, 2)
        storage_quota_limit_mb = round(storage_limit_kb / KB_PER_MB, 2)
        used_mb = round(usage_bytes / (KB_PER_MB * 1024), 2)
        remaining_mb = round(remaining_bytes / (KB_PER_MB * 1024), 2)
        gross_used_mb = round(gross_capped_bytes / (KB_PER_MB * 1024), 2)
        gross_remaining_mb = round(gross_remaining_bytes / (KB_PER_MB * 1024), 2)

        summary = {
            "tenant_id": tenant_id,
            "tenant_slug": tenant["slug"],
            "tenant_name": tenant["name"],
            "quota_limit_kb": limit_kb,
            "quota_limit_mb": quota_limit_mb,
            "quota_limit_bytes": limit_bytes,
            "quota_cycle": quota_cycle,
            "storage_quota_limit_kb": storage_limit_kb,
            "storage_quota_limit_mb": storage_quota_limit_mb,
            "storage_quota_limit_bytes": storage_limit_bytes,
            "used_bytes": usage_bytes,
            "raw_used_bytes": live_usage_bytes,
            "used_kb": round(usage_bytes / 1024, 2),
            "used_mb": used_mb,
            "remaining_bytes": remaining_bytes,
            "remaining_kb": round(remaining_bytes / 1024, 2),
            "remaining_mb": remaining_mb,
            "usage_percent": round((usage_bytes / storage_limit_bytes) * 100, 2)
            if storage_limit_bytes > 0
            else 0,
            "gross_used_bytes": gross_capped_bytes,
            "gross_raw_used_bytes": gross_usage_bytes,
            "gross_used_kb": round(gross_capped_bytes / 1024, 2),
            "gross_used_mb": gross_used_mb,
            "gross_remaining_bytes": gross_remaining_bytes,
            "gross_remaining_kb": round(gross_remaining_bytes / 1024, 2),
            "gross_remaining_mb": gross_remaining_mb,
            "gross_usage_percent": round((gross_capped_bytes / limit_bytes) * 100, 2)
            if limit_bytes > 0
            else 0,
            "cycle_start_at": window.cycle_start_at.isoformat(),
            "cycle_end_at": window.cycle_end_at.isoformat(),
            "tenant_created_at": tenant["created_at"].isoformat()
            if tenant["created_at"]
            else None,
            "manual_reset_count": int(override["manual_reset_count"] or 0),
            "last_manual_reset_at": override["last_manual_reset_at"].isoformat()
            if override.get("last_manual_reset_at")
            else None,
            "is_limit_reached": usage_bytes >= storage_limit_bytes,
            "is_upload_limit_reached": gross_capped_bytes >= limit_bytes,
        }
        logger.info(f"✅ [KB_QUOTA] Summary: {summary}")
        return summary

    async def list_all_tenant_quota_summaries(self) -> List[Dict[str, Any]]:
        query = text(
            """
            SELECT id, slug, name, created_at
            FROM tenants
            WHERE slug != 'default'
            ORDER BY created_at ASC, name ASC
            """
        )
        async with get_db_session() as session:
            rows = (await session.execute(query)).mappings().all()

        logger.info(f"🔍 [KB_QUOTA] Raw tenant rows from DB: {len(rows)} tenants found")
        for row in rows:
            logger.info(
                f"   - tenant: id={row['id']}, slug={row['slug']}, name={row['name']}"
            )

        summaries: List[Dict[str, Any]] = []
        for row in rows:
            try:
                tenant_id = str(row["id"])
                logger.info(
                    f"🔍 [KB_QUOTA] Fetching quota summary for tenant: {tenant_id}"
                )
                summary = await self.get_tenant_quota_summary(tenant_id)
                summaries.append(summary)
                logger.info(
                    f"✅ [KB_QUOTA] Got summary for {tenant_id}: used_kb={summary.get('used_kb')}, limit_kb={summary.get('quota_limit_kb')}"
                )
            except Exception as exc:
                logger.warning(
                    f"⚠️ [KB_QUOTA] Skipping tenant quota summary for {row['id']}: {exc}"
                )

        logger.info(f"📊 [KB_QUOTA] Returning {len(summaries)} tenant summaries")
        return summaries

    async def set_tenant_quota_limit(
        self,
        tenant_id: str,
        quota_limit_kb: int,
        quota_cycle: Optional[str] = None,
        storage_quota_limit_kb: Optional[int] = None,
    ) -> Dict[str, Any]:
        if quota_limit_kb <= 0:
            raise HTTPException(
                status_code=400, detail="Quota limit must be greater than 0 KB"
            )
        if storage_quota_limit_kb is not None and int(storage_quota_limit_kb) <= 0:
            raise HTTPException(
                status_code=400, detail="Storage quota limit must be greater than 0 KB"
            )
        existing_config = await self._get_or_create_quota_config(tenant_id)
        normalized_cycle = self._normalize_quota_cycle(
            quota_cycle or existing_config.get("quota_cycle")
        )
        normalized_storage_limit_kb = int(
            storage_quota_limit_kb
            if storage_quota_limit_kb is not None
            else existing_config.get("storage_quota_limit_kb") or quota_limit_kb
        )

        query = text(
            """
            INSERT INTO tenant_kb_quota_config (
                tenant_id,
                quota_limit_kb,
                storage_quota_limit_kb,
                quota_cycle,
                created_at,
                updated_at
            )
            VALUES (:tenant_id, :quota_limit_kb, :storage_quota_limit_kb, :quota_cycle, NOW(), NOW())
            ON CONFLICT (tenant_id) DO UPDATE
            SET quota_limit_kb = EXCLUDED.quota_limit_kb,
                storage_quota_limit_kb = EXCLUDED.storage_quota_limit_kb,
                quota_cycle = EXCLUDED.quota_cycle,
                updated_at = NOW()
            """
        )
        async with get_db_session() as session:
            await session.execute(
                query,
                {
                    "tenant_id": tenant_id,
                    "quota_limit_kb": quota_limit_kb,
                    "storage_quota_limit_kb": normalized_storage_limit_kb,
                    "quota_cycle": normalized_cycle,
                },
            )
            await session.commit()

        return await self.get_tenant_quota_summary(tenant_id)

    async def manual_reset_tenant_quota(
        self,
        tenant_id: str,
        new_limit_kb: Optional[int] = None,
        quota_cycle: Optional[str] = None,
        storage_quota_limit_kb: Optional[int] = None,
    ) -> Dict[str, Any]:
        tenant = await self._get_tenant_row(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        if new_limit_kb is not None and int(new_limit_kb) <= 0:
            raise HTTPException(
                status_code=400, detail="Quota limit must be greater than 0 KB"
            )
        if storage_quota_limit_kb is not None and int(storage_quota_limit_kb) <= 0:
            raise HTTPException(
                status_code=400, detail="Storage quota limit must be greater than 0 KB"
            )

        config = await self._get_or_create_quota_config(tenant_id)
        normalized_cycle = self._normalize_quota_cycle(quota_cycle or config.get("quota_cycle"))
        now = datetime.now(timezone.utc)
        window = self._build_quota_window(tenant_id, tenant["created_at"], now, normalized_cycle)

        if new_limit_kb is not None or quota_cycle is not None or storage_quota_limit_kb is not None:
            await self.set_tenant_quota_limit(
                tenant_id,
                int(new_limit_kb if new_limit_kb is not None else config["quota_limit_kb"]),
                normalized_cycle,
                int(
                    storage_quota_limit_kb
                    if storage_quota_limit_kb is not None
                    else config.get("storage_quota_limit_kb") or config["quota_limit_kb"]
                ),
            )

        query = text(
            """
            WITH config AS (
                SELECT COALESCE(
                    :new_limit_kb,
                    (SELECT quota_limit_kb FROM tenant_kb_quota_config WHERE tenant_id = :tenant_id),
                    :default_limit_kb
                ) AS quota_limit_kb
            )
            INSERT INTO tenant_kb_quota_monthly_usage (
                tenant_id,
                cycle_start_at,
                cycle_end_at,
                quota_limit_kb,
                reset_usage_at,
                manual_reset_count,
                last_manual_reset_at,
                created_at,
                updated_at
            )
            SELECT
                :tenant_id,
                :cycle_start_at,
                :cycle_end_at,
                config.quota_limit_kb,
                :reset_usage_at,
                1,
                NOW(),
                NOW(),
                NOW()
            FROM config
            ON CONFLICT (tenant_id, cycle_start_at) DO UPDATE
            SET quota_limit_kb = EXCLUDED.quota_limit_kb,
                cycle_end_at = EXCLUDED.cycle_end_at,
                reset_usage_at = EXCLUDED.reset_usage_at,
                manual_reset_count = tenant_kb_quota_monthly_usage.manual_reset_count + 1,
                last_manual_reset_at = EXCLUDED.last_manual_reset_at,
                updated_at = NOW()
            """
        )
        async with get_db_session() as session:
            await session.execute(
                query,
                {
                    "tenant_id": tenant_id,
                    "cycle_start_at": window.cycle_start_at,
                    "cycle_end_at": window.cycle_end_at,
                    "reset_usage_at": now,
                    "new_limit_kb": int(new_limit_kb)
                    if new_limit_kb is not None
                    else None,
                    "default_limit_kb": DEFAULT_MONTHLY_LIMIT_KB,
                },
            )
            await session.commit()

        return await self.get_tenant_quota_summary(tenant_id)

    async def ensure_upload_within_quota(
        self, tenant_id: str, requested_bytes: int
    ) -> Dict[str, Any]:
        summary = await self.get_tenant_quota_summary(tenant_id)
        if summary["gross_raw_used_bytes"] + requested_bytes > summary["quota_limit_bytes"]:
            self._raise_quota_exceeded(summary, requested_bytes, limit_type="upload")
        if summary["raw_used_bytes"] + requested_bytes > summary["storage_quota_limit_bytes"]:
            self._raise_quota_exceeded(summary, requested_bytes, limit_type="storage")
        return summary

    async def check_quota_before_embedding(
        self, tenant_id: str, content_bytes: int, item_label: str = "This content"
    ) -> Dict[str, Any]:
        """Check quota right before embedding generation. Returns summary if within quota, raises HTTPException if exceeded."""
        summary = await self.get_tenant_quota_summary(tenant_id)
        if summary["gross_raw_used_bytes"] + content_bytes > summary["quota_limit_bytes"]:
            remaining_bytes = max(
                summary["quota_limit_bytes"] - summary["gross_raw_used_bytes"], 0
            )
            content_mb_rounded = round(content_bytes / (1024 * 1024), 2)
            limit_mb_rounded = round(summary["quota_limit_bytes"] / (1024 * 1024), 2)
            remaining_mb_rounded = round(remaining_bytes / (1024 * 1024), 2)
            cycle_label = summary.get("quota_cycle", "monthly")
            raise HTTPException(
                status_code=409,
                detail={
                    "code": KB_QUOTA_EXCEEDED_CODE,
                    "message": f"Cannot add {item_label}. You have {remaining_mb_rounded} MB left but this content uses {content_mb_rounded} MB. Your {cycle_label} upload limit is {limit_mb_rounded} MB. Please ask your admin to increase the limit.",
                },
            )
        if summary["raw_used_bytes"] + content_bytes > summary["storage_quota_limit_bytes"]:
            remaining_bytes = max(
                summary["storage_quota_limit_bytes"] - summary["raw_used_bytes"], 0
            )
            content_mb_rounded = round(content_bytes / (1024 * 1024), 2)
            limit_mb_rounded = round(summary["storage_quota_limit_bytes"] / (1024 * 1024), 2)
            remaining_mb_rounded = round(remaining_bytes / (1024 * 1024), 2)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": KB_QUOTA_EXCEEDED_CODE,
                    "message": f"Cannot add {item_label}. You have {remaining_mb_rounded} MB storage left but this content uses {content_mb_rounded} MB. Your storage limit is {limit_mb_rounded} MB. Please delete existing content or ask your admin to increase the limit.",
                },
            )
        return summary

    async def fail_if_tenant_quota_breached_after_processing(
        self,
        tenant_id: str,
        final_total_bytes: int,
        item_label: str,
    ) -> None:
        summary = await self.get_tenant_quota_summary(tenant_id)
        if final_total_bytes > summary["storage_quota_limit_bytes"]:
            final_mb = round(final_total_bytes / (1024 * 1024), 2)
            limit_mb = round(summary["storage_quota_limit_bytes"] / (1024 * 1024), 2)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": KB_QUOTA_EXCEEDED_CODE,
                    "message": f"Cannot add {item_label}. This would exceed your storage limit of {limit_mb} MB ({final_mb} MB used). Please delete existing content or ask your admin to increase the limit.",
                },
            )

    def _raise_quota_exceeded(
        self,
        summary: Dict[str, Any],
        requested_bytes: int,
        limit_type: str = "upload",
    ) -> None:
        requested_mb = round(requested_bytes / (1024 * 1024), 2)
        if limit_type == "storage":
            limit_mb = round(summary["storage_quota_limit_bytes"] / (1024 * 1024), 2)
            message = f"Cannot add this content ({requested_mb} MB). Your storage limit is {limit_mb} MB. Please delete existing content or ask your admin to increase the limit."
        else:
            limit_mb = round(summary["quota_limit_bytes"] / (1024 * 1024), 2)
            cycle_label = summary.get("quota_cycle", "monthly")
            message = f"Cannot add this content ({requested_mb} MB). Your {cycle_label} upload limit is {limit_mb} MB. Please ask your admin to increase the limit."
        raise HTTPException(
            status_code=409,
            detail={
                "code": KB_QUOTA_EXCEEDED_CODE,
                "message": message,
            },
        )

    async def _get_tenant_row(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        query = text(
            """
            SELECT id, slug, name, created_at
            FROM tenants
            WHERE id = :tenant_id
            """
        )
        async with get_db_session() as session:
            row = (
                (await session.execute(query, {"tenant_id": tenant_id}))
                .mappings()
                .first()
            )
            return dict(row) if row else None

    def _build_quota_window(
        self,
        tenant_id: str,
        tenant_created_at: datetime,
        now: datetime,
        quota_cycle: str = "monthly",
    ) -> TenantQuotaWindow:
        tenant_created_at_utc = tenant_created_at.astimezone(timezone.utc)
        now_utc = now.astimezone(timezone.utc)
        if self._normalize_quota_cycle(quota_cycle) == "daily":
            cycle_start_at = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
            cycle_end_at = cycle_start_at + timedelta(days=1)
        else:
            cycle_start_at = now_utc.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            cycle_end_at = self._add_one_month(cycle_start_at)
        return TenantQuotaWindow(
            tenant_id=tenant_id,
            tenant_created_at=tenant_created_at_utc,
            cycle_start_at=cycle_start_at,
            cycle_end_at=cycle_end_at,
        )

    def _add_one_month(self, value: datetime) -> datetime:
        year = value.year + (1 if value.month == 12 else 0)
        month = 1 if value.month == 12 else value.month + 1
        day = value.day
        while True:
            try:
                return value.replace(year=year, month=month, day=day)
            except ValueError:
                day -= 1
                if day <= 0:
                    return (
                        value.replace(year=year, month=month, day=1)
                        + timedelta(days=31)
                    ).replace(day=1)

    async def _get_or_create_monthly_override(
        self,
        tenant_id: str,
        window: TenantQuotaWindow,
    ) -> Dict[str, Any]:
        query = text(
            """
            WITH config AS (
                SELECT COALESCE(
                    (SELECT quota_limit_kb FROM tenant_kb_quota_config WHERE tenant_id = :tenant_id),
                    :default_limit_kb
                ) AS quota_limit_kb
            )
            INSERT INTO tenant_kb_quota_monthly_usage (
                tenant_id,
                cycle_start_at,
                cycle_end_at,
                quota_limit_kb,
                reset_usage_at,
                manual_reset_count,
                created_at,
                updated_at
            )
            SELECT
                :tenant_id,
                :cycle_start_at,
                :cycle_end_at,
                config.quota_limit_kb,
                :cycle_start_at,
                0,
                NOW(),
                NOW()
            FROM config
            ON CONFLICT (tenant_id, cycle_start_at) DO UPDATE
            SET cycle_end_at = EXCLUDED.cycle_end_at,
                quota_limit_kb = EXCLUDED.quota_limit_kb,
                updated_at = NOW()
            RETURNING tenant_id, cycle_start_at, cycle_end_at, quota_limit_kb, reset_usage_at, manual_reset_count, last_manual_reset_at
            """
        )
        params = {
            "tenant_id": tenant_id,
            "cycle_start_at": window.cycle_start_at,
            "cycle_end_at": window.cycle_end_at,
            "default_limit_kb": DEFAULT_MONTHLY_LIMIT_KB,
        }
        async with get_db_session() as session:
            row = (await session.execute(query, params)).mappings().first()
            await session.commit()
        return dict(row)

    def _normalize_quota_cycle(self, quota_cycle: Optional[str]) -> str:
        normalized = str(quota_cycle or "monthly").strip().lower()
        if normalized not in VALID_QUOTA_CYCLES:
            raise HTTPException(
                status_code=400, detail="Quota cycle must be daily or monthly"
            )
        return normalized

    async def _get_or_create_quota_config(self, tenant_id: str) -> Dict[str, Any]:
        query = text(
            """
            INSERT INTO tenant_kb_quota_config (
                tenant_id,
                quota_limit_kb,
                storage_quota_limit_kb,
                quota_cycle,
                created_at,
                updated_at
            )
            VALUES (:tenant_id, :default_limit_kb, :default_limit_kb, 'monthly', NOW(), NOW())
            ON CONFLICT (tenant_id) DO UPDATE
            SET updated_at = tenant_kb_quota_config.updated_at
            RETURNING tenant_id, quota_limit_kb, storage_quota_limit_kb, quota_cycle
            """
        )
        async with get_db_session() as session:
            row = (
                await session.execute(
                    query,
                    {
                        "tenant_id": tenant_id,
                        "default_limit_kb": DEFAULT_MONTHLY_LIMIT_KB,
                    },
                )
            ).mappings().first()
            await session.commit()
        return dict(row)

    async def _get_latest_manual_reset(
        self, tenant_id: str
    ) -> Optional[Dict[str, Any]]:
        query = text(
            """
            SELECT cycle_start_at, cycle_end_at
            FROM tenant_kb_quota_monthly_usage
            WHERE tenant_id = :tenant_id
              AND manual_reset_count > 0
              AND cycle_start_at > NOW() - INTERVAL '2 months'
            ORDER BY cycle_start_at DESC
            LIMIT 1
            """
        )
        async with get_db_session() as session:
            row = (
                (await session.execute(query, {"tenant_id": tenant_id}))
                .mappings()
                .first()
            )
        return dict(row) if row else None

    async def _get_usage_bytes_for_window(
        self, tenant_id: str, window: TenantQuotaWindow
    ) -> int:
        query = text(
            """
            WITH usage_window AS (
                SELECT reset_usage_at, cycle_end_at
                FROM tenant_kb_quota_monthly_usage
                WHERE tenant_id = :tenant_id
                  AND cycle_start_at = :cycle_start_at
            ),
            file_chunk_usage AS (
                SELECT
                    dc.document_id,
                    COALESCE(SUM(pg_column_size(dc.content)), 0) AS chunk_bytes
                FROM document_chunks dc
                WHERE dc.document_type = 'file'
                GROUP BY dc.document_id
            ),
            website_chunk_usage AS (
                SELECT
                    dc.document_id,
                    COALESCE(SUM(pg_column_size(dc.content)), 0) AS chunk_bytes
                FROM document_chunks dc
                WHERE dc.document_type = 'website'
                GROUP BY dc.document_id
            ),
            file_usage AS (
                SELECT COALESCE(SUM(COALESCE(fcu.chunk_bytes, fu.file_size, 0)), 0) AS total_bytes
                FROM file_uploads fu
                CROSS JOIN usage_window
                LEFT JOIN file_chunk_usage fcu ON fcu.document_id = fu.id
                WHERE fu.tenant_id = :tenant_id
                  AND fu.processing_status IN ('completed', 'deleted')
                  AND COALESCE(fu.completed_at, fu.updated_at, fu.created_at) >= usage_window.reset_usage_at
                  AND COALESCE(fu.completed_at, fu.updated_at, fu.created_at) < usage_window.cycle_end_at
            ),
            website_usage AS (
                SELECT COALESCE(SUM(COALESCE(wcu.chunk_bytes, sw.file_size, 0)), 0) AS total_bytes
                FROM scraped_websites sw
                CROSS JOIN usage_window
                LEFT JOIN website_chunk_usage wcu ON wcu.document_id = sw.id
                WHERE sw.tenant_id = :tenant_id
                  AND sw.processing_status IN ('completed', 'deleted')
                  AND COALESCE(sw.completed_at, sw.updated_at, sw.created_at) >= usage_window.reset_usage_at
                  AND COALESCE(sw.completed_at, sw.updated_at, sw.created_at) < usage_window.cycle_end_at
                  AND sw.parent_id IS NULL
            )
            SELECT COALESCE((SELECT total_bytes FROM file_usage), 0) + COALESCE((SELECT total_bytes FROM website_usage), 0) AS total_bytes
            """
        )
        async with get_db_session() as session:
            total = (
                await session.execute(
                    query,
                    {"tenant_id": tenant_id, "cycle_start_at": window.cycle_start_at},
                )
            ).scalar()
        return int(total or 0)

    async def _get_live_usage_bytes(self, tenant_id: str) -> int:
        query = text(
            """
            WITH file_usage AS (
                SELECT COALESCE(SUM(pg_column_size(dc.content)), 0) AS total_bytes
                FROM file_uploads fu
                JOIN document_chunks dc
                  ON dc.document_id = fu.id
                 AND dc.document_type = 'file'
                WHERE fu.tenant_id = :tenant_id
                  AND fu.processing_status = 'completed'
            ),
            website_usage AS (
                SELECT COALESCE(SUM(pg_column_size(dc.content)), 0) AS total_bytes
                FROM scraped_websites sw
                JOIN document_chunks dc
                  ON dc.document_id = sw.id
                 AND dc.document_type = 'website'
                WHERE sw.tenant_id = :tenant_id
                  AND sw.processing_status = 'completed'
                  AND sw.parent_id IS NULL
            )
            SELECT COALESCE((SELECT total_bytes FROM file_usage), 0) + COALESCE((SELECT total_bytes FROM website_usage), 0) AS total_bytes
            """
        )
        async with get_db_session() as session:
            total = (await session.execute(query, {"tenant_id": tenant_id})).scalar()
        return int(total or 0)


kb_quota_service = KBQuotaService()
