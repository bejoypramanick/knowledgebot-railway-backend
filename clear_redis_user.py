import asyncio
from shared.redis_tenant_auth_cache import (
    invalidate_user_auth_cache,
)
from shared.redis_factory import create_async_redis_client
import sys

async def main(email):
    print(f"Invalidating cache for {email}...")
    await invalidate_user_auth_cache(email)
    print("Done.")

if __name__ == "__main__":
    asyncio.run(main("ceo@globistaan.com"))
