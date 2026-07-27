import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def compute_rrf(
    dense_results: List[Dict[str, Any]], 
    sparse_results: List[Dict[str, Any]], 
    k: int = 60
) -> List[Dict[str, Any]]:
    """
    Fuses two lists of retrieved documents using Reciprocal Rank Fusion (RRF).
    Formula: RRF_score(d) = sum_{m in searches} 1 / (k + rank_m(d))
    
    Args:
        dense_results: Search results from dense vector query (ordered by score desc).
        sparse_results: Search results from sparse vector query (ordered by score desc).
        k: Constant parameter for smoothing (default: 60).
        
    Returns:
        List of fused search results containing payloads, sorted by RRF score descending.
    """
    rrf_scores: Dict[str, float] = {}
    doc_payloads: Dict[str, Dict[str, Any]] = {}
    
    # Process dense search rankings
    for rank, doc in enumerate(dense_results, start=1):
        doc_id = str(doc["id"])
        doc_payloads[doc_id] = doc["payload"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        
    # Process sparse search rankings
    for rank, doc in enumerate(sparse_results, start=1):
        doc_id = str(doc["id"])
        # If payload wasn't added by dense search, add it now
        if doc_id not in doc_payloads:
            doc_payloads[doc_id] = doc["payload"]
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank))
        
    # Convert to sorted list of results
    sorted_docs = sorted(rrf_scores.items(), key=lambda item: item[1], reverse=True)
    
    fused_results = []
    for doc_id, rrf_score in sorted_docs:
        fused_results.append({
            "id": doc_id,
            "rrf_score": rrf_score,
            "payload": doc_payloads[doc_id]
        })
        
    logger.info(f"RRF fused {len(dense_results)} dense and {len(sparse_results)} sparse results into {len(fused_results)} unique docs.")
    return fused_results
