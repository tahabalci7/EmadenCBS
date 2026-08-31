import re

from src.coordinate.state_machine import parse_coordinate_blocks


class TableDetector:
    """
    Sprint 19 - TableDetector v4

    Görev:
    - Koordinat tablosu başlıklarını bulmak
    - Numaralı tabloları birbirinden kesin olarak ayırmak
    - OCR nedeniyle iki satıra bölünmüş tablo başlıklarını yakalamak
    - Sayfa birleşimlerinde devam eden koordinat bloklarını korumak
    - Koordinat yapısı taşımayan blokları elemek
    """

    TABLE_KEYWORDS = [
        "PROJEYE KONU ALAN VE KOORDİNATLARI",
        "PROJEYE KONU ALAN VE KOORDINATLARI",
        "PROJE ALANI VE KOORDİNATLARI",
        "PROJE ALANI VE KOORDINATLARI",
        "PROJE ALANI KOORDİNATLARI",
        "PROJE ALANI KOORDINATLARI",
        "KOORDİNAT LİSTESİ",
        "KOORDINAT LISTESI",
        "KOORDİNAT TABLOSU",
        "KOORDINAT TABLOSU",
    ]

    STRUCTURE_KEYWORDS = [
        "UTM",
        "SAĞA",
        "SAGA",
        "YUKARI",
        "DATUM",
        "COĞRAFİK",
        "COGRAFIK",
        "SIRA N",
        "PROJEKSİYON",
        "PRJEKSİYON",
        "PROJEKSIYON",
        "ZON",
        "DOM",
    ]

    TABLE_NUMBER_PATTERN = re.compile(
        r"^\s*TABLO\s+\d+(?:[.\s:]|$)",
        re.IGNORECASE,
    )

    COORDINATE_WORD_PATTERN = re.compile(
        r"KOORD[İI]NAT",
        re.IGNORECASE,
    )

    NUMBER_PATTERN = re.compile(
        r"-?\d+(?:[.,]\d+)?"
    )

    PAGE_MARKER_PATTERN = re.compile(
        r"^--- Sayfa (?P<page>\d+) "
        r"\[[^\]\r\n]+\] ---$"
    )

    @classmethod
    def find_tables(cls, text: str):
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        tables = []
        current = []
        in_table = False
        current_page_number = None
        has_page_markers = any(
            cls.PAGE_MARKER_PATTERN.fullmatch(
                line
            )
            for line in lines
        )

        index = 0

        while index < len(lines):
            line = lines[index]
            upper = line.upper()

            page_marker = (
                cls.PAGE_MARKER_PATTERN.fullmatch(
                    line
                )
            )

            if page_marker is not None:
                page_number = int(
                    page_marker.group("page")
                )
                page_lines = cls._page_body_lines(
                    lines,
                    index + 1,
                )

                continue_active_table = (
                    in_table
                    and current_page_number is not None
                    and page_number
                    == current_page_number + 1
                    and cls._page_is_table_continuation(
                        page_lines
                    )
                )

                if in_table and not continue_active_table:
                    cls._append_candidate(
                        tables,
                        current,
                    )
                    current = []
                    in_table = False

                if continue_active_table:
                    current.append(line)

                current_page_number = page_number
                index += 1
                continue

            # ---------------------------------------------
            # NUMARALI TABLO BAŞLIĞI
            #
            # OCR başlığı tek satırda veya birkaç satırda
            # okuyabilir.
            #
            # Örnek:
            #
            # Tablo 18. Sicil: 74362 Ruhsat Numaralı...
            # Galeri Ağzı Alanı Koordinatları
            #
            # Bu nedenle TABLO XX gördüğümüzde birkaç
            # sonraki satıra da bakıyoruz.
            # ---------------------------------------------

            if cls._looks_like_table_number(upper):
                heading_lines = cls._collect_heading_lines(
                    lines,
                    index,
                )

                heading_text = " ".join(
                    heading_lines
                )

                if cls._heading_is_coordinate_table(
                    heading_text
                ):
                    if current:
                        cls._append_candidate(
                            tables,
                            current,
                        )

                    current = list(
                        heading_lines
                    )

                    in_table = True
                    index += len(
                        heading_lines
                    )
                    continue
            # ---------------------------------------------
            # İKİ SATIRA BÖLÜNMÜŞ NUMARASIZ TABLO BAŞLIĞI
            #
            # Örnek:
            # MEVCUT 1 NOLU ÇED ... ÇED ALANI
            # KOORDİNATLARI
            #
            # İlk satır alanı tanımlar, ikinci satır
            # koordinat başlığını tamamlar.
            # ---------------------------------------------
            # ---------------------------------------------
            # NUMARASIZ KOORDİNAT TABLOSU
            # ---------------------------------------------

            if cls._looks_like_table_start(
                upper
            ):
                heading_lines = [
                    line
                ]

                if index > 0:
                    previous_line = lines[
                        index - 1
                    ]

                    previous_upper = (
                        previous_line.upper()
                    )

                    heading_prefix_keywords = (
                        "RUHSAT",
                        "ÇED",
                        "CED",
                        "PROJE",
                        "OCAK",
                        "TESİS",
                        "TESIS",
                        "ŞANTİYE",
                        "SANTIYE",
                        "PASA",
                        "STOK",
                        "DEPO",
                        "ATIK",
                        "GALERİ",
                        "GALERI",
                    )

                    if (
                        any(
                            keyword
                            in previous_upper
                            for keyword
                            in heading_prefix_keywords
                        )
                        and not re.search(
                            r"\d{5,}",
                            previous_upper,
                        )
                    ):
                        heading_lines.insert(
                            0,
                            previous_line,
                        )

                if current:
                    cls._append_candidate(
                        tables,
                        current,
                    )

                current = heading_lines

                in_table = True
                index += 1
                continue

            # ---------------------------------------------
            # TABLO İÇİNDE DEĞİLSE
            # ---------------------------------------------

            if not in_table:
                if (
                    not has_page_markers
                    and cls._looks_like_continuation_start(
                        lines,
                        index,
                    )
                ):
                    current = [line]
                    in_table = True
                    index += 1
                    continue

                index += 1
                continue

            # ---------------------------------------------
            # YENİ NUMARALI TABLO BAŞLADI
            #
            # Yeni tablo koordinat tablosu olmasa bile
            # mevcut koordinat tablosunun sınırıdır.
            # Böylece Tablo 18 içine Tablo 19 veya
            # sonraki tablo içerikleri sızmaz.
            # ---------------------------------------------

            if cls._looks_like_table_number(
                upper
            ):
                cls._append_candidate(
                    tables,
                    current,
                )

                current = []
                in_table = False

                # Aynı satırı dışarıda tekrar işle.
                continue

            if cls._looks_like_strong_section_start(
                lines,
                index,
            ):
                cls._append_candidate(
                    tables,
                    current,
                )

                current = []
                in_table = False
                index += 1
                continue

            # ---------------------------------------------
            # AÇIK TABLO SONU
            # ---------------------------------------------

            if cls._looks_like_strong_table_end(
                upper
            ):
                current.append(
                    line
                )

                cls._append_candidate(
                    tables,
                    current,
                )

                current = []
                in_table = False
                index += 1
                continue

            current.append(
                line
            )

            index += 1

        if current:
            cls._append_candidate(
                tables,
                current,
            )

        return tables

    @classmethod
    def _collect_heading_lines(
        cls,
        lines,
        start_index,
    ):
        """
        Numaralı tablo başlığının OCR tarafından
        birkaç satıra bölünmesi durumunda başlığı
        birlikte değerlendirir.

        En fazla 4 satır alınır.
        """

        heading_lines = []

        max_index = min(
            start_index + 4,
            len(lines),
        )

        for index in range(
            start_index,
            max_index,
        ):
            line = lines[index]

            # İlk satırdan sonra başka bir
            # TABLO XX başladıysa dur.
            if (
                index > start_index
                and cls._looks_like_table_number(
                    line.upper()
                )
            ):
                break

            heading_lines.append(
                line
            )

            if cls.COORDINATE_WORD_PATTERN.search(
                line.upper()
            ):
                break

        return heading_lines

    @classmethod
    def _looks_like_table_number(
        cls,
        upper_line: str,
    ) -> bool:
        return bool(
            cls.TABLE_NUMBER_PATTERN.search(
                upper_line.strip()
            )
        )

    @classmethod
    def _heading_is_coordinate_table(
        cls,
        heading_text: str,
    ) -> bool:
        upper = heading_text.upper()

        return bool(
            cls.COORDINATE_WORD_PATTERN.search(
                upper
            )
        )
    @classmethod
    def _looks_like_continuation_start(
        cls,
        lines,
        start_index,
    ) -> bool:
        """
        Önceki PDF sayfasında başlayan koordinat tablosunun
        başlıksız devam sayfasını genel yapısından tanır.

        Belirli bir ÇED, tablo veya nokta adına bağlı değildir.
        """

        window = lines[
            start_index:start_index + 25
        ]

        if not window:
            return False

        window_text = "\n".join(
            window
        )

        upper_text = window_text.upper()

        structure_score = sum(
            1
            for keyword in cls.STRUCTURE_KEYWORDS
            if keyword in upper_text
        )

        if structure_score < 4:
            return False

        utm_y_count = 0
        utm_x_count = 0

        for line in window:
            numbers = cls.NUMBER_PATTERN.findall(
                line
            )

            for number_text in numbers:
                try:
                    value = float(
                        number_text.replace(
                            ",",
                            ".",
                        )
                    )
                except ValueError:
                    continue

                if (
                    100000
                    <= value
                    <= 999999
                ):
                    utm_y_count += 1

                elif (
                    3000000
                    <= value
                    <= 5000000
                ):
                    utm_x_count += 1

        return (
            utm_y_count >= 2
            and utm_x_count >= 2
        )

    @classmethod
    def _page_body_lines(
        cls,
        lines,
        start_index,
    ):
        page_lines = []

        for line in lines[start_index:]:
            if cls.PAGE_MARKER_PATTERN.fullmatch(
                line
            ):
                break

            page_lines.append(line)

        return page_lines

    @classmethod
    def _page_is_table_continuation(
        cls,
        page_lines,
    ):
        if not page_lines:
            return False

        if cls._page_has_explicit_coordinate_table(
            page_lines
        ):
            return False

        section_index = None
        for index in range(len(page_lines)):
            if cls._looks_like_strong_section_start(
                page_lines,
                index,
            ):
                section_index = index
                break

        candidate_lines = (
            page_lines[:section_index]
            if section_index is not None
            else page_lines
        )

        candidate_text = (
            "KOORDINAT TABLOSU\n"
            + "\n".join(candidate_lines)
        )

        return len(
            parse_coordinate_blocks(
                candidate_text
            )
        ) >= 2

    @classmethod
    def _page_has_explicit_coordinate_table(
        cls,
        page_lines,
    ):
        for index, line in enumerate(page_lines):
            upper = line.upper()

            if cls._looks_like_table_start(upper):
                return True

            if cls._looks_like_table_number(upper):
                heading_lines = cls._collect_heading_lines(
                    page_lines,
                    index,
                )
                if cls._heading_is_coordinate_table(
                    " ".join(heading_lines)
                ):
                    return True

        return False

    @classmethod
    def _looks_like_strong_section_start(
        cls,
        lines,
        index,
    ):
        line = lines[index].strip()
        same_line = re.fullmatch(
            r"\d+(?:\.\d+)+\.?\s+(.+)",
            line,
        )

        if same_line is not None:
            return cls._looks_like_section_title(
                same_line.group(1)
            )

        if not re.fullmatch(
            r"\d+(?:\.\d+)+\.?",
            line,
        ):
            return False

        if index + 1 >= len(lines):
            return False

        return cls._looks_like_section_title(
            lines[index + 1]
        )

    @classmethod
    def _looks_like_section_title(
        cls,
        value,
    ):
        clean = value.strip()

        if len(clean) < 5:
            return False

        if not re.search(
            r"[A-ZÇĞİÖŞÜ]{3}",
            clean,
            re.IGNORECASE,
        ):
            return False

        if cls._looks_like_table_start(
            clean.upper()
        ):
            return False

        return True

    @classmethod
    def _looks_like_table_start(
        cls,
        upper_line: str,
    ) -> bool:
        ignored_headings = {
            "UTM KOORDİNATLARI",
            "UTM KOORDINATLARI",
            "COĞRAFİK KOORDİNATLARI",
            "COGRAFIK KOORDINATLARI",
            "COĞRAFİK KOORDİNATLAR",
            "COGRAFIK KOORDINATLAR",
            "KOORDİNATLARI",
            "KOORDINATLARI",
        }

        clean = upper_line.strip()

        if clean in ignored_headings:
            return False

        # Numaralı tablolar ayrı mekanizma
        # tarafından yönetiliyor.
        if cls._looks_like_table_number(
            clean
        ):
            return False

        if any(
            keyword in clean
            for keyword in cls.TABLE_KEYWORDS
        ):
            return True

        coordinate_heading = re.search(
            r"KOORD[İI]NATLARI\s*$",
            clean,
        )

        if coordinate_heading:
            return True

        return False

    @classmethod
    def _looks_like_strong_table_end(
        cls,
        upper_line: str,
    ) -> bool:
        """
        Koordinat tablosunun güvenilir bitiş
        satırlarını tespit eder.
        """

        clean = upper_line.strip()

        strong_end_patterns = [
            "TOPLAM ALAN",
            "TOPLAM ALANI",
        ]

        if any(
            pattern in clean
            for pattern in strong_end_patterns
        ):
            return True

        # -------------------------------------------------
        # ALAN: 21,75 ha
        # ALAN : 1.853,12 HA
        #
        # ÇED raporlarında koordinat tablosunun ardından
        # çok sık kullanılan kesin tablo sonudur.
        # -------------------------------------------------

        area_end = re.match(
            r"^ALAN\s*:\s*"
            r"[\d.,]+\s*"
            r"(?:HA|M2|M²)?\s*$",
            clean,
            re.IGNORECASE,
        )

        if area_end:
            return True

        return False
        """
        Yalnızca güçlü ve güvenilir tablo sonlarını
        burada kullanıyoruz.

        ŞEKİL, HARİTA, KAYNAK gibi kelimeler
        OCR metninde tablo içerisinde de görülebildiği
        için artık doğrudan tabloyu kapatmıyor.
        """

        clean = upper_line.strip()

        strong_end_patterns = [
            "TOPLAM ALAN",
            "TOPLAM ALANI",
        ]

        return any(
            pattern in clean
            for pattern in strong_end_patterns
        )

    @classmethod
    def _append_candidate(
        cls,
        tables,
        lines,
    ):
        if not lines:
            return

        table_text = "\n".join(
            lines
        )

        if cls._is_real_coordinate_table(
            table_text
        ):
            tables.append(
                table_text
            )

    @classmethod
    def _is_real_coordinate_table(
        cls,
        table_text: str,
    ) -> bool:
        lines = [
            line.strip()
            for line in table_text.splitlines()
            if line.strip()
        ]

        upper_text = table_text.upper()

        # ---------------------------------------------
        # TABLO YAPISI PUANI
        # ---------------------------------------------

        structure_score = sum(
            1
            for keyword in cls.STRUCTURE_KEYWORDS
            if keyword in upper_text
        )

        utm_y_count = 0
        utm_x_count = 0

        # ---------------------------------------------
        # UTM SAYILARINI SAY
        # ---------------------------------------------

        for line in lines:
            numbers = cls.NUMBER_PATTERN.findall(
                line
            )

            for number_text in numbers:
                try:
                    value = float(
                        number_text.replace(
                            ",",
                            ".",
                        )
                    )

                except ValueError:
                    continue

                if (
                    100000
                    <= value
                    <= 999999
                ):
                    utm_y_count += 1

                elif (
                    3000000
                    <= value
                    <= 5000000
                ):
                    utm_x_count += 1

        has_utm_pairs = (
            utm_y_count >= 2
            and utm_x_count >= 2
        )

        has_table_structure = (
            structure_score >= 2
        )

        return (
            has_utm_pairs
            and has_table_structure
        )
