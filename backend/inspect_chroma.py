import chromadb
import os

db_path = os.path.join(os.getcwd(), 'knowledge_base')
print(f"Checking ChromaDB at: {db_path}")

client = chromadb.PersistentClient(path=db_path)
collection = client.get_or_create_collection(name='yexis_products_local')

print(f"Total count in 'products' collection: {collection.count()}")

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

results = collection.get(limit=20, include=['metadatas', 'documents'])
print("\nSample Entries:")
for i, m, d in zip(results['ids'], results['metadatas'], results['documents']):
    print(f"ID: {i} | Name: {m.get('name')} | Content: {d[:100]}...")
