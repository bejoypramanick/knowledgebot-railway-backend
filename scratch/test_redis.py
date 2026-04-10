
import asyncio
import os
from shared.redis_ui_cache import init_ui_cache_redis, KB_FILES_KEY_PREFIX

async def test_cache():
    client = await init_ui_cache_redis()
    pattern = f"{KB_FILES_KEY_PREFIX}*"
    print(f"Scanning for pattern: {pattern}")
    
    keys = []
    async for key in client.scan_iter(match=pattern):
        keys.append(key)
        print(f"Found key: {key}")
    
    print(f"Total keys found: {len(keys)}")
    
    # Try with a broader pattern if none found
    if not keys:
        print("Broad search for *kb_files*:")
        async for key in client.scan_iter(match="*kb_files*"):
            print(f"Found broad key: {key}")

if __name__ == "__main__":
    asyncio.run(test_cache())
