#!/usr/bin/env python3
"""
Initialize Gemini FileSearch Store
Run this script to create the FileSearch store for your knowledge base
"""
import os
import sys
from dotenv import load_dotenv
from google.genai import Client

# Load environment variables
load_dotenv()

def main():
    """Create or verify the FileSearch store exists"""

    # Get Gemini API key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ ERROR: GEMINI_API_KEY not found in environment")
        print("Please set GEMINI_API_KEY in your .env file or environment variables")
        sys.exit(1)

    # Get store name
    store_name = os.getenv("GEMINI_FILE_SEARCH_STORE_NAME", "knowledgebot-search-store")
    print(f"📂 Initializing FileSearch store: {store_name}")
    print(f"🔑 Using API key: {api_key[:10]}...")

    try:
        # Initialize Gemini client
        client = Client(api_key=api_key)
        print("✅ Gemini client initialized")

        # Check if file_search_stores API is available
        if not hasattr(client, 'file_search_stores'):
            print("❌ ERROR: file_search_stores API not available in client")
            print("Make sure you're using the latest google-genai package:")
            print("  pip install --upgrade google-genai")
            sys.exit(1)

        # List existing stores
        print("\n📋 Listing existing FileSearch stores...")
        stores = list(client.file_search_stores.list())

        if not stores:
            print("ℹ️  No existing stores found")
        else:
            print(f"ℹ️  Found {len(stores)} existing store(s):")
            for store in stores:
                display = getattr(store, 'display_name', 'Unknown')
                print(f"   - {store.name} ({display})")

        # Check if our store exists
        existing_store = None
        for store in stores:
            if hasattr(store, 'display_name') and store.display_name == store_name:
                existing_store = store
                break

        if existing_store:
            print(f"\n✅ FileSearch store already exists!")
            print(f"   Store ID: {existing_store.name}")
            print(f"   Display Name: {existing_store.display_name}")

            # List files in the store
            try:
                files = list(client.files.list())
                store_files = [f for f in files if hasattr(f, 'file_search_store_name') and
                             existing_store.name in getattr(f, 'file_search_store_name', '')]
                print(f"   Files in store: {len(store_files)}")
            except:
                print(f"   Files in store: Unable to retrieve")

        else:
            print(f"\n🔨 Creating new FileSearch store: {store_name}")
            # Create new store using correct Python client API
            new_store = client.file_search_stores.create(
                config={'display_name': store_name}
            )
            print(f"✅ FileSearch store created: {new_store.name}")
            print(f"   Display name: {getattr(new_store, 'display_name', 'N/A')}")
            return new_store.name

        print("\n🎉 Initialization complete!")
        print(f"   Store Name: {store_name}")
        print(f"   You can now upload files and scrape websites.")
        print(f"\n   Update your .env file with:")
        print(f"   GEMINI_FILE_SEARCH_STORE_NAME={store_name}")

    except Exception as e:
        print(f"\n❌ ERROR: Failed to initialize FileSearch store")
        print(f"   Error: {e}")
        print(f"\nTroubleshooting:")
        print(f"1. Verify your GEMINI_API_KEY is valid")
        print(f"2. Check that your API key has FileSearch API access")
        print(f"3. Ensure you have the latest google-genai package:")
        print(f"   pip install --upgrade google-genai")
        sys.exit(1)

if __name__ == "__main__":
    main()
