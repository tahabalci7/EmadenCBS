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
        primary_normalized = cls._normalize(
            cls.strip_parentheticals(heading)
        )

        # Parenthetical "(Talep Edilen ÇED Alanı)" on a tesisi/stok
        # caption is section context, not the table's area type.
        auxiliary = cls._classify_auxiliary_primary(
            primary_normalized
        )
        if auxiliary != "DIGER":
            return auxiliary

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
        # RUHSAT / SİCİL NOLU ALAN (before generic ÇED+ALAN)
        # -----------------------------------------------------

        if cls._looks_like_ruhsat_heading(normalized):
            return "RUHSAT_ALANI"

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
                "KIRMA ELEME TESISI",
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

        if (
            (
                "UNITESI" in normalized
                or re.search(r"\bUNITE\b", normalized)
            )
            and "KOORDINAT" in normalized
        ):
            return "TESIS_ALANI"

        if (
            "TESISI" in normalized
            and "KOORDINAT" in normalized
        ):
            return "TESIS_ALANI"

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

    PARENTHETICAL_PATTERN = re.compile(r"\([^)]*\)")

    AUXILIARY_AREA_TYPES = frozenset(
        {
            "STOK_ALANI",
            "TESIS_ALANI",
            "KIRMA_ELEME_ALANI",
            "PASA_ALANI",
            "HAVUZ_ALANI",
            "SANTIYE_ALANI",
            "BITKISEL_TOPRAK_ALANI",
            "ATIK_ALANI",
            "CEVHER_HAZIRLAMA_ALANI",
            "DEPOLAMA_ALANI",
            "GALERI_ALANI",
            "OCAK_ALANI",
        }
    )

    DOMINANT_AREA_TYPES = frozenset(
        {
            "RUHSAT_ALANI",
            "PROJE_ALANI",
            "ISLETME_IZIN_ALANI",
            "CED_ALANI",
            "YENI_CED_ALANI",
            "MEVCUT_CED_ALANI",
        }
    )

    # ---------------------------------------------------------
    # TABLO BAŞLIĞINI BUL
    # ---------------------------------------------------------

    @classmethod
    def _looks_like_ruhsat_heading(cls, normalized: str) -> bool:
        if cls._contains_any(
            normalized,
            [
                "RUHSAT ALANI",
                "RUHSAT SAHASI",
                "RUHSAT SINIRI",
                "RUHSAT POLIGON",
                "RUHSATLI ALAN",
            ],
        ):
            return True

        return (
            "SICIL" in normalized
            and "NOLU" in normalized
            and "ALAN" in normalized
        )

    @classmethod
    def strip_parentheticals(cls, text: str) -> str:
        """Remove (...) phrases so tesisi/stok nouns beat ÇED context."""

        return cls.PARENTHETICAL_PATTERN.sub(" ", str(text or ""))

    @classmethod
    def detect_ced_context_type(cls, text: str):
        """ÇED phrase anywhere on the line, including parentheticals."""

        normalized = cls._normalize(text)
        if "CED" not in normalized:
            return None

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
            return None

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
    def _classify_auxiliary_primary(cls, normalized_primary: str) -> str:
        """Type from the caption noun outside parentheticals."""

        if not normalized_primary:
            return "DIGER"

        if (
            "STOK" in normalized_primary
            and "ALAN" in normalized_primary
        ):
            return "STOK_ALANI"

        if (
            "KIRMA" in normalized_primary
            and "ELEME" in normalized_primary
            and (
                "TESIS" in normalized_primary
                or "ALAN" in normalized_primary
            )
            and (
                "KOORDINAT" in normalized_primary
                or "ALAN" in normalized_primary
                or "TABLO" in normalized_primary
            )
        ):
            return "KIRMA_ELEME_ALANI"

        if (
            (
                "UNITESI" in normalized_primary
                or re.search(r"\bUNITE\b", normalized_primary)
            )
            and "KOORDINAT" in normalized_primary
        ):
            return "TESIS_ALANI"

        if (
            "TESISI" in normalized_primary
            and "KOORDINAT" in normalized_primary
        ):
            return "TESIS_ALANI"

        return "DIGER"

    @classmethod
    def table_looks_geographic_primary(cls, table_text: str) -> bool:
        """True when the slice is a lon/lat table, not UTM saga/yukarı."""

        normalized = cls._normalize(table_text)
        has_geo_header = cls._contains_any(
            normalized,
            [
                "COGRAFI",
                "ENLEM",
                "BOYLAM",
                "WGS 84",
                "WGS84",
            ],
        )
        utm_y = 0
        utm_x = 0
        geo = 0
        for line in str(table_text).splitlines():
            for token in re.findall(r"\d+[.,]?\d*", line):
                try:
                    value = float(token.replace(",", "."))
                except ValueError:
                    continue
                if 100000 <= value <= 999999:
                    utm_y += 1
                elif 3000000 <= value <= 5000000:
                    utm_x += 1
                elif 35 <= value <= 43 or 25 <= value <= 46:
                    geo += 1
        if utm_y >= 3 and utm_x >= 3:
            return False
        return has_geo_header or geo >= 6

    @classmethod
    def _extract_heading(cls, table_text: str) -> str:
        """
        Tablonun sınıflandırma açısından anlamlı başlığını
        çıkarmaya çalışır.

        Öncelik:
        1. "Tablo XX..." şeklindeki satır (anywhere — PDF reading
           order can emit the body before the caption)
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

        numbered = cls._extract_numbered_caption(
            lines
        )

        if numbered:
            return numbered

        # -----------------------------------------------------
        # KOORDİNAT KELİMESİ İÇEREN BAŞLIK
        # -----------------------------------------------------

        for index, line in enumerate(lines):

            if cls._looks_like_context_noise_line(line):
                continue

            normalized = cls._normalize(line)

            if "KOORDINAT" not in normalized:
                continue

            if (
                cls._looks_like_coordinate_data(
                    normalized
                )
                or cls._looks_like_numeric_or_pair_line(
                    line
                )
            ):
                continue

            previous_parts = []

            for back in range(1, 4):
                previous_index = index - back

                if previous_index < 0:
                    break

                previous = lines[previous_index]

                if cls._looks_like_context_noise_line(
                    previous
                ):
                    break

                if (
                    cls._looks_like_coordinate_data(
                        cls._normalize(previous)
                    )
                    or cls._looks_like_numeric_or_pair_line(
                        previous
                    )
                ):
                    break

                if (
                    len(previous.strip()) > 80
                    or previous.count(",") >= 2
                ):
                    break

                previous_parts.append(previous)

            previous_parts.reverse()

            if previous_parts:
                return (
                    " ".join(previous_parts)
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
    def _extract_numbered_caption(cls, lines):
        """First Tablo/Çizelge caption, including after leading data rows."""

        for index, line in enumerate(lines):
            if cls._looks_like_context_noise_line(line):
                continue

            normalized = cls._normalize(line)

            if not cls.NUMBERED_TABLE_CAPTION_PATTERN.match(
                normalized
            ):
                continue

            heading_lines = [line]

            for next_line in lines[index + 1:index + 4]:
                if cls._looks_like_context_noise_line(
                    next_line
                ):
                    break

                next_normalized = cls._normalize(
                    next_line
                )

                if (
                    cls._looks_like_coordinate_data(
                        next_normalized
                    )
                    or cls._looks_like_numeric_or_pair_line(
                        next_line
                    )
                ):
                    break

                heading_lines.append(next_line)

                if "KOORDINAT" in next_normalized:
                    break

            return " ".join(heading_lines)

        return ""

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
                    cls.strip_parentheticals(
                        " ".join(window[start:])
                    )
                )
                if cls._looks_like_ruhsat_heading(candidate):
                    return "RUHSAT_ALANI"

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

        if cls._classify_auxiliary_primary(normalized) != "DIGER":
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
        lines = [
            line.strip()
            for line in table_text.splitlines()
            if line.strip()
        ]
        return bool(cls._extract_numbered_caption(lines))

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