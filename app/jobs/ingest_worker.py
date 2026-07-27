import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import List, Dict, Any

from app.config import settings
from app.ingestion.repo_loader import clone_repo, load_and_filter_repo, get_repo_id, clean_repo_temp_dir
from app.ingestion.chunker import chunk_file, CodeChunk
from app.ingestion.diff_sync import load_stored_hashes, calculate_diff, save_stored_hashes
from app.retrieval.dense_search import get_qdrant_client, init_collection, upsert_chunks_dense
from app.retrieval.sparse_search import train_and_save_vectorizer, text_to_sparse_vector
from app.cache.redis_client import redis_client

logger = logging.getLogger(__name__)

def update_status(job_id: str, message: str, is_local: bool, local_store: dict = None, status: str = "running"):
    """Helper to update status message in Redis or local store."""
    logger.info(f"Job {job_id} Status: {message}")
    if is_local and local_store is not None:
        local_store[job_id] = {
            "status": status,
            "progress": message,
            "updated_at": time.time()
        }
    else:
        # Save to Redis status cache
        redis_client.set_job_progress(job_id, message)

def run_ingest_pipeline(
    repo_url: str, 
    job_id: str, 
    is_local: bool = False, 
    local_store: dict = None,
    username: str = None
) -> str:
    """
    Main ingestion pipeline function.
    Can be run in FastAPI BackgroundTasks (is_local=True) or inside an RQ Worker.
    """
    repo_id = get_repo_id(repo_url)
    collection_name = f"repo_{repo_id}"
    
    try:
        # 1. Clone repository
        update_status(job_id, "Cloning repository...", is_local, local_store)
        repo_path = clone_repo(repo_url)
        
        # 2. Filter files & check size
        update_status(job_id, "Filtering files and checking repository size...", is_local, local_store)
        valid_files, total_size = load_and_filter_repo(repo_path)
        update_status(job_id, f"Found {len(valid_files)} files. Total size: {total_size / (1024*1024):.2f} MB.", is_local, local_store)
        
        # 3. Load stored state and calculate diff
        update_status(job_id, "Checking for changes (diff sync)...", is_local, local_store)
        old_hashes = load_stored_hashes(repo_id, is_local)
        new_files, modified_files, deleted_files, current_hashes = calculate_diff(
            repo_path, valid_files, old_hashes
        )
        
        qdrant_client = get_qdrant_client()
        init_collection(qdrant_client, collection_name)
        
        # 4. Process deletions
        files_to_delete = deleted_files + modified_files
        if files_to_delete:
            update_status(job_id, f"Removing old index points for {len(files_to_delete)} files...", is_local, local_store)
            from qdrant_client.http import models as qd_models
            qdrant_client.delete(
                collection_name=collection_name,
                points_selector=qd_models.FilterSelector(
                    filter=qd_models.Filter(
                        must=[
                            qd_models.FieldCondition(
                                key="file_path",
                                match=qd_models.MatchAny(any=files_to_delete)
                            )
                        ]
                    )
                )
            )
            
        # 5. Process new & modified files (Chunking + Dense embedding)
        files_to_index = new_files + modified_files
        new_chunks: List[CodeChunk] = []
        
        if files_to_index:
            update_status(job_id, f"Chunking {len(files_to_index)} changed/new files...", is_local, local_store)
            for i, rel_path in enumerate(files_to_index):
                abs_path = repo_path / rel_path
                chunks = chunk_file(abs_path, repo_path)
                new_chunks.extend(chunks)
                
            update_status(job_id, f"Generated {len(new_chunks)} code chunks. Creating dense embeddings...", is_local, local_store)
            upsert_chunks_dense(qdrant_client, collection_name, new_chunks, username=username)
            
        # 6. Re-calculate Sparse Index if any changes occurred, or if vectorizer is missing
        # We need a Redis connection if not local
        redis_conn = None if is_local else redis_client.get_client()
        from app.retrieval.sparse_search import load_vectorizer
        vectorizer_exists = load_vectorizer(collection_name, redis_conn) is not None
        
        if files_to_index or deleted_files or not vectorizer_exists:
            update_status(job_id, "Updating keyword search index (sparse vectors)...", is_local, local_store)
            
            # Fetch all chunk texts from the collection to build the corpus vocabulary
            scroll_results = []
            next_page = None
            from qdrant_client.http import models as qd_models
            
            # Scroll until we get all points
            while True:
                res, next_page = qdrant_client.scroll(
                    collection_name=collection_name,
                    limit=1000,
                    with_payload=True,
                    with_vectors=False,
                    offset=next_page
                )
                scroll_results.extend(res)
                if not next_page:
                    break
                    
            if scroll_results:
                all_texts = [item.payload["content"] for item in scroll_results]
                
                # Fit new vectorizer
                vectorizer = train_and_save_vectorizer(collection_name, all_texts, redis_client=redis_conn)
                
                # Update Qdrant sparse vectors for all chunks
                update_operations = []
                from qdrant_client.http import models as qd_models
                
                for item in scroll_results:
                    indices, values = text_to_sparse_vector(vectorizer, item.payload["content"])
                    update_operations.append(
                        qd_models.PointVectors(
                            id=item.id,
                            vector={
                                "text-sparse": qd_models.SparseVector(indices=indices, values=values)
                            }
                        )
                    )
                    
                # Update vectors in batches
                batch_size = 200
                for j in range(0, len(update_operations), batch_size):
                    qdrant_client.update_vectors(
                        collection_name=collection_name,
                        points=update_operations[j:j+batch_size]
                    )
                    
                update_status(job_id, f"Updated sparse vectors for {len(update_operations)} chunks.", is_local, local_store)
            else:
                update_status(job_id, "No indexed chunks found. Keyword search index is empty.", is_local, local_store)
                
        # 7. Save file hashes
        update_status(job_id, "Saving repository index state...", is_local, local_store)
        save_stored_hashes(repo_id, current_hashes, is_local)
        
        # 8. Clean temporary clone
        clean_repo_temp_dir(repo_url)
        
        update_status(job_id, "finished", is_local, local_store, status="finished")
        return "Indexing completed successfully."
        
    except Exception as e:
        error_msg = f"failed: {str(e)}"
        logger.error(f"Ingestion failed for job {job_id}: {e}")
        logger.error(traceback.format_exc())
        clean_repo_temp_dir(repo_url)
        update_status(job_id, error_msg, is_local, local_store, status="failed")
        return error_msg

def ingest_repo_job(repo_url: str, username: str = None):
    """Entrypoint function called by RQ worker."""
    # Retrieve current RQ job ID
    try:
        from rq import get_current_job
        job = get_current_job()
        job_id = job.get_id() if job else "rq_job"
    except Exception:
        job_id = "rq_job"
        
    logger.info(f"RQ Worker starting job {job_id} for URL {repo_url} for user {username}")
    return run_ingest_pipeline(repo_url, job_id, is_local=False, username=username)

if __name__ == "__main__":
    # If file is executed directly, starts a local RQ worker listening to 'ingest' queue
    try:
        from redis import Redis
        from rq import Worker, Queue, Connection
        
        redis_conn = Redis.from_url(settings.REDIS_URL)
        with Connection(redis_conn):
            queue = Queue("ingest")
            worker = Worker([queue])
            logger.info("Starting RQ worker...")
            worker.work()
    except Exception as e:
        print(f"Failed to start RQ worker from command line: {e}")
        sys.exit(1)
