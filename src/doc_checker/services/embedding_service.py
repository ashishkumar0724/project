# src/doc_checker/services/embedding_service.py
import requests
import numpy as np
from typing import List, Dict, Any
from pathlib import Path
import re

from ..config import config

class EmbeddingService:
    """Service for generating and managing text embeddings via Ollama."""
    
    def __init__(self):
        self.base_url = config.ollama.base_url
        self.model = config.ollama.embedding_model
        self.api_url = f"{self.base_url}/api/embeddings"
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """Generate embedding for a single text chunk."""
        payload = {
            "model": self.model,
            "prompt": text.strip()
        }
        
        try:
            response = requests.post(self.api_url, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            return np.array(result["embedding"], dtype=np.float32)
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Ollama embedding API failed: {e}")
    
    def chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> List[Dict[str, Any]]:
        """
        Split text into overlapping chunks for embedding.
        Returns list of dicts with 'text' and 'metadata'.
        """
        # Clean text
        text = re.sub(r'\n\s*\n', '\n\n', text)  # Normalize newlines
        text = text.strip()
        
        chunks = []
        start = 0
        chunk_id = 0
        
        while start < len(text):
            end = start + chunk_size
            
            # Try to break at sentence or paragraph boundary
            if end < len(text):
                # Look for sentence boundary
                sentence_break = text.rfind('. ', start, end)
                if sentence_break > start + chunk_size // 2:
                    end = sentence_break + 1
                
                # If no sentence, try paragraph
                para_break = text.rfind('\n\n', start, end)
                if para_break > start + chunk_size // 2:
                    end = para_break
            
            chunk_text = text[start:end].strip()
            
            if chunk_text:  # Only add non-empty chunks
                chunks.append({
                    'text': chunk_text,
                    'metadata': {
                        'chunk_id': chunk_id,
                        'start_char': start,
                        'end_char': end,
                        'char_length': len(chunk_text)
                    }
                })
                chunk_id += 1
            
            start = end - overlap
        
        return chunks
    
    def embed_document(self, full_text: str, doc_id: str) -> tuple:
        """
        Embed an entire document.
        Returns (chunks, embeddings) tuple.
        """
        # Chunk the text
        chunks = self.chunk_text(full_text)
        
        # Generate embeddings for each chunk
        embeddings = []
        for chunk in chunks:
            emb = self.generate_embedding(chunk['text'])
            embeddings.append(emb)
        
        return chunks, embeddings
    
    def embed_query(self, query: str) -> np.ndarray:
        """Generate embedding for a search query."""
        return self.generate_embedding(query)