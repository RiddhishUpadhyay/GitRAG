import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Tuple

from app.config import settings
from app.cache.redis_client import redis_client

logger = logging.getLogger(__name__)

def compute_file_hash(file_path: Path) -> str:
    """Computes the MD5 hash of a file's content."""
    hasher = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception as e:
        logger.error(f"Failed to compute hash for {file_path}: {e}")
        return ""

def get_local_hashes_path(repo_id: str) -> str:
    return os.path.join(settings.TEMP_DIR, f"{repo_id}_hashes.json")

def load_stored_hashes(repo_id: str, is_local: bool = False) -> Dict[str, str]:
    """Retrieves file path -> hash mapping from Redis or local JSON file."""
    if not is_local:
        stored = redis_client.get_file_hashes(repo_id)
        if stored:
            return stored
            
    # Local fallback
    local_path = get_local_hashes_path(repo_id)
    if os.path.exists(local_path):
        try:
            with open(local_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load local hashes from {local_path}: {e}")
            
    return {}

def save_stored_hashes(repo_id: str, file_hashes: Dict[str, str], is_local: bool = False):
    """Saves file path -> hash mapping to Redis and local JSON file."""
    if not is_local:
        redis_client.save_file_hashes(repo_id, file_hashes)
        
    # Always save local copy for durability
    local_path = get_local_hashes_path(repo_id)
    try:
        with open(local_path, "w", encoding="utf-8") as f:
            json.dump(file_hashes, f)
    except Exception as e:
        logger.error(f"Failed to save local hashes to {local_path}: {e}")

def delete_stored_hashes(repo_id: str):
    """Deletes stored hashes for a repository."""
    redis_client.delete_repo_metadata(repo_id)
    local_path = get_local_hashes_path(repo_id)
    if os.path.exists(local_path):
        try:
            os.remove(local_path)
        except Exception as e:
            logger.error(f"Failed to remove local hash file {local_path}: {e}")

def calculate_diff(
    repo_path: Path, 
    current_files: List[Path], 
    old_hashes: Dict[str, str]
) -> Tuple[List[str], List[str], List[str], Dict[str, str]]:
    """
    Compares disk file state with previous index hashes.
    
    Returns:
        new_files: Files present on disk but not in old_hashes.
        modified_files: Files present in both but with changed hashes.
        deleted_files: Files in old_hashes but no longer on disk.
        current_hashes: Map of current relative path -> current hash.
    """
    new_files = []
    modified_files = []
    current_hashes = {}
    
    disk_rel_paths = set()
    
    for file_path in current_files:
        rel_path = str(file_path.relative_to(repo_path)).replace("\\", "/")
        disk_rel_paths.add(rel_path)
        
        file_hash = compute_file_hash(file_path)
        current_hashes[rel_path] = file_hash
        
        if rel_path not in old_hashes:
            new_files.append(rel_path)
        elif old_hashes[rel_path] != file_hash:
            modified_files.append(rel_path)
            
    # Deleted files are in old hashes but not on disk anymore
    deleted_files = [path for path in old_hashes.keys() if path not in disk_rel_paths]
    
    logger.info(
        f"Diff sync results: {len(new_files)} new, "
        f"{len(modified_files)} modified, {len(deleted_files)} deleted files."
    )
    
    return new_files, modified_files, deleted_files, current_hashes
