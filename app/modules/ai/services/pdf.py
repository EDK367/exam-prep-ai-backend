from io import BytesIO

from pypdf import PdfReader


def extract_text_from_pdf(file_bytes):
    reader = PdfReader(BytesIO(file_bytes))
    text = ""
    
    for page in reader.pages:
        if page.extract_text():
            text += page.extract_text()
    return text