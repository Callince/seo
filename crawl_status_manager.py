"""
Crawl Status Manager - Redis-based shared state for multi-worker Gunicorn
This module provides a thread-safe, multi-worker compatible crawl status tracker
"""

import redis
import json
import time
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class CrawlStatusManager:
    """
    Manages crawl job status across multiple Gunicorn workers using Redis
    """

    def __init__(self, redis_host='localhost', redis_port=6379, redis_db=1, redis_password=None):
        """
        Initialize Redis connection for crawl status management

        Args:
            redis_host: Redis server host
            redis_port: Redis server port
            redis_db: Redis database number (use different from cache)
            redis_password: Redis password if authentication is enabled
        """
        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                db=redis_db,
                password=redis_password,
                decode_responses=True,  # Automatically decode responses to strings
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            # Test connection
            self.redis_client.ping()
            logger.info(f"✅ Connected to Redis at {redis_host}:{redis_port} (db={redis_db})")
        except redis.ConnectionError as e:
            logger.error(f"❌ Failed to connect to Redis: {e}")
            logger.warning("⚠️  Falling back to in-memory storage (NOT suitable for multi-worker)")
            self.redis_client = None
            self._fallback_storage = {}

    def _get_key(self, job_id: str) -> str:
        """Generate Redis key for a job_id"""
        return f"crawl_status:{job_id}"

    def set_status(self, job_id: str, status_data: Dict[str, Any], expire_seconds: int = 86400):
        """
        Set crawl status for a job

        Args:
            job_id: Unique job identifier
            status_data: Dictionary containing status information
            expire_seconds: Time in seconds before the key expires (default: 24 hours)
        """
        try:
            if self.redis_client:
                key = self._get_key(job_id)
                # Store as JSON string
                self.redis_client.setex(
                    key,
                    expire_seconds,
                    json.dumps(status_data)
                )
                logger.debug(f"Set status for job {job_id}: {status_data.get('status', 'unknown')}")
            else:
                # Fallback to in-memory storage
                self._fallback_storage[job_id] = status_data
        except Exception as e:
            logger.error(f"Error setting status for job {job_id}: {e}")

    def get_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """
        Get crawl status for a job

        Args:
            job_id: Unique job identifier

        Returns:
            Dictionary with status data or None if not found
        """
        try:
            if self.redis_client:
                key = self._get_key(job_id)
                data = self.redis_client.get(key)
                if data:
                    return json.loads(data)
                return None
            else:
                # Fallback to in-memory storage
                return self._fallback_storage.get(job_id)
        except Exception as e:
            logger.error(f"Error getting status for job {job_id}: {e}")
            return None

    def update_status(self, job_id: str, updates: Dict[str, Any]):
        """
        Update specific fields in crawl status

        Args:
            job_id: Unique job identifier
            updates: Dictionary with fields to update
        """
        try:
            current_status = self.get_status(job_id)
            if current_status:
                current_status.update(updates)
                self.set_status(job_id, current_status)
                logger.debug(f"Updated job {job_id}: {updates}")
            else:
                logger.warning(f"Cannot update non-existent job {job_id}")
        except Exception as e:
            logger.error(f"Error updating status for job {job_id}: {e}")

    def delete_status(self, job_id: str):
        """
        Delete crawl status for a job

        Args:
            job_id: Unique job identifier
        """
        try:
            if self.redis_client:
                key = self._get_key(job_id)
                self.redis_client.delete(key)
                logger.debug(f"Deleted status for job {job_id}")
            else:
                # Fallback to in-memory storage
                if job_id in self._fallback_storage:
                    del self._fallback_storage[job_id]
        except Exception as e:
            logger.error(f"Error deleting status for job {job_id}: {e}")

    def exists(self, job_id: str) -> bool:
        """
        Check if a job exists

        Args:
            job_id: Unique job identifier

        Returns:
            True if job exists, False otherwise
        """
        try:
            if self.redis_client:
                key = self._get_key(job_id)
                return self.redis_client.exists(key) > 0
            else:
                # Fallback to in-memory storage
                return job_id in self._fallback_storage
        except Exception as e:
            logger.error(f"Error checking existence for job {job_id}: {e}")
            return False

    def get_all_job_ids(self) -> list:
        """
        Get all active job IDs

        Returns:
            List of job IDs
        """
        try:
            if self.redis_client:
                pattern = self._get_key("*")
                keys = self.redis_client.keys(pattern)
                # Extract job_id from keys
                job_ids = [key.replace("crawl_status:", "") for key in keys]
                return job_ids
            else:
                # Fallback to in-memory storage
                return list(self._fallback_storage.keys())
        except Exception as e:
            logger.error(f"Error getting all job IDs: {e}")
            return []

    def cleanup_old_jobs(self, max_age_seconds: int = 86400):
        """
        Clean up jobs older than max_age_seconds

        Args:
            max_age_seconds: Maximum age in seconds (default: 24 hours)

        Returns:
            Number of jobs cleaned up
        """
        try:
            current_time = time.time()
            cleaned_count = 0

            for job_id in self.get_all_job_ids():
                status_data = self.get_status(job_id)
                if status_data:
                    job_age = current_time - status_data.get('start_time', current_time)

                    # Remove old completed/failed jobs
                    job_status = status_data.get('status', 'unknown')
                    if job_status in ['completed', 'failed'] and job_age > max_age_seconds:
                        self.delete_status(job_id)
                        cleaned_count += 1
                        logger.info(f"Cleaned up old job {job_id} (age: {job_age:.0f}s, status: {job_status})")

            if cleaned_count > 0:
                logger.info(f"✅ Cleaned up {cleaned_count} old crawl jobs")

            return cleaned_count

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
            return 0

    def get_stats(self) -> Dict[str, int]:
        """
        Get statistics about crawl jobs

        Returns:
            Dictionary with job counts by status
        """
        try:
            stats = {
                'total': 0,
                'running': 0,
                'completed': 0,
                'failed': 0,
                'unknown': 0
            }

            for job_id in self.get_all_job_ids():
                status_data = self.get_status(job_id)
                if status_data:
                    stats['total'] += 1
                    job_status = status_data.get('status', 'unknown')
                    stats[job_status] = stats.get(job_status, 0) + 1

            return stats

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {'total': 0, 'error': str(e)}


# Backward compatibility wrapper for dictionary-like access
class CrawlStatusDict:
    """
    Provides dictionary-like interface for backward compatibility
    """

    def __init__(self, manager: CrawlStatusManager):
        self.manager = manager

    def __setitem__(self, job_id: str, value: Dict[str, Any]):
        self.manager.set_status(job_id, value)

    def __getitem__(self, job_id: str) -> Dict[str, Any]:
        status = self.manager.get_status(job_id)
        if status is None:
            raise KeyError(f"Job {job_id} not found")
        return status

    def __contains__(self, job_id: str) -> bool:
        return self.manager.exists(job_id)

    def __delitem__(self, job_id: str):
        self.manager.delete_status(job_id)

    def get(self, job_id: str, default=None) -> Optional[Dict[str, Any]]:
        status = self.manager.get_status(job_id)
        return status if status is not None else default

    def keys(self):
        return self.manager.get_all_job_ids()

    def items(self):
        for job_id in self.manager.get_all_job_ids():
            status = self.manager.get_status(job_id)
            if status:
                yield job_id, status

    def values(self):
        for job_id in self.manager.get_all_job_ids():
            status = self.manager.get_status(job_id)
            if status:
                yield status
