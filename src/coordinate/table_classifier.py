import re
import unicodedata


class TableClassifier:
    """
    Koordinat tablolarını başlıklarına göre sınıflandırır.

    Temel prensip:
    - Tablonun tamamını sınıflandırmada kullanmaz.
    - Öncelikle koordinat tablosunun başlığını bulur.
    - OCR kaynaklı Türkçe karakter / boşluk hatalarını
      normalize eder.
    - Nokta adlarına bağlı değildir.
    - Farklı ÇED raporlarında kullanılabilecek genel
      başlık yapıları üzerinden çalışır.
    """

    # ---------------------------------------------------------
    # ANA SINIFLANDIRMA
    # ---------------------------------------------------------

    @classmethod
    def classify(cls, table_text: str) -> str:

        heading = cls._extract_heading(table_text)

        normalized = cls._normalize(heading)

        # -----------------------------------------------------
        # 1. ÇALIŞMA YAPILMAYACAK / KORUNACAK ALAN
        # -----------------------------------------------------

        if cls._contains_any(
            normalized,
            [
                "CALISMA YAPILMAYACAK",
                "CALISILMAYACAK",
                "CALISMA YAPILMAMASI",
                "FAALIYET YAPILMAYACAK",
                "FAALIYET YURUTULMEYECEK",
            ],
        ):
            return "CALISILMAYACAK_ALAN"

        # -----------------------------------------------------
        # 2. GALERİ
        # -----------------------------------------------------

        if cls._contains_any(
            normalized,
            [
                "GALERI AGZI",
                "GALERI ALANI",
                "GALERI GIRISI",
                "GALERI GIRIS",
                "GALERI",
            ],
        ):
            return "GALERI_ALANI"
        # -----------------------------------------------------
        # TALEP EDİLEN / PROJEYE KONU ÇED ALANI
        # -----------------------------------------------------

        if (
            "CED" in normalized
            and cls._contains_any(
                normalized,
                [
                    "TALEP EDILEN",
                    "PROJEYE KONU",
                    "PLANLANAN",
                    "ONGORULEN",
                ],
            )
        ):
            return "YENI_CED_ALANI"
        # -----------------------------------------------------
        # 3. YENİ ÇED ALANI
        # -----------------------------------------------------

        if (
            (
                "CED" in normalized
                and cls._contains_any(
                    normalized,
                    [
                        "YENI",
                        "GENISLEME",
                        "ILAVE",
                        "EK ALAN",
                        "KAPASITE ARTISI",
                        "EK KAPASITE ARTISI",
                    ],
                )
            )
            or (
                cls._contains_any(
                    normalized,
                    [
                        "YENI OCAK",
                        "PLANLANAN YENI",
                        "KAPASITE ARTISI OLARAK PLANLANAN YENI",
                        "EK KAPASITE ARTISI OLARAK PLANLANAN YENI",
                    ],
                )
                and "KOORDINAT" in normalized
            )
        ):
            return "YENI_CED_ALANI"

        # -----------------------------------------------------
        # 4. MEVCUT ÇED ALANI
        # -----------------------------------------------------

        if (
            "CED" in normalized
            and "MEVCUT" in normalized
        ):
            return "MEVCUT_CED_ALANI"

        # -----------------------------------------------------
        # 5. İŞLETME İZİN ALANI
        # -----------------------------------------------------

        if cls._contains_any(
            normalized,
            [
                "ISLETME IZIN ALANI",
                "ISLETME IZIN SAHASI",
                "ISLETME IZNI ALANI",
                "ISLETME IZNI SAHASI",
            ],
        ):
            return "ISLETME_IZIN_ALANI"

        # -----------------------------------------------------
        # 6. ÇED ALANI
        # -----------------------------------------------------

        if (
            "CED" in normalized
            and cls._contains_any(
                normalized,
                [
                    "ALAN",
                    "SAHA",
                    "SINIR",
                    "KOORDINAT",
                ],
            )
        ):
            return "CED_ALANI"
        # -----------------------------------------------------
        # YARDIMCI PROJE / MADENCİLİK ALANLARI
        # -----------------------------------------------------

        if cls._contains_any(
            normalized,
            [
                "BITKISEL TOPRAK DEPO ALANI",
                "BITKISEL TOPRAK DEPOLAMA ALANI",
                "BITKISEL TOPRAK STOK ALANI",
                "BITKISEL TOPRAK ALANI",
            ],
        ):
            return "BITKISEL_TOPRAK_ALANI"

        if cls._contains_any(
            normalized,
            [
                "PASA DEPO ALANI",
                "PASA DEPOLAMA ALANI",
                "PASA DOKUM ALANI",
                "PASA ALANI",
            ],
        ):
            return "PASA_ALANI"

        if cls._contains_any(
            normalized,
            [
                "STOK ALANI",
                "STOK SAHASI",
                "CEVHER STOK ALANI",
                "MADEN STOK ALANI",
                "URUN STOK ALANI",
            ],
        ):
            return "STOK_ALANI"

        if cls._contains_any(
            normalized,
            [
                "SANTIYE ALANI",
                "SANTIYE SAHASI",
                "SANTIYE YERLESIM ALANI",
                "SANTIYE TESIS ALANI",
            ],
        ):
            return "SANTIYE_ALANI"

        if cls._contains_any(
            normalized,
            [
                "OCAK ALANI",
                "OCAK SAHASI",
                "ACIK OCAK ALANI",
                "ACIK OCAK SAHASI",
                "URETIM ALANI",
                "URETIM SAHASI",
            ],
        ):
            return "OCAK_ALANI"

        if cls._contains_any(
            normalized,
            [
                "KIRMA ELEME TESIS ALANI",
                "KIRMA ELEME TESISI ALANI",
                "KIRMA ELEME ALANI",
                "KIRMA ELEME YIKAMA TESISI",
                "KIRMA ELEME YIKAMA TESIS ALANI",
                "KIRMA ELEME YIKAMA TESISI ALANI",
                "KIRMA-ELEME-YIKAMA TESISI",
                "KIRMA-ELEME-YIKAMA TESIS ALANI",
                "KIRMA-ELEME-YIKAMA TESISI ALANI",
            ],
        ):
            return "KIRMA_ELEME_ALANI"

        if cls._contains_any(
            normalized,
            [
                "CEVHER HAZIRLAMA TESIS ALANI",
                "CEVHER HAZIRLAMA TESISI ALANI",
                "CEVHER HAZIRLAMA ALANI",
            ],
        ):
            return "CEVHER_HAZIRLAMA_ALANI"

        if cls._contains_any(
            normalized,
            [
                "ATIK DEPOLAMA ALANI",
                "ATIK DEPO ALANI",
                "ATIK ALANI",
            ],
        ):
            return "ATIK_ALANI"

        if cls._contains_any(
            normalized,
            [
                "SEDIMANTASYON HAVUZU",
                "COKELTME HAVUZU",
                "COKELTIM HAVUZU",
            ],
        ):
            return "HAVUZ_ALANI"
        # -----------------------------------------------------
        # 7. PROJE ALANI
        # -----------------------------------------------------

        if cls._contains_any(
            normalized,
            [
                "PROJEYE KONU ALAN",
                "PROJEYE KONU SAHA",
                "PROJE ALANI",
                "PROJE SAHASI",
                "FAALIYET ALANI",
                "FAALIYET SAHASI",
            ],
        ):
            return "PROJE_ALANI"

        # -----------------------------------------------------
        # 8. RUHSAT ALANI
        # -----------------------------------------------------

        if cls._contains_any(
            normalized,
            [
                "RUHSAT ALANI",
                "RUHSAT SAHASI",
                "RUHSAT SINIRI",
            ],
        ):
            return "RUHSAT_ALANI"

        return "DIGER"

    # ---------------------------------------------------------
    # TABLO BAŞLIĞINI BUL
    # ---------------------------------------------------------

    @classmethod
    def _extract_heading(cls, table_text: str) -> str:
        """
        Tablonun sınıflandırma açısından anlamlı başlığını
        çıkarmaya çalışır.

        Öncelik:
        1. "Tablo XX..." şeklindeki satır
        2. Koordinat kelimesi içeren ilk anlamlı satır
        3. İlk birkaç satır

        Böylece tablonun alt kısmında geçen başka alan
        isimlerinin sınıflandırmayı bozması engellenir.
        """

        lines = [
            line.strip()
            for line in table_text.splitlines()
            if line.strip()
        ]

        if not lines:
            return ""

        # -----------------------------------------------------
        # TABLO XX BAŞLIĞI
        # -----------------------------------------------------

        for index, line in enumerate(lines[:15]):

            normalized = cls._normalize(line)

            if re.match(
                r"^TABLO\s*\d+",
                normalized,
            ):
                heading_lines = [line]

                # OCR bazı başlıkları iki veya üç satıra bölebilir.
                for next_line in lines[
                    index + 1:index + 4
                ]:
                    next_normalized = cls._normalize(
                        next_line
                    )

                    # Veri satırına gelmişsek dur.
                    if cls._looks_like_coordinate_data(
                        next_normalized
                    ):
                        break

                    heading_lines.append(
                        next_line
                    )

                    # Koordinat başlığı tamamlandıysa
                    # daha fazla ilerlemeye gerek yok.
                    if "KOORDINAT" in next_normalized:
                        break

                return " ".join(
                    heading_lines
                )

        # -----------------------------------------------------
        # KOORDİNAT KELİMESİ İÇEREN BAŞLIK
        # -----------------------------------------------------

        for index, line in enumerate(lines[:15]):

            normalized = cls._normalize(line)

            if "KOORDINAT" in normalized:

                # Başlığın bir önceki satıra bölünmüş olma
                # ihtimalini de hesaba kat.
                if index > 0:
                    previous = lines[index - 1]

                    if not cls._looks_like_coordinate_data(
                        cls._normalize(previous)
                    ):
                        return (
                            previous
                            + " "
                            + line
                        )

                return line

        # -----------------------------------------------------
        # SON ÇARE:
        # İlk birkaç satır.
        # -----------------------------------------------------

        return " ".join(
            lines[:3]
        )

    # ---------------------------------------------------------
    # NORMALİZASYON
    # ---------------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        """
        Türkçe karakterleri ve OCR kaynaklı bazı farklılıkları
        karşılaştırma için normalize eder.
        """

        text = text.upper()

        replacements = {
            "Ç": "C",
            "Ğ": "G",
            "İ": "I",
            "İ": "I",
            "Ö": "O",
            "Ş": "S",
            "Ü": "U",
        }

        for old, new in replacements.items():
            text = text.replace(
                old,
                new,
            )

        text = unicodedata.normalize(
            "NFKD",
            text,
        )

        text = "".join(
            char
            for char in text
            if not unicodedata.combining(char)
        )

        # OCR / noktalama farklarını boşluğa çevir.
        text = re.sub(
            r"[_/\\|:;,.()\[\]{}]+",
            " ",
            text,
        )

        # Çoklu boşlukları temizle.
        text = re.sub(
            r"\s+",
            " ",
            text,
        )

        return text.strip()

    # ---------------------------------------------------------
    # YARDIMCI
    # ---------------------------------------------------------

    @staticmethod
    def _contains_any(
        text: str,
        patterns,
    ) -> bool:

        return any(
            pattern in text
            for pattern in patterns
        )

    # ---------------------------------------------------------
    # KOORDİNAT VERİ SATIRI KONTROLÜ
    # ---------------------------------------------------------

    @staticmethod
    def _looks_like_coordinate_data(
        normalized_line: str,
    ) -> bool:
        """
        Başlık toplarken koordinat verilerine geçildiğini
        anlamak için kaba fakat genel bir kontrol.
        """

        numbers = re.findall(
            r"\d+(?:[.,]\d+)?",
            normalized_line,
        )

        if len(numbers) < 2:
            return False

        large_number_count = 0

        for number in numbers:

            try:
                value = float(
                    number.replace(
                        ",",
                        ".",
                    )
                )
            except ValueError:
                continue

            if (
                100000 <= value <= 999999
                or
                3000000 <= value <= 5000000
            ):
                large_number_count += 1

        return large_number_count >= 2