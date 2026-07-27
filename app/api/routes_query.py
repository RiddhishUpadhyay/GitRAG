import logging
import hashlib
import json
from typing import List, Dict, Any
from pathlib import Path
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from app.config import settings
from app.retrieval.dense_search import search_dense, get_qdrant_client
from app.retrieval.sparse_search import search_sparse
from app.retrieval.rrf import compute_rrf
from app.reranking.reranker import reranker_manager
from app.generation.groq_client import generate_answer
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api", 
    tags=["query"],
    dependencies=[Depends(get_current_user)]
)

class QueryRequest(BaseModel):
    repo_url: str
    query: str

class QueryResponse(BaseModel):
    answer: str
    citations: List[Dict[str, Any]]
    cached: bool

def get_redis_client():
    try:
        from redis import Redis
        return Redis.from_url(settings.REDIS_URL)
    except Exception:
        return None

def get_query_cache_key(repo_id: str, query: str) -> str:
    query_hash = hashlib.md5(query.strip().lower().encode("utf-8")).hexdigest()
    return f"query_cache:{repo_id}:{query_hash}"

def get_history_file_path(username: str, repo_id: str) -> Path:
    return Path(settings.TEMP_DIR) / f"chat_history_{username}_{repo_id}.json"

def read_chat_history(username: str, repo_id: str) -> List[Dict[str, Any]]:
    path = get_history_file_path(username, repo_id)
    if not path.exists():
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read chat history for {username} and {repo_id}: {e}")
        return []

def write_chat_history(username: str, repo_id: str, history: List[Dict[str, Any]]):
    path = get_history_file_path(username, repo_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to write chat history for {username} and {repo_id}: {e}")

@router.get("/history/{repo_id}", response_model=List[Dict[str, Any]])
def get_history(repo_id: str, username: str = Depends(get_current_user)):
    """Fetches the conversation log for a specific repository and username."""
    return read_chat_history(username, repo_id)

@router.post("/query", response_model=QueryResponse)
async def query_repository(request: QueryRequest, username: str = Depends(get_current_user)):
    """Processes a natural language query over an ingested codebase."""
    repo_url = request.repo_url.strip()
    query = request.query.strip()
    
    if not repo_url or not query:
        raise HTTPException(status_code=400, detail="Repository URL and query string must not be empty.")
        
    repo_id = hashlib.md5(repo_url.encode("utf-8")).hexdigest()
    collection_name = f"repo_{repo_id}"
    
    # Check if this user has indexed/registered this repository
    import sqlite3
    from app.database import get_db_connection
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM user_repos WHERE username = ? AND repo_id = ?",
            (username, repo_id)
        )
        if not cursor.fetchone():
            raise HTTPException(
                status_code=403, 
                detail="You do not have access to this repository. Please index it first on your dashboard."
            )
    except sqlite3.Error as e:
        logger.error(f"Failed to verify repo access: {e}")
        raise HTTPException(status_code=500, detail="Database verification failed.")
    finally:
        conn.close()
        
    # Load history turns for conversational memory
    full_history = read_chat_history(username, repo_id)
    
    # Format last 6 messages (3 turns) for LLM context
    llm_history = []
    for msg in full_history[-6:]:
        role = "assistant" if msg["sender"] == "bot" else "user"
        llm_history.append({"role": role, "content": msg["text"]})
        
    # 1. Query Cache Check (Redis cache)
    redis_conn = get_redis_client()
    cache_key = get_query_cache_key(repo_id, query)
    if redis_conn:
        try:
            cached_data = redis_conn.get(cache_key)
            if cached_data:
                logger.info(f"Cache hit for query: '{query}' in collection '{collection_name}'")
                result = json.loads(cached_data.decode("utf-8"))
                
                # Append to conversation log even on cache hits
                full_history.append({
                    "sender": "user",
                    "text": query,
                    "citations": []
                })
                full_history.append({
                    "sender": "bot",
                    "text": result["answer"],
                    "citations": result["citations"]
                })
                write_chat_history(username, repo_id, full_history)
                
                return QueryResponse(
                    answer=result["answer"],
                    citations=result["citations"],
                    cached=True
                )
        except Exception as e:
            logger.warning(f"Failed to query Redis cache: {e}")
            
    # 2. Vector search initialization
    try:
        qdrant_client = get_qdrant_client()
    except Exception as e:
        logger.error(f"Failed to create Qdrant client: {e}")
        raise HTTPException(status_code=500, detail=f"Vector DB connection error: {e}")
        
    # 3. Dense semantic search (top 20)
    try:
        dense_results = search_dense(qdrant_client, collection_name, query, top_k=20)
    except Exception as e:
        logger.error(f"Dense search failed: {e}")
        dense_results = []
        
    # 4. Sparse keyword search (top 20)
    try:
        sparse_results = search_sparse(qdrant_client, collection_name, query, top_k=20, redis_client=redis_conn)
    except Exception as e:
        logger.error(f"Sparse search failed: {e}")
        sparse_results = []
        
    if not dense_results and not sparse_results:
        # If collection doesn't exist or is empty
        raise HTTPException(
            status_code=404, 
            detail="Repository not found or has no indexed contents. Please ingest it first."
        )
        
    # 5. Reciprocal Rank Fusion (RRF)
    fused_results = compute_rrf(dense_results, sparse_results, k=60)
    
    # 6. Reranking using Cross-Encoder (top 5)
    reranked_results = reranker_manager.rerank(query, fused_results, top_n=5)
    
    # 7. Normalize reranked scores and filter by threshold
    import math
    filtered_results = []
    relevance_threshold = 0.35  # Keep matches with >=35% normalized relevance
    
    for i, res in enumerate(reranked_results):
        raw_score = res.get("rerank_score", 0.0)
        # BGE Cross-Encoder outputs raw logits. Map to [0, 1] using standard sigmoid
        normalized_score = 1 / (1 + math.exp(-raw_score))
        res["normalized_score"] = normalized_score
        
        # Keep if score meets threshold, or if it is the top (best) match
        if normalized_score >= relevance_threshold or i == 0:
            filtered_results.append(res)
            
    # 8. LLM Answer generation using filtered matches
    answer = generate_answer(query, filtered_results, history=llm_history)
    
    # 9. Format final citations with normalized scores to display on UI
    citations = []
    for rank, res in enumerate(filtered_results, start=1):
        payload = res["payload"]
        citations.append({
            "rank": rank,
            "file_path": payload.get("file_path"),
            "start_line": payload.get("start_line"),
            "end_line": payload.get("end_line"),
            "content": payload.get("content"),
            "score": res.get("normalized_score", 0.0)
        })
        
    # Append the new messages to the backend history file
    full_history.append({
        "sender": "user",
        "text": query,
        "citations": []
    })
    full_history.append({
        "sender": "bot",
        "text": answer,
        "citations": citations
    })
    write_chat_history(username, repo_id, full_history)
        
    # 8. Cache the answer in Redis
    if redis_conn:
        try:
            cache_payload = {
                "answer": answer,
                "citations": citations
            }
            # Cache for 1 day (86400 seconds)
            redis_conn.setex(cache_key, 86400, json.dumps(cache_payload))
            logger.info("Saved query response to Redis cache.")
        except Exception as e:
            logger.warning(f"Failed to cache query result in Redis: {e}")
            
    return QueryResponse(
        answer=answer,
        citations=citations,
        cached=False
    )
