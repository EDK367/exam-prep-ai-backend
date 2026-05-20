def split_text(text, chunk_size=300, overlap=300):
    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)

        step = chunk_size - overlap
        if step <= 0:
            step = chunk_size  # Fallback to no overlap if overlap is invalid
        start += step

    return chunks