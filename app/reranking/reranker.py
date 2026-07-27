import logging
from typing import List, Dict, Any
from sentence_transformers import CrossEncoder

from app.config import settings

logger = logging.getLogger(__name__)

class RerankerManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(RerankerManager, cls).__new__(cls)
            cls._instance._model = None
        return cls._instance

    @property
    def model(self) -> CrossEncoder:
        if self._model is None:
            logger.info("Loading reranker model (BAAI/bge-reranker-base)...")
            import os
            # Set cache folder inside workspace to avoid writing outside sandbox
            os.environ["SENTENCE_TRANSFORMERS_HOME"] = os.path.join(settings.TEMP_DIR, "models")
            self._model = CrossEncoder("BAAI/bge-reranker-base", token=False)
            logger.info("Reranker model loaded successfully.")
        return self._model

    def rerank(self, query: str, candidates: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Reranks a list of candidate documents against the query using a Cross-Encoder.
        
        Args:
            query: The user's query string.
            candidates: List of fused document dicts from RRF search.
            top_n: Number of documents to return after reranking.
            
        Returns:
            List of reranked candidates containing payloads and a cross_encoder_score, sorted desc.
        """
        if not candidates:
            return []
            
        logger.info(f"Reranking {len(candidates)} candidates for query: '{query}'...")
        
        # Prepare pairs for Cross-Encoder evaluation: [query, document_text]
        pairs = [[query, cand["payload"]["content"]] for cand in candidates]
        
        # Calculate similarity scores
        scores = self.model.predict(pairs)
        
        # Append scores to candidates
        reranked = []
        for i, cand in enumerate(candidates):
            cand_copy = cand.copy()
            # Convert numpy float to standard float
            cand_copy["rerank_score"] = float(scores[i])
            reranked.append(cand_copy)
            
        # Sort desc by rerank score
        reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
        
        # Keep top_n
        results = reranked[:top_n]
        logger.info(f"Reranking complete. Selected top {len(results)} matches.")
        return results

# Global singleton
reranker_manager = RerankerManager()
