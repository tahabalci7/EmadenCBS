import fitz  # PyMuPDF


def pdf_oku(pdf_yolu):

    """
    PDF içindeki metni okur
    """

    metin = ""

    try:

        belge = fitz.open(pdf_yolu)

        for sayfa in belge:
            metin += sayfa.get_text()

        belge.close()

    except Exception as hata:

        print("PDF okuma hatası:", hata)

    return metin


if __name__ == "__main__":

    dosya = input("PDF yolu: ")

    sonuc = pdf_oku(dosya)

    print("\n--- PDF ANALİZ ---\n")

    print("Karakter sayısı:", len(sonuc))

    print("\n--- İLK 2000 KARAKTER ---\n")

    print(sonuc[:2000])
import pytesseract

pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"