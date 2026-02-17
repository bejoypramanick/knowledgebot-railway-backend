FROM redis:7-alpine

# Health check
HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD redis-cli ping

# Enable persistence and AOF for data durability
CMD ["redis-server", "--appendonly", "yes", "--maxmemory", "512mb", "--maxmemory-policy", "allkeys-lru"]
