# app/modules/ai/embeddings.py
from openai import AsyncOpenAI
import hashlib
from app.shared.cache import redis_cache

class EmbeddingService:
    MODEL = 'text-embedding-3-small'
    BATCH_SIZE = 100

    def __init__(self, client: AsyncOpenAI):
        self.client = client

    async def embed_chunks(self, chunks: list[str]) -> list[list[float]]:
        all_embeddings = []
        for i in range(0, len(chunks), self.BATCH_SIZE):
            batch = chunks[i:i + self.BATCH_SIZE]
            cached, uncached_idxs, uncached_texts = [], [], []
            for j, text in enumerate(batch):
                cache_key = f'emb:{{hashlib.md5(text.encode()).hexdigest()}}'
                cached_val = await redis_cache.get(cache_key)
                if cached_val:
                    cached.insert(j, cached_val)
                else:
                    uncached_idxs.append(j)
                    uncached_texts.append(text)
            if uncached_texts:
                response = await self.client.embeddings.create(
                    model=self.MODEL,
                    input=uncached_texts,
                )
                for k, emb in enumerate(response.data):
                    text = uncached_texts[k]
                    cache_key = f'emb:{{hashlib.md5(text.encode()).hexdigest()}}'
                    await redis_cache.set(cache_key, emb.embedding, ttl=2592000)
                    cached.insert(uncached_idxs[k], emb.embedding)
            all_embeddings.extend(cached)
        return all_embeddings
