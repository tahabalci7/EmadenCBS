import fitz
import os


class PDFAnalyzer:

    @staticmethod
    def analyze(pdf_path):

        doc = fitz.open(pdf_path)

        total_characters = 0

        for page in doc:
            total_characters += len(page.get_text())

        result = {
            "Dosya": os.path.basename(pdf_path),
            "Sayfa Sayısı": len(doc),
            "Toplam Karakter": total_characters,
            "Metin Var": "Evet" if total_characters > 0 else "Hayır",
            "OCR Gerekli": "Hayır" if total_characters > 0 else "Evet"
        }

        doc.close()

        return result