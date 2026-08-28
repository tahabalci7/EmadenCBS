import fitz
import pytesseract

from PIL import Image


# Tesseract yolu
pytesseract.pytesseract.tesseract_cmd = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)


def pdf_ocr_oku(pdf_yolu):

    """
    Taranmış PDF'lerden OCR ile metin okur
    """

    metin = ""

    belge = fitz.open(pdf_yolu)

    for sayfa_no, sayfa in enumerate(belge):

        print(
            f"{sayfa_no + 1}. sayfa okunuyor..."
        )

        # PDF sayfasını görüntüye çevir
        pix = sayfa.get_pixmap(
            dpi=300
        )

        image = Image.frombytes(
            "RGB",
            [pix.width, pix.height],
            pix.samples
        )

        # OCR
        sayfa_metni = pytesseract.image_to_string(
            image,
            lang="tur"
        )

        metin += sayfa_metni


    belge.close()

    return metin
if __name__ == "__main__":

    pdf = input(
        "PDF yolu: "
    )

    pdf = pdf.strip('"')

    sonuc = pdf_ocr_oku(pdf)

    print("\n--- OCR SONUÇ ---")

    print(
        "Karakter sayısı:",
        len(sonuc)
    )

    print(
        sonuc[:2000]
    )


    with open(
        "ocr_sonuc.txt",
        "w",
        encoding="utf-8"
    ) as f:

        f.write(sonuc)


    print(
        "ocr_sonuc.txt oluşturuldu"
    )


