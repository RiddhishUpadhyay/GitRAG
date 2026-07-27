import logging
from typing import List
from sentence_transformers import SentenceTransformer

from app.config import settings

logger = logging.getLogger(__name__)

class EmbeddingManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(EmbeddingManager, cls).__new__(cls)
            cls._instance._model = None
        return cls._instance

    @property
    def model(self) -> SentenceTransformer:
        if self._model is None:
            logger.info("Loading dense embedding model (BAAI/bge-base-en-v1.5)...")
            # Set cache folder inside workspace to avoid writing outside the sandbox
            import os
            os.environ["SENTENCE_TRANSFORMERS_HOME"] = os.path.join(settings.TEMP_DIR, "models")
            self._model = SentenceTransformer("BAAI/bge-base-en-v1.5", token=False)
            logger.info("Dense embedding model loaded successfully.")
        return self._model

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Generates dense embeddings for a list of document texts."""
        if not texts:
            return []
        embeddings = self.model.encode(texts, show_progress_bar=False, convert_to_numpy=True)
        return embeddings.tolist()

    def embed_query(self, query: str) -> List[float]:
        """Generates a dense embedding for a single search query, with BGE prompt prefix."""
        # BGE-v1.5 recommends prepending this prefix to queries
        prompt_query = f"Represent this sentence for searching relevant passages: {query}"
        embedding = self.model.encode(prompt_query, show_progress_bar=False, convert_to_numpy=True)
        return embedding.tolist()

# Global singleton
embedding_manager = EmbeddingManager()
