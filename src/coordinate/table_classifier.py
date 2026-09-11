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
                "URETIM IZIN ALANI",
                "HAMMADDE URETIM IZIN",
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
                    "POLIGON",
                    "IZIN",
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

        if (
            "PASA" in normalized
            and "ALAN" in normalized
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
        ) or (
            "STOK" in normalized
            and "ALAN" in normalized
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
        ) or (
            "OCAK" in normalized
            and "ALAN" in normalized
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

        prefix_hint = cls._classify_prefix_hint(
            table_text
        )

        if prefix_hint != "DIGER":
            return prefix_hint

        return "DIGER"

    PAGE_MARKER_PATTERN = re.compile(
        r"^--- Sayfa \d+ \[[^\]\r\n]+\] ---$"
    )

    NUMBERED_TABLE_CAPTION_PATTERN = re.compile(
        r"^(?:TABLO|CIZELGE|TABLE)[-.\s]+\d+"
    )

    CRS_METADATA_LINE_PATTERN = re.compile(
        r"^(?:"
        r"KOORDINAT\s+SIRASI|"
        r"KOOR\s+SIRASI|"
        r"DATUM|"
        r"TURU|"
        r"PROJEKSIYON|"
        r"D\s*O\s*M|"
        r"ZON|"
        r"OLCEK(?:\s+FAKTORU)?|"
        r"PAFTA(?:\s+NO)?|"
        r"ENLEM|"
        r"BOYLAM|"
        r"WGS\s*84|"
        r"ED\s*50|"
        r"UTM|"
        r"SAGA(?:\s+YUKARI)?|"
        r"YUKARI"
        r")(?:\s|$)"
    )

    RUNNING_PAGE_HEADER_PATTERN = re.compile(
        r"^(?:NIHAI\s+)?CED\s+RAPORU$"
    )

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

        for index, line in enumerate(lines[:20]):

            if cls._looks_like_context_noise_line(line):
                continue

            normalized = cls._normalize(line)

            if cls.NUMBERED_TABLE_CAPTION_PATTERN.match(
                normalized
            ):
                heading_lines = [line]

                # OCR bazı başlıkları iki veya üç satıra bölebilir.
                for next_line in lines[
                    index + 1:index + 4
                ]:
                    if cls._looks_like_context_noise_line(
                        next_line
                    ):
                        break

                    next_normalized = cls._normalize(
                        next_line
                    )

                    # Veri satırına gelmişsek dur.
                    if (
                        cls._looks_like_coordinate_data(
                            next_normalized
                        )
                        or cls._looks_like_numeric_or_pair_line(
                            next_line
                        )
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

        for index, line in enumerate(lines[:20]):

            if cls._looks_like_context_noise_line(line):
                continue

            normalized = cls._normalize(line)

            if "KOORDINAT" not in normalized:
                continue

            # Başlığın bir önceki satıra bölünmüş olma
            # ihtimalini de hesaba kat.
            if index > 0:
                previous = lines[index - 1]

                if (
                    not cls._looks_like_context_noise_line(
                        previous
                    )
                    and not cls._looks_like_coordinate_data(
                        cls._normalize(previous)
                    )
                    and len(previous.strip()) <= 80
                    and previous.count(",") < 2
                ):
                    return (
                        previous
                        + " "
                        + line
                    )

            return line

        # -----------------------------------------------------
        # SON ÇARE:
        # İlk birkaç anlamlı satır. Tekrarlayan CRS
        # metadata veya sayfa üst bilgisi başlık değildir.
        # -----------------------------------------------------

        meaningful = []

        for line in lines[:20]:
            if cls._looks_like_context_noise_line(line):
                continue

            if (
                cls._looks_like_coordinate_data(
                    cls._normalize(line)
                )
                or cls._looks_like_numeric_or_pair_line(
                    line
                )
            ):
                break

            if len(line.strip()) < 8:
                continue

            meaningful.append(line)

            if len(meaningful) >= 3:
                break

        return " ".join(
            meaningful
        )

    @classmethod
    def _classify_prefix_hint(
        cls,
        table_text: str,
    ) -> str:
        """
        Numbered Tablo caption yoksa veya başlık
        çıkarma şirket/rapor satırına düştüyse,
        koordinat verisinden önceki alan başlığını
        ayrıca dene. Böylece ÇED tabloları DIGER
        kalıp önceki RUHSAT bağlamını devralmaz.
        """

        window = []

        for line in table_text.splitlines()[:30]:
            value = line.strip()

            if not value:
                continue

            if cls._looks_like_context_noise_line(value):
                continue

            normalized = cls._normalize(value)

            if (
                cls._looks_like_coordinate_data(
                    normalized
                )
                or cls._looks_like_numeric_or_pair_line(
                    value
                )
            ):
                break

            window.append(value)
            del window[:-3]

            for start in range(len(window)):
                candidate = cls._normalize(
                    " ".join(window[start:])
                )
                hinted = cls._classify_ced_heading(
                    candidate
                )

                if hinted != "DIGER":
                    return hinted

        return "DIGER"

    @classmethod
    def _classify_ced_heading(
        cls,
        normalized: str,
    ) -> str:
        if "CED" not in normalized:
            return "DIGER"

        if not cls._contains_any(
            normalized,
            [
                "ALAN",
                "SAHA",
                "SINIR",
                "KOORDINAT",
                "POLIGON",
                "IZIN",
            ],
        ):
            return "DIGER"

        if re.search(r"\bMEVCUT\b", normalized):
            return "MEVCUT_CED_ALANI"

        if (
            re.search(r"\bYENI\b", normalized)
            or cls._contains_any(
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

        return "CED_ALANI"

    @classmethod
    def _looks_like_context_noise_line(
        cls,
        line: str,
    ) -> bool:
        value = str(line).strip()

        if not value or value == ":":
            return True

        if cls.PAGE_MARKER_PATTERN.fullmatch(value):
            return True

        if cls._looks_like_running_page_header(value):
            return True

        return cls._looks_like_crs_metadata_line(
            value
        )

    @classmethod
    def _looks_like_crs_metadata_line(
        cls,
        line: str,
    ) -> bool:
        normalized = cls._normalize(line)

        if not normalized:
            return False

        return bool(
            cls.CRS_METADATA_LINE_PATTERN.match(
                normalized
            )
        )

    @classmethod
    def _looks_like_running_page_header(
        cls,
        line: str,
    ) -> bool:
        normalized = cls._normalize(line)

        return bool(
            cls.RUNNING_PAGE_HEADER_PATTERN.match(
                normalized
            )
        )

    @classmethod
    def _has_numbered_table_caption(
        cls,
        table_text: str,
    ) -> bool:
        for line in table_text.splitlines()[:20]:
            if cls._looks_like_context_noise_line(line):
                continue

            if cls.NUMBERED_TABLE_CAPTION_PATTERN.match(
                cls._normalize(line)
            ):
                return True

        return False

    @classmethod
    def _is_headerless_continuation(
        cls,
        table_text: str,
    ) -> bool:
        return not cls._has_numbered_table_caption(
            table_text
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
    def _looks_like_numeric_or_pair_line(
        line: str,
    ) -> bool:
        value = str(line).strip()

        if not value:
            return False

        if re.fullmatch(
            r"[+-]?\d+(?:[.,]\d+)?",
            value,
        ):
            return True

        return bool(
            re.fullmatch(
                r"[+-]?\d+(?:[.,]\d+)?"
                r"\s*:\s*"
                r"[+-]?\d+(?:[.,]\d+)?",
                value,
            )
        )

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