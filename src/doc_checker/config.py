# src/doc_checker/config.py
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

@dataclass
class OllamaConfig:
    """Ollama model configurations"""
    base_url: str = "http://localhost:11434"
    extraction_model: str = "qwen3-vl:2b"
    embedding_model: str = "embeddinggemma-2:440m"
    chat_model: str = "qwen3.5:2b"  # For future agent
    timeout: int = 120
    context_size: int = 8192

@dataclass
class DatabaseConfig:
    """Database configuration"""
    db_path: Path = Path("loan_knowledge_base.db")
    embeddings_table: str = "document_embeddings"
    
@dataclass
class StorageConfig:
    """File storage configuration"""
    uploads_dir: Path = Path("secure_uploads")
    text_dir: Path = Path("document_text")
    max_upload_size_mb: int = 20
    
@dataclass
class SecurityConfig:
    """Security limits"""
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB
    max_pages: int = 40
    max_pixels_per_page: int = 40_000_000
    max_total_pixels: int = 150_000_000
    quarantine_dir: Path = Path("quarantine")

@dataclass
class AppConfig:
    """Main application configuration"""
    ollama: OllamaConfig = None
    database: DatabaseConfig = None
    storage: StorageConfig = None
    security: SecurityConfig = None
    
    def __post_init__(self):
        self.ollama = self.ollama or OllamaConfig()
        self.database = self.database or DatabaseConfig()
        self.storage = self.storage or StorageConfig()
        self.security = self.security or SecurityConfig()
        
        # Create directories
        for dir_path in [self.storage.uploads_dir, 
                        self.storage.text_dir, 
                        self.security.quarantine_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

# Global config instance
config = AppConfig()