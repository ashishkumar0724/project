# src/doc_checker/db/database.py
import sqlite3
import json
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional  # <--- ADD THIS LINE
from ..config import config

def init_db():
    """Initialize the SQLite database with enhanced schema."""
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        
        # Table 1: Document metadata and file storage
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS documents (
                doc_id TEXT PRIMARY KEY,
                original_filename TEXT,
                stored_filepath TEXT,
                file_hash_sha256 TEXT,
                file_size_bytes INTEGER,
                document_type TEXT,
                upload_timestamp TEXT,
                security_verdict TEXT,
                page_count INTEGER
            )
        ''')
        
        # Table 2: Applicant profiles (structured extraction)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS applicant_profiles (
                doc_id TEXT PRIMARY KEY,
                applicant_name TEXT,
                account_number TEXT,
                ifsc_code TEXT,
                bank_name TEXT,
                pan_number TEXT,
                extraction_timestamp TEXT,
                raw_json TEXT,
                FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
            )
        ''')
        
        # Table 3: Raw extracted text (markdown format)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_text (
                doc_id TEXT PRIMARY KEY,
                full_text_md TEXT,
                page_texts TEXT,  -- JSON array of page texts
                raw_tables_json TEXT,
                extraction_method TEXT,
                FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
            )
        ''')
        
        # Table 4: Embeddings for semantic search
        # Store embeddings as BLOB for efficiency
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS document_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                chunk_id INTEGER,
                chunk_text TEXT,
                embedding BLOB,  -- Store as binary
                embedding_model TEXT,
                chunk_metadata TEXT,  -- JSON metadata
                FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
            )
        ''')
        
        # Table 5: Extracted fields (granular key-value pairs)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS extracted_fields (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT,
                field_name TEXT,
                field_value TEXT,
                confidence_score REAL,
                source_page INTEGER,
                FOREIGN KEY(doc_id) REFERENCES documents(doc_id)
            )
        ''')
        
        cursor.execute("PRAGMA table_info(documents)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if 'image_paths_json' not in columns:
            print("Adding missing 'image_paths_json' column to documents table...")
            cursor.execute("ALTER TABLE documents ADD COLUMN image_paths_json TEXT")
            
        conn.commit()

def save_document_metadata(doc_id: str, filename: str, filepath: str, 
                          file_hash: str, file_size: int, doc_type: str,
                          security_verdict: str, page_count: int):
    """Save document metadata."""
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO documents 
            (doc_id, original_filename, stored_filepath, file_hash_sha256, 
             file_size_bytes, document_type, upload_timestamp, security_verdict, page_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (doc_id, filename, filepath, file_hash, file_size, doc_type,
              datetime.now().isoformat(), security_verdict, page_count))
        conn.commit()

def save_profile_to_db(doc_id: str, profile: dict, raw_json: str):
    """Save extracted profile to database."""
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO applicant_profiles 
            (doc_id, applicant_name, account_number, ifsc_code, bank_name, 
             pan_number, extraction_timestamp, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (doc_id, profile.get("applicant_name"), profile.get("account_number"), 
              profile.get("ifsc_code"), profile.get("bank_name"), 
              profile.get("pan_number"), datetime.now().isoformat(), raw_json))
        conn.commit()

def save_document_text(doc_id: str, full_text_md: str, page_texts: list, raw_tables: list, method: str = "pdfplumber"):
    """Save raw extracted text and raw tables as JSON."""
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO document_text 
            (doc_id, full_text_md, page_texts, raw_tables_json, extraction_method)
            VALUES (?, ?, ?, ?, ?)
        ''', (doc_id, full_text_md, json.dumps(page_texts), json.dumps(raw_tables), method))
        conn.commit()

def save_embeddings(doc_id: str, chunks: list, embeddings: list, model_name: str):
    """
    Save text chunks and their embeddings.
    chunks: list of dicts with 'text' and 'metadata'
    embeddings: list of numpy arrays
    """
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        
        # Clear old embeddings for this doc
        cursor.execute('DELETE FROM document_embeddings WHERE doc_id = ?', (doc_id,))
        
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
            cursor.execute('''
                INSERT INTO document_embeddings 
                (doc_id, chunk_id, chunk_text, embedding, embedding_model, chunk_metadata)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (doc_id, i, chunk['text'], emb.tobytes(), model_name, 
                  json.dumps(chunk.get('metadata', {}))))
        
        conn.commit()

def save_extracted_fields(doc_id: str, fields: dict):
    """Save granular extracted fields."""
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        for key, value in fields.items():
            if value and key not in ["document_type", "verification_warnings"]:
                cursor.execute('''
                    INSERT INTO extracted_fields (doc_id, field_name, field_value, confidence_score)
                    VALUES (?, ?, ?, ?)
                ''', (doc_id, key, str(value), 0.95))
        conn.commit()

def search_similar(query_embedding: np.ndarray, top_k: int = 5) -> list:
    """
    Search for similar documents using cosine similarity.
    Note: SQLite doesn't have native vector ops, so we do this in Python.
    For production, use pgvector or Qdrant.
    """
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT doc_id, chunk_id, chunk_text, embedding, chunk_metadata FROM document_embeddings')
        rows = cursor.fetchall()
    
    results = []
    for doc_id, chunk_id, chunk_text, emb_blob, metadata in rows:
        # Convert blob back to numpy array
        emb = np.frombuffer(emb_blob, dtype=np.float32)
        
        # Calculate cosine similarity
        similarity = np.dot(query_embedding, emb) / (np.linalg.norm(query_embedding) * np.linalg.norm(emb))
        
        results.append({
            'doc_id': doc_id,
            'chunk_id': chunk_id,
            'chunk_text': chunk_text,
            'similarity': float(similarity),
            'metadata': json.loads(metadata) if metadata else {}
        })
    
    # Sort by similarity and return top_k
    results.sort(key=lambda x: x['similarity'], reverse=True)
    return results[:top_k]

# Add this function to src/doc_checker/db/database.py

def save_document_images(doc_id: str, image_paths: List[Path]):
    """Save the paths of the rasterized images to the database."""
    # We store them as a JSON array in the documents table, or a separate table.
    # For simplicity, let's update the documents table.
    import json
    with sqlite3.connect(config.database.db_path) as conn:
        cursor = conn.cursor()
        # Convert Paths to strings
        paths_json = json.dumps([str(p) for p in image_paths])
        
        cursor.execute('''
            UPDATE documents SET image_paths_json = ? WHERE doc_id = ?
        ''', (paths_json, doc_id))
        conn.commit()