import logging
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings
from app.ingestion.chunker import CodeChunk
from app.retrieval.embeddings import embedding_manager

logger = logging.getLogger(__name__)

def get_qdrant_client() -> QdrantClient:
    """Instantiates a Qdrant client using configuration settings."""
    if settings.QDRANT_URL.startswith("local"):
        # Support in-memory/local filesystem storage for testing
        db_path = settings.QDRANT_URL.replace("local://", "")
        return QdrantClient(path=db_path or None)
    return QdrantClient(url=settings.QDRANT_URL, api_key=settings.QDRANT_API_KEY, timeout=60)

def init_collection(client: QdrantClient, collection_name: str):
    """Initializes a Qdrant collection with dense and sparse vector configs."""
    try:
        client.get_collection(collection_name)
        logger.info(f"Qdrant collection '{collection_name}' already exists.")
    except Exception:
        logger.info(f"Creating Qdrant collection '{collection_name}'...")
        client.create_collection(
            collection_name=collection_name,
            vectors_config=models.VectorParams(
                size=768,  # dimension of BGE-base-en-v1.5
                distance=models.Distance.COSINE
            ),
            sparse_vectors_config={
                "text-sparse": models.SparseVectorParams(
                    index=models.SparseIndexParams(
                        on_disk=True
                    )
                )
            }
        )
        logger.info(f"Qdrant collection '{collection_name}' created successfully.")

def upsert_chunks_dense(client: QdrantClient, collection_name: str, chunks: List[CodeChunk], username: str = None):
    """Generates embeddings and upserts chunks (dense vectors and payloads) into Qdrant."""
    if not chunks:
        return
        
    init_collection(client, collection_name)
    
    texts = [chunk.content for chunk in chunks]
    embeddings = embedding_manager.embed_documents(texts)
    
    points = []
    for i, chunk in enumerate(chunks):
        payload = {
            "content": chunk.content,
            "file_path": chunk.file_path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "chunk_type": chunk.chunk_type
        }
        if username:
            payload["username"] = username
        points.append(
            models.PointStruct(
                id=chunk.chunk_id,
                vector=embeddings[i],
                payload=payload
            )
        )
        
    # Batch upsert points
    batch_size = 100
    for j in range(0, len(points), batch_size):
        client.upsert(
            collection_name=collection_name,
            points=points[j:j+batch_size]
        )
        logger.info(f"Upserted dense batch {j//batch_size + 1} of size {len(points[j:j+batch_size])}")

def search_dense(client: QdrantClient, collection_name: str, query: str, top_k: int = 20, username: str = None) -> List[Dict[str, Any]]:
    """Performs a dense vector search in the Qdrant collection, isolating results by username."""
    try:
        client.get_collection(collection_name)
    except Exception:
        logger.warning(f"Collection '{collection_name}' does not exist. Cannot query.")
        return []
        
    query_vector = embedding_manager.embed_query(query)
    
    query_filter = None
    if username:
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="username",
                    match=models.MatchValue(value=username)
                )
            ]
        )
        
    response = client.query_points(
        collection_name=collection_name,
        query=query_vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True
    )
    
    results = []
    for res in response.points:
        results.append({
            "id": res.id,
            "score": res.score,
            "payload": res.payload
        })
    return results
