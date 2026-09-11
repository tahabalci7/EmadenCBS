import fitz
import os
import subprocess
import tempfile

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class OCREngine:
    """
    Hibrit ve paralel PDF metin çıkarma motoru.

    Çalışma mantığı:

    1. Her sayfanın PDF metin katmanını kontrol eder.
    2. Sağlıklı metin katmanı varsa doğrudan kullanır.
    3. Metin bozuk veya yetersizse sayfayı OCR kuyruğuna alır.
    4. OCR gereken sayfalar paralel Tesseract işlemleriyle okunur.
    5. Sonuçlar yeniden gerçek PDF sayfa sırasına yerleştirilir.

    Böylece sağlıklı metin katmanına sahip sayfalar OCR edilmez,
    OCR gereken sayfalar da tek tek seri şekilde bekletilmez.
    """

    TESSERACT_EXE = Path(
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )

    OCR_LANGUAGE = "tur+eng"
    OCR_DPI = 300
    OCR_PSM = "4"

    MIN_TEXT_CHARACTERS = 50
    CANDIDATE_KEYWORDS = (
        "KOORDİNAT",
        "KOORDINAT",
        "UTM",
        "DATUM",
        "SAĞA",
        "SAGA",
        "YUKARI",
        "ENLEM",
        "BOYLAM",
        "PROJEKSİYON",
        "PROJEKSIYON",
        "ZON",
        "DOM",
        "RUHSAT ALANI",
        "RUHSAT SAHASI",
        "PROJE ALANI",
        "ÇED ALANI",
        "CED ALANI",
    )

    CANDIDATE_NEIGHBOR_PAGES = 1

    # Aynı anda çalışacak Tesseract sayısı.
    #
    # 2 ile başlıyoruz:
    # - CPU'yu tamamen kilitlemez.
    # - RAM kullanımını kontrollü tutar.
    # - 300 DPI OCR kalitesini değiştirmez.
    MAX_OCR_WORKERS = 2

    @classmethod
    def extract_text_layer(
        cls,
        pdf_path,
        max_pages=None,
    ):
        """
        PDF'nin yalnızca mevcut metin katmanını okur.

        Tesseract çalıştırmaz.
        Bu metod hızlı ilk tarama için kullanılır.
        """

        doc = fitz.open(
            pdf_path
        )

        page_count = len(doc)

        if max_pages is None:
            scan_limit = page_count
        else:
            scan_limit = min(
                page_count,
                max_pages,
            )

        extracted_parts = []

        try:
            for page_index in range(
                scan_limit
            ):
                page = doc[
                    page_index
                ]

                page_number = (
                    page_index + 1
                )

                page_text = (
                    page.get_text()
                )

                if not page_text.strip():
                    continue

                extracted_parts.append(
                    cls._format_page_text(
                        page_number,
                        page_text,
                        "PDF METİN KATMANI",
                    )
                )

        finally:
            doc.close()

        extracted_text = "\n".join(
            extracted_parts
        )

        return {
            "success": bool(
                extracted_text.strip()
            ),
            "method": "PDF Metin Katmanı",
            "text": extracted_text,
            "page_count": page_count,
            "scanned_pages": scan_limit,
            "text_layer_pages": len(
                extracted_parts
            ),
            "ocr_pages": 0,
            "failed_pages": (
                scan_limit
                - len(extracted_parts)
            ),
        }

    @classmethod
    def extract_text_layer_pages(
        cls,
        pdf_path,
        page_numbers,
    ):
        page_numbers = sorted(
            {
                int(page_number)
                for page_number in page_numbers
                if int(page_number) >= 1
            }
        )
        doc = fitz.open(pdf_path)
        page_count = len(doc)
        extracted_parts = []
        extracted_pages = []
        try:
            for page_number in page_numbers:
                if page_number > page_count:
                    continue
                page_text = doc[page_number - 1].get_text() or ""
                if not page_text.strip():
                    continue
                extracted_pages.append(page_number)
                extracted_parts.append(
                    cls._format_page_text(
                        page_number,
                        page_text,
                        "PDF METİN KATMANI",
                    )
                )
        finally:
            doc.close()

        extracted_text = "\n".join(extracted_parts)
        requested = [
            page_number
            for page_number in page_numbers
            if page_number <= page_count
        ]
        return {
            "success": bool(extracted_text.strip()),
            "method": "PDF Metin Katmanı",
            "text": extracted_text,
            "page_count": page_count,
            "scanned_pages": len(requested),
            "text_layer_pages": len(extracted_parts),
            "ocr_pages": 0,
            "failed_pages": (
                len(requested) - len(extracted_parts)
            ),
            "extracted_page_numbers": extracted_pages,
            "requested_page_numbers": requested,
        }

    @classmethod
    def extract_text(
        cls,
        pdf_path,
        max_pages=None,
    ):
        doc = fitz.open(pdf_path)

        page_count = len(doc)

        if max_pages is None:
            scan_limit = page_count
        else:
            scan_limit = min(
                page_count,
                max_pages,
            )

        scanned_pages = scan_limit

        page_results = {}

        text_layer_pages = 0
        ocr_pages = 0
        failed_pages = 0

        if not cls.TESSERACT_EXE.exists():
            tesseract_available = False
        else:
            tesseract_available = True

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(
                    temp_dir
                )

                ocr_jobs = []

                # -----------------------------------------
                # 1. SAYFALARI SINIFLANDIR
                # -----------------------------------------

                for page_index in range(
                    scan_limit
                ):
                    page = doc[
                        page_index
                    ]

                    page_number = (
                        page_index + 1
                    )

                    page_text = (
                        page.get_text()
                    )
                    
                    if not cls._has_usable_text(page_text):
                        print(
                            f"OCR adayı sayfa: {page_number}"
                        )                      
                    if cls._has_usable_text(
                        page_text
                    ):
                        text_layer_pages += 1

                        page_results[
                            page_number
                        ] = cls._format_page_text(
                            page_number,
                            page_text,
                            "PDF METİN KATMANI",
                        )

                        continue

                    # -------------------------------------
                    # OCR GEREKEN SAYFAYI RENDER ET
                    # -------------------------------------

                    if not tesseract_available:
                        if page_text.strip():
                            text_layer_pages += 1

                            page_results[
                                page_number
                            ] = cls._format_page_text(
                                page_number,
                                page_text,
                                (
                                    "PDF METİN KATMANI "
                                    "- TESSERACT YOK"
                                ),
                            )
                        else:
                            failed_pages += 1

                        continue

                    image_path = (
                        temp_path
                        / f"page_{page_number}.png"
                    )

                    pix = page.get_pixmap(
                        dpi=cls.OCR_DPI,
                        alpha=False,
                    )

                    pix.save(
                        str(image_path)
                    )

                    ocr_jobs.append(
                        (
                            page_number,
                            image_path,
                            page_text,
                        )
                    )

                # -----------------------------------------
                # 2. OCR GEREKEN SAYFALARI PARALEL ÇALIŞTIR
                # -----------------------------------------

                if ocr_jobs:
                    worker_count = min(
                        cls.MAX_OCR_WORKERS,
                        len(ocr_jobs),
                    )

                    with ThreadPoolExecutor(
                        max_workers=worker_count
                    ) as executor:
                        futures = {}

                        for (
                            page_number,
                            image_path,
                            fallback_text,
                        ) in ocr_jobs:
                            future = executor.submit(
                                cls._ocr_image,
                                image_path,
                                temp_path,
                                page_number,
                            )

                            futures[
                                future
                            ] = (
                                page_number,
                                fallback_text,
                            )

                        for future, job_info in (
                            futures.items()
                        ):
                            (
                                page_number,
                                fallback_text,
                            ) = job_info

                            try:
                                ocr_text = (
                                    future.result()
                                )
                            except Exception as error:
                                print(
                                    f"OCR hatası - "
                                    f"Sayfa {page_number}: "
                                    f"{error}"
                                )

                                ocr_text = ""

                            if ocr_text.strip():
                                ocr_pages += 1

                                page_results[
                                    page_number
                                ] = (
                                    cls._format_page_text(
                                        page_number,
                                        ocr_text,
                                        "OCR",
                                    )
                                )

                            elif fallback_text.strip():
                                text_layer_pages += 1

                                page_results[
                                    page_number
                                ] = (
                                    cls._format_page_text(
                                        page_number,
                                        fallback_text,
                                        (
                                            "PDF METİN KATMANI "
                                            "- OCR BAŞARISIZ"
                                        ),
                                    )
                                )

                            else:
                                failed_pages += 1

        finally:
            doc.close()

        # ---------------------------------------------
        # 3. PDF SAYFA SIRASINI KORU
        # ---------------------------------------------

        extracted_parts = []

        for page_number in range(
            1,
            scan_limit + 1,
        ):
            page_result = (
                page_results.get(
                    page_number
                )
            )

            if page_result:
                extracted_parts.append(
                    page_result
                )

        extracted_text = "\n".join(
            extracted_parts
        )

        if not extracted_text.strip():
            return {
                "success": False,
                "method": "Metin çıkarılamadı",
                "text": (
                    "PDF içinde kullanılabilir metin "
                    "veya OCR sonucu bulunamadı."
                ),
                "page_count": page_count,
                "scanned_pages": scanned_pages,
                "text_layer_pages": text_layer_pages,
                "ocr_pages": ocr_pages,
                "failed_pages": failed_pages,
            }

        method = cls._build_method_name(
            text_layer_pages=text_layer_pages,
            ocr_pages=ocr_pages,
        )

        return {
            "success": True,
            "method": method,
            "text": extracted_text,
            "page_count": page_count,
            "scanned_pages": scanned_pages,
            "text_layer_pages": text_layer_pages,
            "ocr_pages": ocr_pages,
            "failed_pages": failed_pages,
        }
    @classmethod
    def extract_selected_pages(
        cls,
        pdf_path,
        page_numbers,
    ):
        """
        Yalnızca verilen PDF sayfalarını 300 DPI OCR eder.

        page_numbers:
            1 tabanlı PDF sayfa numaraları.
        """

        page_numbers = sorted(
            {
                int(page_number)
                for page_number in page_numbers
                if int(page_number) >= 1
            }
        )

        doc = fitz.open(
            pdf_path
        )

        page_count = len(doc)

        valid_pages = [
            page_number
            for page_number in page_numbers
            if page_number <= page_count
        ]

        page_results = {}
        failed_pages = 0

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(
                    temp_dir
                )

                jobs = []

                for page_number in valid_pages:
                    page = doc[
                        page_number - 1
                    ]

                    image_path = (
                        temp_path
                        / f"selected_{page_number}.png"
                    )

                    pix = page.get_pixmap(
                        dpi=cls.OCR_DPI,
                        alpha=False,
                    )

                    pix.save(
                        str(image_path)
                    )

                    jobs.append(
                        (
                            page_number,
                            image_path,
                        )
                    )

                if jobs:
                    worker_count = min(
                        cls.MAX_OCR_WORKERS,
                        len(jobs),
                    )

                    with ThreadPoolExecutor(
                        max_workers=worker_count
                    ) as executor:
                        futures = {}

                        for (
                            page_number,
                            image_path,
                        ) in jobs:
                            future = executor.submit(
                                cls._ocr_image,
                                image_path,
                                temp_path,
                                page_number,
                            )

                            futures[
                                future
                            ] = page_number

                        for future, page_number in (
                            futures.items()
                        ):
                            try:
                                ocr_text = (
                                    future.result()
                                )
                            except Exception as error:
                                print(
                                    f"OCR hatası - "
                                    f"Sayfa {page_number}: "
                                    f"{error}"
                                )

                                ocr_text = ""

                            if ocr_text.strip():
                                page_results[
                                    page_number
                                ] = cls._format_page_text(
                                    page_number,
                                    ocr_text,
                                    "OCR",
                                )
                            else:
                                failed_pages += 1

        finally:
            doc.close()

        extracted_parts = []

        for page_number in valid_pages:
            page_text = page_results.get(
                page_number
            )

            if page_text:
                extracted_parts.append(
                    page_text
                )

        extracted_text = "\n".join(
            extracted_parts
        )

        return {
            "success": bool(
                extracted_text.strip()
            ),
            "method": "Seçili Sayfalarda OCR",
            "text": extracted_text,
            "page_count": page_count,
            "scanned_pages": len(
                valid_pages
            ),
            "text_layer_pages": 0,
            "ocr_pages": (
                len(valid_pages)
                - failed_pages
            ),
            "failed_pages": failed_pages,
        }
    @classmethod
    def _has_usable_text(
        cls,
        text,
    ):
        """
        PDF metin katmanının gerçekten okunabilir
        olup olmadığını kontrol eder.

        Metnin sadece mevcut olması yeterli değildir.
        Bozuk font encoding'i varsa OCR kullanılmalıdır.
        """

        if not text:
            return False

        clean_text = "".join(
            character
            for character in text
            if not character.isspace()
        )

        if (
            len(clean_text)
            < cls.MIN_TEXT_CHARACTERS
        ):
            return False

        total_characters = len(
            clean_text
        )

        control_characters = sum(
            1
            for character in clean_text
            if ord(character) < 32
        )

        control_ratio = (
            control_characters
            / total_characters
        )

        if control_ratio > 0.01:
            return False

        letters = sum(
            1
            for character in clean_text
            if character.isalpha()
        )

        digits = sum(
            1
            for character in clean_text
            if character.isdigit()
        )

        readable_characters = (
            letters
            + digits
        )

        readable_ratio = (
            readable_characters
            / total_characters
        )

        if readable_ratio < 0.45:
            return False

        suspicious_sequences = (
            "7DEOR",
            ".RRU",
            "5XKVDW",
            "6D÷D",
            "<XNDU",
            "'DWXP",
            "GOOHN",
            "32/Ø*21",
            "&2Ö5$",
        )

        upper_text = (
            text.upper()
        )

        suspicious_count = sum(
            1
            for sequence in suspicious_sequences
            if sequence.upper() in upper_text
        )

        if suspicious_count >= 2:
            return False

        return True

    @classmethod
    def _ocr_image(
        cls,
        image_path,
        temp_path,
        page_number,
    ):
        """
        Önceden render edilmiş tek bir sayfa görüntüsünü
        Tesseract ile OCR eder.

        Bu fonksiyon ThreadPoolExecutor içinde paralel
        çalıştırılabilir.
        """

        output_base = (
            temp_path
            / f"page_{page_number}_ocr"
        )

        command = [
            str(cls.TESSERACT_EXE),
            str(image_path),
            str(output_base),
            "-l",
            cls.OCR_LANGUAGE,
            "--psm",
            cls.OCR_PSM,
        ]

        subprocess.run(
            command,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        text_path = Path(
            str(output_base) + ".txt"
        )

        if not text_path.exists():
            return ""

        return text_path.read_text(
            encoding="utf-8",
            errors="ignore",
        )

    @staticmethod
    def _format_page_text(
        page_number,
        text,
        source,
    ):
        return (
            f"\n--- Sayfa {page_number} "
            f"[{source}] ---\n"
            f"{text.strip()}\n"
        )

    @staticmethod
    def _build_method_name(
        text_layer_pages,
        ocr_pages,
    ):
        if (
            text_layer_pages > 0
            and ocr_pages > 0
        ):
            return (
                "PDF Metin Katmanı + OCR"
            )

        if ocr_pages > 0:
            return "OCR"

        return "PDF Metin Katmanı"