#!/usr/bin/env python3
"""
Document Chunks Size Report
Calculates the size of document_chunks content in KB for each file uploaded
or website scraped, along with the number of chunks.
"""

import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Database connection URL (set via DATABASE_URL environment variable)
# Example: postgresql+asyncpg://user:pass@host:5432/dbname
import os

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL environment variable not set")
    print(
        "Usage: DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/dbname python document_chunks_size_report.py"
    )
    exit(1)


async def run_report():
    engine = create_async_engine(DATABASE_URL, echo=False)

    async with engine.connect() as conn:
        print("=" * 100)
        print("DOCUMENT CHUNKS SIZE REPORT")
        print("=" * 100)

        # 1. File Uploads
        print("\n📄 FILE UPLOADS\n")
        query = text("""
            SELECT 
                fu.id AS source_id,
                t.slug AS tenant_slug,
                fu.file_name,
                fu.file_size / 1024.0 AS original_file_size_kb,
                COUNT(dc.id) AS chunk_count,
                LENGTH(string_agg(dc.content, '')) / 1024.0 AS chunks_size_kb
            FROM file_uploads fu
            LEFT JOIN document_chunks dc ON dc.file_id = fu.id
            LEFT JOIN tenants t ON t.id = fu.tenant_id
            WHERE fu.processing_status = 'completed'
            GROUP BY fu.id, t.slug, fu.file_name, fu.file_size
            ORDER BY chunks_size_kb DESC NULLS LAST
            LIMIT 50
        """)
        result = await conn.execute(query)
        rows = result.fetchall()

        print(
            f"{'Tenant':<15} {'File Name':<40} {'Chunks':<8} {'Original KB':<12} {'Chunks KB':<12}"
        )
        print("-" * 90)
        for row in rows:
            chunks_kb = round(row.chunks_size_kb or 0, 2) if row.chunks_size_kb else 0
            print(
                f"{row.tenant_slug:<15} {row.file_name[:38]:<40} {row.chunk_count:<8} {round(row.original_file_size_kb, 2):<12} {chunks_kb:<12}"
            )

        # 2. Scraped Websites
        print("\n🌐 SCRAPED WEBSITES\n")
        query = text("""
            SELECT 
                sw.id AS source_id,
                t.slug AS tenant_slug,
                SUBSTRING(sw.url, 1, 50) AS website_url,
                sw.content_length / 1024.0 AS original_content_size_kb,
                COUNT(dc.id) AS chunk_count,
                LENGTH(string_agg(dc.content, '')) / 1024.0 AS chunks_size_kb
            FROM scraped_websites sw
            LEFT JOIN document_chunks dc ON dc.website_id = sw.id
            LEFT JOIN tenants t ON t.id = sw.tenant_id
            WHERE sw.processing_status = 'completed'
              AND sw.parent_id IS NULL
            GROUP BY sw.id, t.slug, sw.url, sw.content_length
            ORDER BY chunks_size_kb DESC NULLS LAST
            LIMIT 50
        """)
        result = await conn.execute(query)
        rows = result.fetchall()

        print(
            f"{'Tenant':<15} {'Website URL':<50} {'Chunks':<8} {'Original KB':<12} {'Chunks KB':<12}"
        )
        print("-" * 100)
        for row in rows:
            chunks_kb = round(row.chunks_size_kb or 0, 2) if row.chunks_size_kb else 0
            print(
                f"{row.tenant_slug:<15} {row.website_url:<50} {row.chunk_count:<8} {round(row.original_content_size_kb, 2):<12} {chunks_kb:<12}"
            )

        # 3. Summary by Tenant
        print("\n📊 SUMMARY BY TENANT\n")
        query = text("""
            SELECT 
                t.slug AS tenant_slug,
                t.name AS tenant_name,
                COUNT(DISTINCT fu.id) AS total_files,
                COUNT(DISTINCT sw.id) AS total_websites,
                COALESCE(SUM(fu.file_size), 0) / 1024.0 AS total_original_size_kb,
                COUNT(dc.id) AS total_chunks,
                LENGTH(string_agg(dc.content, '')) / 1024.0 AS total_chunks_size_kb
            FROM tenants t
            LEFT JOIN file_uploads fu ON fu.tenant_id = t.id AND fu.processing_status = 'completed'
            LEFT JOIN scraped_websites sw ON sw.tenant_id = t.id AND sw.processing_status = 'completed' AND sw.parent_id IS NULL
            LEFT JOIN document_chunks dc ON dc.file_id = fu.id OR dc.website_id = sw.id
            GROUP BY t.id, t.slug, t.name
            ORDER BY total_chunks_size_kb DESC NULLS LAST
        """)
        result = await conn.execute(query)
        rows = result.fetchall()

        print(
            f"{'Tenant':<15} {'Name':<25} {'Files':<8} {'Websites':<10} {'Chunks':<8} {'Original KB':<15} {'Chunks KB':<15}"
        )
        print("-" * 100)
        for row in rows:
            chunks_kb = (
                round(row.total_chunks_size_kb or 0, 2)
                if row.total_chunks_size_kb
                else 0
            )
            print(
                f"{row.tenant_slug:<15} {row.tenant_name[:23]:<25} {row.total_files:<8} {row.total_websites:<10} {row.total_chunks:<8} {round(row.total_original_size_kb, 2):<15} {chunks_kb:<15}"
            )

        # 4. Grand Total
        print("\n📈 GRAND TOTAL\n")
        query = text("""
            SELECT 
                COUNT(DISTINCT fu.id) AS total_files,
                COUNT(DISTINCT sw.id) AS total_websites,
                COALESCE(SUM(fu.file_size), 0) / 1024.0 AS total_original_size_kb,
                COUNT(dc.id) AS total_chunks,
                LENGTH(string_agg(dc.content, '')) / 1024.0 AS total_chunks_size_kb
            FROM file_uploads fu
            LEFT JOIN scraped_websites sw ON sw.tenant_id = fu.tenant_id AND sw.processing_status = 'completed' AND sw.parent_id IS NULL
            LEFT JOIN document_chunks dc ON dc.file_id = fu.id OR dc.website_id = sw.id
            WHERE fu.processing_status = 'completed'
        """)
        result = await conn.execute(query)
        row = result.fetchone()

        chunks_kb = (
            round(row.total_chunks_size_kb or 0, 2) if row.total_chunks_size_kb else 0
        )
        print(f"Total Files:     {row.total_files}")
        print(f"Total Websites:  {row.total_websites}")
        print(f"Total Chunks:    {row.total_chunks}")
        print(f"Total Original:  {round(row.total_original_size_kb, 2)} KB")
        print(f"Total Chunks KB: {chunks_kb} KB")

        print("\n" + "=" * 100)

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run_report())
