import pytesseract
from pdf2image import convert_from_bytes


def extract_text_with_ocr(file_bytes):
    images = convert_from_bytes(file_bytes)
    text = ""
    
    for img in images:
        text += pytesseract.image_to_string(img, lang="spa") + "\n"
    return text