"""RAG system for document ingestion, chunking, and retrieval."""

import json
import logging
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import sqlite3
from dataclasses import dataclass, asdict
import hashlib

from .client_interface import BaseLLMClient

LOG = logging.getLogger(__name__)


@dataclass
class DocumentChunk:
    """A chunk of text from a document with metadata."""
    chunk_id: str
    source_id: str
    filename: str
    page: Optional[int]
    heading: Optional[str]
    text: str
    embedding: Optional[List[float]] = None


class RAGSystem:
    """RAG system for document processing and retrieval."""
    
    def __init__(
        self,
        llm_client: BaseLLMClient,
        embedding_model: Optional[str] = None,
        db_path: Optional[Path] = None,
        chunk_size: int = 500,
        chunk_overlap: int = 50
    ):
        self.llm_client = llm_client
        # Use provider-specific embedding model or default
        self.embedding_model = embedding_model or llm_client.model
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.db_path = db_path or Path(__file__).parent.parent.parent / ".rag_data" / "rag.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database for storing chunks and metadata."""
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    source_id TEXT PRIMARY KEY,
                    filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    page INTEGER,
                    heading TEXT,
                    text TEXT NOT NULL,
                    embedding BLOB,
                    FOREIGN KEY (source_id) REFERENCES documents(source_id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_source_id ON chunks(source_id)
            """)
            conn.commit()
    
    def _chunk_text(self, text: str, heading: Optional[str] = None) -> List[str]:
        """Split text into overlapping chunks."""
        if not text:
            return []
        
        # Simple word-based chunking
        words = text.split()
        chunks = []
        
        for i in range(0, len(words), self.chunk_size - self.chunk_overlap):
            chunk_words = words[i:i + self.chunk_size]
            chunk_text = " ".join(chunk_words)
            chunks.append(chunk_text)
        
        return chunks
    
    def _generate_chunk_id(self, source_id: str, index: int) -> str:
        """Generate a unique chunk ID."""
        return f"{source_id}_chunk_{index}"
    
    def _file_hash(self, path: Path) -> str:
        """Generate hash of file contents."""
        hash_obj = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    
    def add_document(
        self,
        text: str,
        filename: str,
        source_id: Optional[str] = None,
        page: Optional[int] = None,
        heading: Optional[str] = None
    ) -> str:
        """Add a document to the RAG system."""
        if source_id is None:
            source_id = hashlib.md5(filename.encode()).hexdigest()[:16]
        
        with sqlite3.connect(str(self.db_path)) as conn:
            # Check if document already exists
            cursor = conn.execute(
                "SELECT source_id FROM documents WHERE source_id = ?",
                (source_id,)
            )
            if cursor.fetchone():
                LOG.info(f"Document {source_id} already exists, skipping")
                return source_id
            
            # Store document metadata
            conn.execute(
                "INSERT INTO documents (source_id, filename, file_hash) VALUES (?, ?, ?)",
                (source_id, filename, "manual_add")
            )
            
            # Chunk and store text
            chunks = self._chunk_text(text, heading)
            LOG.info(f"Created {len(chunks)} chunks from {filename}")
            
            for idx, chunk_text in enumerate(chunks):
                chunk_id = self._generate_chunk_id(source_id, idx)
                conn.execute(
                    """INSERT INTO chunks (chunk_id, source_id, filename, page, heading, text)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (chunk_id, source_id, filename, page, heading, chunk_text)
                )
            
            conn.commit()
        
        # Generate embeddings for all chunks
        self._embed_chunks(source_id)
        
        return source_id
    
    def add_document_from_file(self, path: Path) -> str:
        """Add a document from a text file."""
        text = path.read_text(encoding="utf-8")
        source_id = hashlib.md5(str(path).encode()).hexdigest()[:16]
        return self.add_document(text, path.name, source_id)
    
    def _embed_chunks(self, source_id: str):
        """Generate embeddings for all chunks of a document."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT chunk_id, text FROM chunks WHERE source_id = ? AND embedding IS NULL",
                (source_id,)
            )
            chunks_to_embed = cursor.fetchall()
        
        if not chunks_to_embed:
            return
        
        LOG.info(f"Generating embeddings for {len(chunks_to_embed)} chunks")
        
        # Batch embeddings
        batch_size = 10
        for i in range(0, len(chunks_to_embed), batch_size):
            batch = chunks_to_embed[i:i + batch_size]
            chunk_ids = [row[0] for row in batch]
            texts = [row[1] for row in batch]
            
            try:
                embeddings = self.llm_client.embed(texts)
                
                with sqlite3.connect(str(self.db_path)) as conn:
                    for chunk_id, embedding in zip(chunk_ids, embeddings):
                        embedding_blob = json.dumps(embedding).encode("utf-8")
                        conn.execute(
                            "UPDATE chunks SET embedding = ? WHERE chunk_id = ?",
                            (embedding_blob, chunk_id)
                        )
                    conn.commit()
                    
            except Exception as e:
                LOG.error(f"Failed to embed batch {i//batch_size}: {e}")
    
    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        source_id: Optional[str] = None
    ) -> List[DocumentChunk]:
        """Retrieve relevant chunks for a query."""
        # Generate query embedding
        try:
            query_embedding = self.llm_client.embed([query])[0]
        except Exception as e:
            LOG.error(f"Failed to generate query embedding: {e}")
            return []
        
        # Get all chunks with embeddings
        with sqlite3.connect(str(self.db_path)) as conn:
            if source_id:
                cursor = conn.execute(
                    "SELECT chunk_id, source_id, filename, page, heading, text, embedding "
                    "FROM chunks WHERE source_id = ? AND embedding IS NOT NULL",
                    (source_id,)
                )
            else:
                cursor = conn.execute(
                    "SELECT chunk_id, source_id, filename, page, heading, text, embedding "
                    "FROM chunks WHERE embedding IS NOT NULL"
                )
            
            chunks_with_embeddings = cursor.fetchall()
        
        # Calculate cosine similarity
        scored_chunks = []
        for row in chunks_with_embeddings:
            chunk_id, source_id, filename, page, heading, text, embedding_blob = row
            embedding = json.loads(embedding_blob.decode("utf-8"))
            
            similarity = self._cosine_similarity(query_embedding, embedding)
            scored_chunks.append((similarity, DocumentChunk(
                chunk_id=chunk_id,
                source_id=source_id,
                filename=filename,
                page=page,
                heading=heading,
                text=text
            )))
        
        # Sort by similarity and return top_k
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in scored_chunks[:top_k]]
    
    def _cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        dot_product = sum(x * y for x, y in zip(a, b))
        magnitude_a = math.sqrt(sum(x * x for x in a))
        magnitude_b = math.sqrt(sum(y * y for y in b))
        
        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0
        
        return dot_product / (magnitude_a * magnitude_b)
    
    def get_source_context(self, source_id: str) -> Dict[str, Any]:
        """Get context information about a source."""
        with sqlite3.connect(str(self.db_path)) as conn:
            cursor = conn.execute(
                "SELECT * FROM documents WHERE source_id = ?",
                (source_id,)
            )
            doc = cursor.fetchone()
            
            if not doc:
                return {}
            
            cursor = conn.execute(
                "SELECT COUNT(*) FROM chunks WHERE source_id = ?",
                (source_id,)
            )
            chunk_count = cursor.fetchone()[0]
            
            return {
                "source_id": doc[0],
                "filename": doc[1],
                "chunk_count": chunk_count
            }
