import chromadb
import os
from google import genai
from google.genai import types

from dotenv import load_dotenv

load_dotenv()

# Initialize ChromaDB (Persistent)
chroma_client = chromadb.PersistentClient(path="./knowledge_base")
collection = chroma_client.get_or_create_collection(name="yexis_docs")

# Initialize Gemini Client for Embeddings
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})

def get_embedding(text: str) -> list[float]:
    """Generates vector embedding for the given text using Gemini."""
    response = client.models.embed_content(
        model="models/text-embedding-004",
        contents=text
    )
    return response.embeddings[0].values

def add_document(doc_id: str, text: str):
    """Adds a document to the ChromaDB collection."""
    embedding = get_embedding(text)
    collection.add(
        documents=[text],
        embeddings=[embedding],
        ids=[doc_id]
    )
    print(f"Added document: {doc_id}")

def search_knowledge_base(query: str, n_results: int = 2) -> list[str]:
    """Searches the knowledge base for relevant context."""
    print(f"Searching KB for: {query}")
    query_embedding = get_embedding(query)
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results
    )
    
    if results["documents"]:
        return results["documents"][0]
    return []

# Seed initial knowledge if empty
if collection.count() == 0:
    print("Seeding initial knowledge base...")
    docs = {
        "vrf_warranty": "The Samsung VRF System usually comes with a 1-year comprehensive warranty and 5 years on the compressor. AMC options are available.",
        "return_policy": "Yexis Electronics allows returns for defective items within 7 days of delivery. Original packaging is required.",
        "support_hours": "Our support team is available Mon-Sat from 9 AM to 6 PM IST. Emergency support is available for contract customers."
    }
    for doc_id, text in docs.items():
        try:
            add_document(doc_id, text)
        except Exception as e:
            print(f"Failed to seed {doc_id}: {e}")
