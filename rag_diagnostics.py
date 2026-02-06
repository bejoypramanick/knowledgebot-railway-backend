#!/usr/bin/env python3
"""
RAG Diagnostics Script
Checks what's in Gemini FileSearch and PostgreSQL database
"""

import asyncio
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def check_gemini_file_search():
    """Check what documents are in Gemini FileSearch store"""
    print("\n" + "="*80)
    print("🔍 GEMINI FILE SEARCH DIAGNOSTICS")
    print("="*80)

    try:
        from google.genai import Client

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("❌ GEMINI_API_KEY not set")
            return

        client = Client(api_key=api_key)
        store_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")

        print(f"\n📂 Looking for FileSearch store: {store_name}")

        # List all stores
        print("\n📋 All FileSearch stores:")
        stores = list(client.file_search_stores.list())
        print(f"   Total stores: {len(stores)}")

        target_store = None
        for idx, store in enumerate(stores):
            display_name = getattr(store, 'display_name', None)
            print(f"\n   [{idx+1}] Store ID: {store.name}")
            print(f"       Display Name: {display_name}")

            if display_name == store_name:
                target_store = store
                print(f"       ✅ MATCH!")

        if not target_store:
            print(f"\n❌ FileSearch store '{store_name}' not found!")
            return

        print(f"\n✅ Found target store: {target_store.name}")

        # List documents in the store
        print(f"\n📄 Documents in FileSearch store:")
        try:
            documents = list(client.file_search_stores.list_files(name=target_store.name))
            print(f"   Total documents: {len(documents)}")

            if len(documents) == 0:
                print("   ⚠️  NO DOCUMENTS IN STORE!")
            else:
                for idx, doc in enumerate(documents[:10]):  # Show first 10
                    print(f"\n   [{idx+1}] Document ID: {doc.name if hasattr(doc, 'name') else 'N/A'}")
                    if hasattr(doc, 'display_name'):
                        print(f"       Display Name: {doc.display_name}")
                    if hasattr(doc, 'metadata'):
                        print(f"       Metadata: {doc.metadata}")
                    if hasattr(doc, 'size_bytes'):
                        print(f"       Size: {doc.size_bytes} bytes")

                if len(documents) > 10:
                    print(f"\n   ... and {len(documents) - 10} more documents")
        except Exception as e:
            print(f"   ⚠️  Could not list files: {e}")

    except Exception as e:
        print(f"❌ Error checking Gemini: {e}")
        import traceback
        traceback.print_exc()


async def check_database():
    """Check what files are recorded in PostgreSQL"""
    print("\n" + "="*80)
    print("🗄️  DATABASE DIAGNOSTICS")
    print("="*80)

    try:
        from shared.db import get_db_connection

        async with get_db_connection() as conn:
            # Get file uploads
            print("\n📁 Files in file_uploads table:")
            files = await conn.fetch("SELECT id, original_filename, gemini_file_name, gemini_state, created_at FROM file_uploads ORDER BY created_at DESC LIMIT 10")

            if not files:
                print("   ⚠️  NO FILES IN DATABASE!")
            else:
                print(f"   Total files (showing 10): {len(files)}")
                for idx, file in enumerate(files):
                    print(f"\n   [{idx+1}] ID: {file['id']}")
                    print(f"       Filename: {file['original_filename']}")
                    print(f"       Gemini File: {file['gemini_file_name']}")
                    print(f"       State: {file['gemini_state']}")
                    print(f"       Created: {file['created_at']}")

            # Check total count
            total_count = await conn.fetchval("SELECT COUNT(*) FROM file_uploads")
            print(f"\n   📊 Total files in database: {total_count}")

    except Exception as e:
        print(f"❌ Error checking database: {e}")
        import traceback
        traceback.print_exc()


async def test_rag_search():
    """Test RAG search with a simple query"""
    print("\n" + "="*80)
    print("🧪 RAG SEARCH TEST")
    print("="*80)

    try:
        from google.genai import Client, types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("❌ GEMINI_API_KEY not set")
            return

        from shared.file_search import get_file_search_store_by_display_name

        client = Client(api_key=api_key)
        store_id = get_file_search_store_by_display_name(
            client,
            display_name="knowledgebot-search-store"
        )

        if not store_id:
            print("❌ Could not resolve FileSearch store")
            return

        print(f"\n✅ Using store: {store_id}")

        # Try a simple test query
        test_query = "What is in the knowledge base?"
        print(f"\n🔎 Test query: '{test_query}'")

        file_search_tool = types.Tool(
            file_search=types.FileSearch(
                file_search_store_names=[store_id]
            )
        )

        response = client.models.generate_content(
            model="gemini-2.5-flash-lite",
            contents=test_query,
            config=types.GenerateContentConfig(
                tools=[file_search_tool],
                temperature=0.7
            )
        )

        print(f"\n📄 Response ({len(response.text)} chars):")
        print(f"   {response.text[:500]}")

        if hasattr(response, 'grounding_metadata'):
            print(f"\n📚 Grounding metadata: {response.grounding_metadata}")
        else:
            print("\n⚠️  No grounding metadata")

    except Exception as e:
        print(f"❌ Error testing RAG: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Run all diagnostics"""
    print("\n🚀 RAG DIAGNOSTICS STARTING")
    print("This script checks what's in your knowledge base")

    await check_gemini_file_search()
    await check_database()
    await test_rag_search()

    print("\n" + "="*80)
    print("✅ DIAGNOSTICS COMPLETE")
    print("="*80)
    print("\nTo fix RAG search issues:")
    print("1. Ensure files are uploaded using the batch upload endpoint")
    print("2. Check that files are marked as ACTIVE in Gemini")
    print("3. Try re-uploading a test document")
    print("4. Check API Gateway logs for FileSearch store initialization")


if __name__ == "__main__":
    asyncio.run(main())
