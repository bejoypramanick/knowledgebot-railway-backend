"""
Migration script to fix sitemap records that were incorrectly classified.

This script updates the metadata.scraping_config.source field for URLs
that are sitemaps but were classified as 'single' or 'website'.

Run with: python scripts/fix_sitemap_metadata.py
"""
import asyncio
import asyncpg
import os
import json
from typing import List, Dict, Any


async def fix_sitemap_metadata():
    """Update sitemap records with correct source type."""
    
    # Get database URL from environment
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        print("❌ DATABASE_URL environment variable not set")
        return
    
    # Ensure SSL mode
    if 'sslmode=' not in database_url:
        database_url += '&sslmode=require' if '?' in database_url else '?sslmode=require'
    
    print("🔌 Connecting to database...")
    conn = await asyncpg.connect(database_url)
    
    try:
        # Find all records that look like sitemaps but aren't classified as such
        print("\n🔍 Finding sitemap URLs with incorrect classification...")
        
        query = """
            SELECT id, original_url, metadata
            FROM scraped_websites
            WHERE (
                LOWER(original_url) LIKE '%sitemap.xml' OR
                LOWER(original_url) LIKE '%sitemap.xml.gz' OR
                LOWER(original_url) LIKE '%sitemap_index.xml' OR
                LOWER(original_url) LIKE '%sitemap%.xml'
            )
            AND processing_status != 'deleted'
        """
        
        records = await conn.fetch(query)
        print(f"📊 Found {len(records)} sitemap URLs")
        
        if not records:
            print("✅ No records to update")
            return
        
        # Check which ones need updating
        to_update: List[Dict[str, Any]] = []
        
        for record in records:
            metadata = record['metadata']
            if metadata and isinstance(metadata, dict):
                scraping_config = metadata.get('scraping_config', {})
                current_source = scraping_config.get('source')
                
                if current_source != 'sitemap':
                    to_update.append({
                        'id': record['id'],
                        'url': record['original_url'],
                        'current_source': current_source,
                        'metadata': metadata
                    })
        
        print(f"\n📝 Records needing update: {len(to_update)}")
        
        if not to_update:
            print("✅ All sitemap records already have correct classification")
            return
        
        # Show what will be updated
        print("\n🔄 Will update the following records:")
        for item in to_update:
            print(f"   ID {item['id']}: {item['url']}")
            print(f"      Current: {item['current_source']} → New: sitemap")
        
        # Ask for confirmation
        response = input("\n⚠️  Proceed with update? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Update cancelled")
            return
        
        # Update records
        print("\n🔄 Updating records...")
        updated_count = 0
        
        for item in to_update:
            # Update metadata
            metadata = item['metadata']
            if 'scraping_config' not in metadata:
                metadata['scraping_config'] = {}
            metadata['scraping_config']['source'] = 'sitemap'
            
            # Update in database
            update_query = """
                UPDATE scraped_websites
                SET metadata = $1::jsonb,
                    updated_at = NOW()
                WHERE id = $2
            """
            
            await conn.execute(update_query, json.dumps(metadata), item['id'])
            updated_count += 1
            print(f"   ✅ Updated ID {item['id']}")
        
        print(f"\n✅ Successfully updated {updated_count} records")
        print("\n💡 Tip: Refresh your browser to see the changes in the UI")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        await conn.close()
        print("\n🔌 Database connection closed")


if __name__ == "__main__":
    print("=" * 60)
    print("🔧 Sitemap Metadata Fix Script")
    print("=" * 60)
    asyncio.run(fix_sitemap_metadata())
