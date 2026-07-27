import logging
import pickle
import os
from typing import List, Dict, Any, Tuple
from sklearn.feature_extraction.text import TfidfVectorizer
from qdrant_client import QdrantClient
from qdrant_client.http import models

from app.config import settings

logger = logging.getLogger(__name__)

# Fallback path for local serialization when Redis is unavailable
def get_local_vectorizer_path(collection_name: str) -> str:
    return os.path.join(settings.TEMP_DIR, f"{collection_name}_vectorizer.pkl")

def train_and_save_vectorizer(
    collection_name: str, 
    texts: List[str], 
    redis_client = None
) -> TfidfVectorizer:
    """
    Fits a TfidfVectorizer on the document collection, serializes it, 
    and stores it in Redis (or local file fallback).
    """
    logger.info(f"Fitting TF-IDF Vectorizer on {len(texts)} chunks...")
    
    # We use a sublinear term frequency scaling and ignore extremely common/rare words
    vectorizer = TfidfVectorizer(
        sublinear_tf=True,
        min_df=1,
        max_df=0.98,
        token_pattern=r"(?u)\b\w+\b" # Standard word tokenizer
    )
    vectorizer.fit(texts)
    
    # Serialize vectorizer
    pkl_data = pickle.dumps(vectorizer)
    
    # Save to Redis if client provided, otherwise save locally
    saved_to_redis = False
    if redis_client:
        try:
            redis_client.set(f"vectorizer:{collection_name}", pkl_data)
            saved_to_redis = True
            logger.info(f"Saved TF-IDF Vectorizer to Redis for collection '{collection_name}'")
        except Exception as e:
            logger.warning(f"Failed to save TF-IDF Vectorizer to Redis: {e}. Falling back to disk.")
            
    if not saved_to_redis:
        local_path = get_local_vectorizer_path(collection_name)
        try:
            with open(local_path, "wb") as f:
                f.write(pkl_data)
            logger.info(f"Saved TF-IDF Vectorizer to local disk: {local_path}")
        except Exception as e:
            logger.error(f"Failed to save TF-IDF Vectorizer to local disk: {e}")
            
    return vectorizer

def load_vectorizer(collection_name: str, redis_client = None) -> TfidfVectorizer | None:
    """Loads TF-IDF Vectorizer from Redis or local file fallback."""
    pkl_data = None
    
    if redis_client:
        try:
            pkl_data = redis_client.get(f"vectorizer:{collection_name}")
        except Exception as e:
            logger.warning(f"Failed to load TF-IDF Vectorizer from Redis: {e}")
            
    if not pkl_data:
        local_path = get_local_vectorizer_path(collection_name)
        if os.path.exists(local_path):
            try:
                with open(local_path, "rb") as f:
                    pkl_data = f.read()
            except Exception as e:
                logger.error(f"Failed to read TF-IDF Vectorizer from local disk: {e}")
                
    if pkl_data:
        try:
            return pickle.loads(pkl_data)
        except Exception as e:
            logger.error(f"Failed to deserialize TF-IDF Vectorizer: {e}")
            
    return None

def text_to_sparse_vector(vectorizer: TfidfVectorizer, text: str) -> Tuple[List[int], List[float]]:
    """Converts a string of text into list of indices and values for Qdrant SparseVector."""
    sparse_matrix = vectorizer.transform([text])
    coo = sparse_matrix.tocoo()
    # COO format has row, col, data attributes. We only have 1 row (index 0)
    indices = coo.col.tolist()
    values = coo.data.tolist()
    return indices, values

def search_sparse(
    client: QdrantClient, 
    collection_name: str, 
    query: str, 
    top_k: int = 20,
    redis_client = None,
    username: str = None
) -> List[Dict[str, Any]]:
    """Performs a sparse vector search in the Qdrant collection using the fitted TF-IDF Vectorizer, isolated by user."""
    vectorizer = load_vectorizer(collection_name, redis_client)
    if not vectorizer:
        logger.warning(f"No TF-IDF Vectorizer found for collection '{collection_name}'. Sparse search is disabled.")
        return []
        
    indices, values = text_to_sparse_vector(vectorizer, query)
    if not indices:
        return []
        
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
        
    try:
        response = client.query_points(
            collection_name=collection_name,
            query=models.SparseVector(
                indices=indices,
                values=values
            ),
            using="text-sparse",
            query_filter=query_filter,
            limit=top_k,
            with_payload=True
        )
    except Exception as e:
        logger.error(f"Sparse search query failed for collection '{collection_name}': {e}")
        return []
        
    results = []
    for res in response.points:
        results.append({
            "id": res.id,
            "score": res.score,
            "payload": res.payload
        })
    return results
