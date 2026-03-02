import chromadb
import os
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

# Initialize Local Embedding Model (SentenceTransformers)
# This replaces Gemini API to avoid quota issues and 404s.
print("Loading local embedding model (all-MiniLM-L6-v2)...")
embed_model = SentenceTransformer("all-MiniLM-L6-v2")

# Initialize ChromaDB (Persistent)
chroma_client = chromadb.PersistentClient(path="./knowledge_base")

# Note: We use "_local" suffix because local embeddings (384) 
# have different dimensionality than Gemini (768).
collection = chroma_client.get_or_create_collection(name="yexis_docs_local")
product_collection = chroma_client.get_or_create_collection(name="yexis_products_local")

def get_embedding(text: str) -> list[float]:
    """Generates vector embedding for the given text using local SentenceTransformer."""
    embedding = embed_model.encode(text)
    return embedding.tolist()

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
    print(f"Searching KB (Local) for: {query}")
    query_embedding = get_embedding(query)
    
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results
    )
    
    if results["documents"]:
        return results["documents"][0]
    return []

def search_products(query: str, n_results: int = 1) -> list[dict]:
    """Searches the product collection for relevant items."""
    print(f"Semantic search (Local) for product: {query}")
    query_embedding = get_embedding(query)
    
    results = product_collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas"]
    )
    
    formatted_results = []
    if results["documents"] and results["documents"][0]:
        for i in range(len(results["documents"][0])):
            formatted_results.append({
                "name": results["metadatas"][0][i]["name"],
                "content": results["documents"][0][i]
            })
    return formatted_results

def sync_products_to_chroma(products: list):
    """Syncs list of product objects from DB to ChromaDB."""
    print(f"Syncing {len(products)} products to ChromaDB (Local)...")
    
    ids = []
    documents = []
    embeddings = []
    metadatas = []
    
    for p in products:
        doc_text = f"Product Name: {p.name}. Price: {p.price}. Description: {p.note or 'No description'}. Stock: {p.stock} units."
        ids.append(f"prod_{p.id}")
        documents.append(doc_text)
        embeddings.append(get_embedding(doc_text))
        metadatas.append({"name": p.name, "id": p.id})
    
    if ids:
        product_collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas
        )
    print("Product sync complete.")

# Seed initial knowledge if empty
if collection.count() == 0:
    print("Seeding initial knowledge base (Local)...")
    docs = {
        "vrf_warranty": "The Samsung VRF System usually comes with a 1-year comprehensive warranty and 5 years on the compressor. AMC options are available.",
        "return_policy": "{company_name} allows returns for defective items within 7 days of delivery. Original packaging is required.",
        "support_hours": "Our support team is available Mon-Sat from 9 AM to 6 PM IST. Emergency support is available for contract customers."
    }
    for doc_id, text in docs.items():
        try:
            add_document(doc_id, text)
        except Exception as e:
            print(f"Failed to seed {doc_id}: {e}")
