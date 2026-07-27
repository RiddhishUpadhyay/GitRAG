import logging
import os
import uuid
from typing import Dict, Any, List
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel, HttpUrl

from app.config import settings
from app.ingestion.repo_loader import get_repo_id, clean_repo_temp_dir
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api", 
    tags=["ingestion"],
    dependencies=[Depends(get_current_user)]
)

# In-memory status store for BackgroundTasks fallback
local_jobs: Dict[str, Dict[str, Any]] = {}

# Helper to import RQ when needed, preventing startup crashes if Redis/RQ is missing
def get_rq_queue():
    try:
        from redis import Redis
        from rq import Queue
        redis_conn = Redis.from_url(settings.REDIS_URL)
        return Queue("ingest", connection=redis_conn), redis_conn
    except Exception as e:
        logger.warning(f"Could not connect to Redis/RQ queue: {e}")
        return None, None

class IngestRequest(BaseModel):
    repo_url: str

@router.post("/ingest")
async def ingest_repository(
    request: IngestRequest, 
    background_tasks: BackgroundTasks, 
    username: str = Depends(get_current_user)
):
    """Triggers indexing of a GitHub repository."""
    repo_url = request.repo_url.strip()
    if not repo_url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid repository URL. Must start with http/https.")
        
    repo_id = get_repo_id(repo_url)
    
    # Store repository url mapping in user_repos database table
    import sqlite3
    from app.database import get_db_connection
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO user_repos (username, repo_url, repo_id) VALUES (?, ?, ?)",
            (username, repo_url, repo_id)
        )
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"Failed to record user repository in SQLite: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    finally:
        conn.close()
    
    # Try to queue via RQ first
    queue, redis_conn = get_rq_queue()
    if queue and redis_conn:
        try:
            # We import here to avoid circular imports
            from app.jobs.ingest_worker import ingest_repo_job
            job = queue.enqueue(
                ingest_repo_job,
                args=(repo_url, username),
                job_id=f"job_{repo_id}",
                result_ttl=86400, # 1 day
                job_timeout=600   # 10 minutes
            )
            return {"job_id": job.get_id(), "repo_id": repo_id, "mode": "rq"}
        except Exception as e:
            logger.error(f"Failed to queue job on Redis, falling back to BackgroundTasks: {e}")
            
    # Fallback to FastAPI BackgroundTasks
    job_id = f"local_{repo_id}"
    local_jobs[job_id] = {
        "status": "queued",
        "progress": "Starting background job...",
        "repo_url": repo_url
    }
    
    # Launch job
    from app.jobs.ingest_worker import run_ingest_pipeline
    background_tasks.add_task(
        run_ingest_pipeline,
        repo_url=repo_url,
        job_id=job_id,
        is_local=True,
        local_store=local_jobs,
        username=username
    )
    
    return {"job_id": job_id, "repo_id": repo_id, "mode": "background_tasks"}

@router.post("/resync")
async def resync_repository(
    request: IngestRequest, 
    background_tasks: BackgroundTasks,
    username: str = Depends(get_current_user)
):
    """Triggers a manual re-sync for a repository, diffing hashes and re-embedding."""
    return await ingest_repository(request, background_tasks, username)

@router.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """Fetches progress and state of an ingestion job."""
    # Check in-memory store first
    if job_id.startswith("local_"):
        if job_id in local_jobs:
            return local_jobs[job_id]
        raise HTTPException(status_code=404, detail="Job not found in local scheduler.")
        
    # Check RQ
    queue, redis_conn = get_rq_queue()
    if queue and redis_conn:
        try:
            from rq.job import Job
            job = Job.fetch(job_id, connection=redis_conn)
            
            # Fetch custom progress message set during execution
            progress = redis_conn.get(f"progress:{job_id}")
            progress_str = progress.decode("utf-8") if progress else "Queued..."
            
            return {
                "status": job.get_status(),
                "progress": progress_str,
                "repo_url": job.args[0] if job.args else ""
            }
        except Exception as e:
            logger.warning(f"Failed to fetch job from RQ: {e}")
            
    raise HTTPException(status_code=404, detail="Job not found or Redis disconnected.")

@router.get("/repos")
async def list_repositories(username: str = Depends(get_current_user)):
    """Returns a list of all successfully ingested repositories for the logged-in user."""
    repos = []
    from app.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT repo_id, repo_url FROM user_repos WHERE username = ?",
            (username,)
        )
        rows = cursor.fetchall()
        for row in rows:
            repos.append({
                "id": row["repo_id"],
                "url": row["repo_url"]
            })
    except sqlite3.Error as e:
        logger.error(f"Failed to query user repos from SQLite: {e}")
    finally:
        conn.close()
        
    return repos
