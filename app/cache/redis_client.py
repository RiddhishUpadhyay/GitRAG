import logging
import json
import hashlib
from typing import Dict, Any, Optional
import redis

from app.config import settings

logger = logging.getLogger(__name__)

class RedisClientManager:
    _client: Optional[redis.Redis] = None

    def get_client(self) -> Optional[redis.Redis]:
        """Lazy-loaded Redis client singleton."""
        if self._client is None:
            if not settings.REDIS_URL:
                logger.warning("REDIS_URL is not set. Redis operations are disabled.")
                return None
            try:
                # Upstash URL usually begins with rediss:// for SSL
                self._client = redis.Redis.from_url(
                    settings.REDIS_URL, 
                    decode_responses=False # Decode manually or in helpers to avoid binary confusion
                )
                self._client.ping()
                logger.info("Successfully connected to Redis server.")
            except Exception as e:
                logger.error(f"Failed to connect to Redis at {settings.REDIS_URL}: {e}")
                self._client = None
        return self._client

    # --- Job Status & Progress helpers ---
    
    def set_job_progress(self, job_id: str, message: str, ttl: int = 86400):
        """Sets a progress message for a running background job."""
        client = self.get_client()
        if client:
            try:
                client.setex(f"progress:{job_id}", ttl, message)
            except Exception as e:
                logger.warning(f"Failed to set job progress in Redis: {e}")

    def get_job_progress(self, job_id: str) -> str:
        """Retrieves a progress message for a job."""
        client = self.get_client()
        if client:
            try:
                val = client.get(f"progress:{job_id}")
                return val.decode("utf-8") if val else "Queued..."
            except Exception as e:
                logger.warning(f"Failed to get job progress from Redis: {e}")
        return "Unknown status"

    # --- File Hash Sync State helpers ---
    
    def save_file_hashes(self, repo_id: str, file_hashes: Dict[str, str]):
        """Saves file paths and their MD5 hashes to Redis for a repo."""
        client = self.get_client()
        if client:
            key = f"repo_files:{repo_id}"
            try:
                # We can store them in a hash structure
                if file_hashes:
                    # Clean old values first
                    client.delete(key)
                    # Convert keys and values to strings/bytes
                    payload = {k: v for k, v in file_hashes.items()}
                    client.hset(key, mapping=payload)
                else:
                    client.delete(key)
            except Exception as e:
                logger.warning(f"Failed to save file hashes to Redis: {e}")

    def get_file_hashes(self, repo_id: str) -> Dict[str, str]:
        """Retrieves previously indexed file path -> hash mapping from Redis."""
        client = self.get_client()
        if client:
            key = f"repo_files:{repo_id}"
            try:
                stored = client.hgetall(key)
                return {k.decode("utf-8"): v.decode("utf-8") for k, v in stored.items()}
            except Exception as e:
                logger.warning(f"Failed to retrieve file hashes from Redis: {e}")
        return {}

    def delete_repo_metadata(self, repo_id: str):
        """Deletes all Redis metadata and cache linked to a repository."""
        client = self.get_client()
        if client:
            try:
                client.delete(f"repo_files:{repo_id}")
                client.hdel("repos", repo_id)
                # Clear all cached queries for this repo
                keys = client.keys(f"query_cache:{repo_id}:*")
                if keys:
                    client.delete(*keys)
                logger.info(f"Cleared Redis metadata for repo {repo_id}")
            except Exception as e:
                logger.warning(f"Failed to delete repo metadata from Redis: {e}")

# Global singleton
redis_client = RedisClientManager()
