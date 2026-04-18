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

DEFAULT_MONTHLY_LIMIT_KB = 1024 * 100
KB_QUOTA_EXCEEDED_CODE = "kb_quota_exceeded"


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

        now = datetime.now(timezone.utc)
        window = self._build_quota_window(tenant_id, tenant["created_at"], now)

        latest_reset = await self._get_latest_manual_reset(tenant_id)
        if latest_reset and latest_reset["cycle_start_at"] > window.cycle_start_at:
            window = TenantQuotaWindow(
                tenant_id=tenant_id,
                tenant_created_at=tenant["created_at"],
                cycle_start_at=latest_reset["cycle_start_at"],
                cycle_end_at=latest_reset["cycle_end_at"],
            )

        logger.info(
            f"🔍 [KB_QUOTA] Quota window: cycle_start={window.cycle_start_at}, cycle_end={window.cycle_end_at}"
        )

        override = await self._get_or_create_monthly_override(tenant_id, window)
        logger.info(f"🔍 [KB_QUOTA] Override config: {override}")

        usage_bytes = await self._get_usage_bytes_for_window(tenant_id, window)
        logger.info(f"🔍 [KB_QUOTA] Usage bytes: {usage_bytes}")

        limit_kb = int(override["quota_limit_kb"] or DEFAULT_MONTHLY_LIMIT_KB)
        limit_bytes = limit_kb * 1024
        remaining_bytes = max(limit_bytes - usage_bytes, 0)

        summary = {
            "tenant_id": tenant_id,
            "tenant_slug": tenant["slug"],
            "tenant_name": tenant["name"],
            "quota_limit_kb": limit_kb,
            "quota_limit_bytes": limit_bytes,
            "used_bytes": usage_bytes,
            "used_kb": round(usage_bytes / 1024, 2),
            "remaining_bytes": remaining_bytes,
            "remaining_kb": round(remaining_bytes / 1024, 2),
            "usage_percent": round((usage_bytes / limit_bytes) * 100, 2)
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
            "is_limit_reached": usage_bytes >= limit_bytes,
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
        self, tenant_id: str, quota_limit_kb: int
    ) -> Dict[str, Any]:
        if quota_limit_kb <= 0:
            raise HTTPException(
                status_code=400, detail="Quota limit must be greater than 0 KB"
            )

        query = text(
            """
            INSERT INTO tenant_kb_quota_config (tenant_id, quota_limit_kb, created_at, updated_at)
            VALUES (:tenant_id, :quota_limit_kb, NOW(), NOW())
            ON CONFLICT (tenant_id) DO UPDATE
            SET quota_limit_kb = EXCLUDED.quota_limit_kb,
                updated_at = NOW()
            """
        )
        async with get_db_session() as session:
            await session.execute(
                query, {"tenant_id": tenant_id, "quota_limit_kb": quota_limit_kb}
            )
            await session.commit()

        return await self.get_tenant_quota_summary(tenant_id)

    async def manual_reset_tenant_quota(
        self, tenant_id: str, new_limit_kb: Optional[int] = None
    ) -> Dict[str, Any]:
        tenant = await self._get_tenant_row(tenant_id)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")

        now = datetime.now(timezone.utc)
        limit_kb = int(new_limit_kb or DEFAULT_MONTHLY_LIMIT_KB)

        new_cycle_start = now
        new_cycle_end = self._add_one_month(now)

        query = text(
            """
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
            VALUES (
                :tenant_id,
                :cycle_start_at,
                :cycle_end_at,
                :quota_limit_kb,
                :reset_usage_at,
                1,
                NOW(),
                NOW(),
                NOW()
            )
            ON CONFLICT (tenant_id, cycle_start_at) DO UPDATE
            SET quota_limit_kb = EXCLUDED.quota_limit_kb,
                cycle_end_at = EXCLUDED.cycle_end_at,
                reset_usage_at = EXCLUDED.reset_usage_at,
                manual_reset_count = EXCLUDED.manual_reset_count,
                last_manual_reset_at = EXCLUDED.last_manual_reset_at,
                updated_at = NOW()
            """
        )
        async with get_db_session() as session:
            await session.execute(
                query,
                {
                    "tenant_id": tenant_id,
                    "cycle_start_at": new_cycle_start,
                    "cycle_end_at": new_cycle_end,
                    "quota_limit_kb": limit_kb,
                    "reset_usage_at": now,
                },
            )
            await session.commit()

        return await self.get_tenant_quota_summary(tenant_id)

    async def ensure_upload_within_quota(
        self, tenant_id: str, requested_bytes: int
    ) -> Dict[str, Any]:
        summary = await self.get_tenant_quota_summary(tenant_id)
        if summary["used_bytes"] + requested_bytes > summary["quota_limit_bytes"]:
            self._raise_quota_exceeded(summary, requested_bytes)
        return summary

    async def check_quota_before_embedding(
        self, tenant_id: str, content_bytes: int, item_label: str = "This content"
    ) -> Dict[str, Any]:
        """Check quota right before embedding generation. Returns summary if within quota, raises HTTPException if exceeded."""
        summary = await self.get_tenant_quota_summary(tenant_id)
        if summary["used_bytes"] + content_bytes > summary["quota_limit_bytes"]:
            remaining_bytes = max(
                summary["quota_limit_bytes"] - summary["used_bytes"], 0
            )
            remaining_kb = round(remaining_bytes / 1024, 2)
            raise HTTPException(
                status_code=409,
                detail={
                    "code": KB_QUOTA_EXCEEDED_CODE,
                    "message": f"{item_label} cannot be processed. Adding this content ({round(content_bytes / 1024, 2)} KB) would exceed your monthly KB quota ({round(summary['quota_limit_bytes'] / 1024, 2)} KB). You have {remaining_kb} KB remaining. Please delete some existing content or contact your administrator to reset the quota.",
                    "tenant_id": tenant_id,
                    "quota": summary,
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
        if final_total_bytes > summary["quota_limit_bytes"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": KB_QUOTA_EXCEEDED_CODE,
                    "message": f"{item_label} exceeded this tenant's monthly knowledge base quota.",
                    "tenant_id": tenant_id,
                    "quota": summary,
                },
            )

    def _raise_quota_exceeded(
        self, summary: Dict[str, Any], requested_bytes: int
    ) -> None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": KB_QUOTA_EXCEEDED_CODE,
                "message": "Monthly knowledge base quota reached. Uploads and website scraping are blocked until the next reset or a manual reset by superadmin.",
                "requested_bytes": requested_bytes,
                "quota": summary,
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
    ) -> TenantQuotaWindow:
        anchor = tenant_created_at.astimezone(timezone.utc)
        cursor = anchor

        while True:
            next_cursor = self._add_one_month(cursor)
            if now < next_cursor:
                return TenantQuotaWindow(
                    tenant_id=tenant_id,
                    tenant_created_at=anchor,
                    cycle_start_at=cursor,
                    cycle_end_at=next_cursor,
                )
            cursor = next_cursor

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
            file_usage AS (
                SELECT COALESCE(SUM(char_count), 0) AS total_bytes
                FROM file_uploads, usage_window
                WHERE tenant_id = :tenant_id
                  AND completed_at >= usage_window.reset_usage_at
                  AND completed_at < usage_window.cycle_end_at
            ),
            website_usage AS (
                SELECT COALESCE(SUM(char_count), 0) AS total_bytes
                FROM scraped_websites, usage_window
                WHERE tenant_id = :tenant_id
                  AND completed_at >= usage_window.reset_usage_at
                  AND completed_at < usage_window.cycle_end_at
                  AND parent_id IS NULL
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


kb_quota_service = KBQuotaService()
