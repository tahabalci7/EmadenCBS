import re
import unicodedata


class ProjectInfoExtractor:

    def extract(self, text):
        normalized_text = self._normalize_text(text)

        province, district = self._extract_location(
            normalized_text
        )

        province = self._normalize_turkish_unicode(
            province
        )

        district = self._normalize_turkish_unicode(
            district
        )

        return {
            "company": self._extract_company(
                normalized_text
            ),
            "mine_type": self._extract_mine_type(
                normalized_text
            ),
            "license_no": self._extract_license_no(
                normalized_text
            ),
            "province": province,
            "district": district,
        }

    UNKNOWN = "Bilinmiyor"

    _COMPANY_LABEL_PREFIX = re.compile(
        r"^(?:"
        r"PROJE\s+SAH[Iİ]B[Iİ]N[Iİ]N\s+"
        r"(?:ADI|[UÜ]NVANI)|"
        r"PROJE\s+SAH[Iİ]B[Iİ]|"
        r"F[Iİ]RMA\s+[UÜ]NVANI"
        r")\s*[:.\-]?\s*",
        flags=re.IGNORECASE,
    )

    _JUNK_MINE_TYPE_PREFIX = re.compile(
        r"^(?:"
        r"(?:\d{3,10}\s+)?"
        r"(?:RUHSAT\s+|S[Iİ]C[Iİ]L\s+)?"
        r"NUMARALI\s+"
        r"|"
        r"(?:\d{3,10}\s+)?"
        r"(?:SAYILI|NOLU|NO['’]?LU|NO\.?\s*LU)\s+"
        r")+",
        flags=re.IGNORECASE,
    )
    @staticmethod
    def _normalize_turkish_unicode(value):
        if not value:
            return value

        value = unicodedata.normalize(
            "NFKC",
            value,
        )

        value = value.replace(
            "i\u0307",
            "i",
        )

        value = value.replace(
            "I\u0307",
            "İ",
        )

        return unicodedata.normalize(
            "NFC",
            value,
        )
    def _extract_company(self, text):
        patterns = [
            (
                r"PROJE\s+SAHİBİNİN\s+ADI"
                r"\s*[:.\-]?\s*([^\n]+)"
            ),
            (
                r"PROJE\s+SAH[Iİ]B[Iİ]N[Iİ]N\s+ADI"
                r"\s*[:.\-]?\s*([^\n]+)"
            ),
            (
                r"PROJE\s+SAHİBİNİN\s+ÜNVANI"
                r"\s*[:.\-]?\s*([^\n]+)"
            ),
            (
                r"PROJE\s+SAH[Iİ]B[Iİ]N[Iİ]N\s+[UÜ]NVANI"
                r"\s*[:.\-]?\s*([^\n]+)"
            ),
            (
                r"PROJE\s+SAHİBİ"
                r"\s*[:.\-]?\s*([^\n]+)"
            ),
            (
                r"FİRMA\s+ÜNVANI"
                r"\s*[:.\-]?\s*([^\n]+)"
            ),
            (
                r"F[Iİ]RMA\s+[UÜ]NVANI"
                r"\s*[:.\-]?\s*([^\n]+)"
            ),
        ]

        value = self._find_first_match(
            text,
            patterns,
        )

        if value != "Bilinmiyor":
            return self._clean_company_value(value)

        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        company_end_pattern = re.compile(
            r"\b("
            r"LTD\.?\s*ŞTİ\.?"
            r"|LTD\.?\s*STI\.?"
            r"|A\.?\s*Ş\.?"
            r"|A\.?\s*S\.?"
            r"|ANONİM\s+ŞİRKETİ"
            r"|LIMITED\s+ŞİRKETİ"
            r"|LİMİTED\s+ŞİRKETİ"
            r")\s*$",
            flags=re.IGNORECASE,
        )

        for index, line in enumerate(lines):
            if not company_end_pattern.search(line):
                continue

            candidate_lines = [line]

            # Şirket unvanları ÇED kapaklarında sıklıkla
            # iki veya üç satıra bölünür.
            for offset in (1, 2):
                previous_index = index - offset

                if previous_index < 0:
                    break

                previous_line = lines[previous_index]

                if self._looks_like_report_heading(
                    previous_line
                ):
                    break

                candidate_lines.insert(
                    0,
                    previous_line,
                )

            candidate = self._clean_value(
                " ".join(candidate_lines)
            )

            if self._looks_like_company(candidate):
                return self._clean_company_value(candidate)

        return "Bilinmiyor"

    def _extract_mine_type(self, text):
        """
        ÇED raporundan ana maden cinsini çıkarır.

        Öncelik:
        1. Raporun başlangıç bölümündeki açık maden cinsi alanları
        2. Başlıkta geçen "... OCAĞI" ifadeleri
        3. Birden fazla maden varsa temiz ve tekil olarak birleştirir

        Tüm raporu taramaz. Böylece raporun ilerleyen
        bölümlerindeki açıklamalar maden cinsi olarak alınmaz.
        """

        if not text:
            return "Bilinmiyor"

        # Proje adı ve temel bilgiler normalde raporun
        # başlangıcında bulunur. Bütün 500+ sayfayı taramak
        # yanlış pozitifleri ciddi şekilde artırıyor.
        search_text = text[:20000]

        # -------------------------------------------------
        # 1. AÇIK MADEN CİNSİ ALANLARI
        # -------------------------------------------------

        patterns = [
            r"MADEN\s+CİNSİ\s*[:\-]?\s*([^\n]+)",
            r"CEVHER\s+CİNSİ\s*[:\-]?\s*([^\n]+)",
            r"HAMMADDE\s+CİNSİ\s*[:\-]?\s*([^\n]+)",
        ]

        value = self._find_first_match(
            search_text,
            patterns,
        )

        if value != "Bilinmiyor":
            return self._clean_mine_type(value)

        # -------------------------------------------------
        # 2. PROJE ADINDAN MADEN CİNSİ
        # -------------------------------------------------

        candidates = []

        project_name_text = search_text

        project_name_match = re.search(
            r"PROJENİN\s+ADI(.*?)(?:PROJE\s+BEDELİ|PROJE\s+ICIN|PROJE\s+İÇİN)",
            search_text,
            flags=re.IGNORECASE | re.DOTALL,
        )

        if project_name_match:
            project_name_text = (
                project_name_match.group(1)
            )

        mine_matches = re.findall(
            r"([A-ZÇĞİÖŞÜa-zçğıöşü]"
            r"[A-ZÇĞİÖŞÜa-zçğıöşü\-]{2,30})"
            r"\s+"
            r"(?:"
            r"OCAĞI"
            r"|OCAĞINA"
            r"|OCAĞININ"
            r"|OCAKLARI"
            r"|OCAKLARINA"
            r"|OCAKLARININ"
            r")"
            r"\b",
            project_name_text,
            flags=re.IGNORECASE,
        )

        # Proje adında bulunamadıysa yalnızca
        # raporun başlangıç kısmında tekrar dene.
        if not mine_matches:
            mine_matches = re.findall(
                r"([A-ZÇĞİÖŞÜa-zçğıöşü]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü\-]{2,30})"
                r"\s+"
                r"(?:"
                r"OCAĞI"
                r"|OCAĞINA"
                r"|OCAĞININ"
                r"|OCAKLARI"
                r"|OCAKLARINA"
                r"|OCAKLARININ"
                r")"
                r"\b",
                search_text[:6000],
                flags=re.IGNORECASE,
            )

        for match in mine_matches:
            value = self._clean_value(match)

            # Satırın son tarafı bizim için daha değerlidir.
            words = value.split()

            if len(words) > 6:
                words = words[-6:]

            value = " ".join(words).strip()

            # Başlıkta maden adından önce sık görülen
            # anlamsız kelimeleri temizle.
            stop_prefixes = {
                "MADEN",
                "AÇIK",
                "YERALTI",
                "MEVCUT",
                "YENİ",
                "YENI",
                "PROJE",
                "IV.",
                "III.",
                "II.",
                "I.",
                "IV",
                "III",
                "II",
                "I",
                "GRUP",
            }

            words = value.split()

            while (
                words
                and words[0].upper() in stop_prefixes
            ):
                words.pop(0)

            value = " ".join(words).strip()

            if not value:
                continue

            # "KUVARSİT VE ÇİNKO" gibi birleşik ifadeleri
            # ayrı maden türlerine ayır.
            parts = re.split(
                r"\s+(?:VE|/|&)\s+|/",
                value,
                flags=re.IGNORECASE,
            )

            for part in parts:
                part = self._clean_mine_type(part)

                if not part:
                    continue

                if part == "Bilinmiyor":
                    continue

                # Türkçe karakter farklarını da dikkate alarak
                # aynı madenin tekrar eklenmesini engelle.
                normalized_part = (
                    part.upper()
                    .replace("Ç", "C")
                    .replace("Ğ", "G")
                    .replace("İ", "I")
                    .replace("Ö", "O")
                    .replace("Ş", "S")
                    .replace("Ü", "U")
                )

                existing_normalized = {
                    item.upper()
                    .replace("Ç", "C")
                    .replace("Ğ", "G")
                    .replace("İ", "I")
                    .replace("Ö", "O")
                    .replace("Ş", "S")
                    .replace("Ü", "U")
                    for item in candidates
                }

                if normalized_part not in existing_normalized:
                    candidates.append(part)

        # -------------------------------------------------
        # 3. ALTERNATİF MADEN TANIMLARI
        #
        # Bazı ÇED raporlarında proje başlığında
        # "... OCAĞI" ifadesi bulunmayabilir.
        #
        # Örnek yapılar:
        # KUVARSİT MADENİ
        # KROM MADENİ
        # MERMER MADENCİLİĞİ
        # IV. GRUP KUVARSİT
        # -------------------------------------------------

        if not candidates:
            fallback_patterns = [
                (
                    r"\b([A-ZÇĞİÖŞÜa-zçğıöşü]"
                    r"[A-ZÇĞİÖŞÜa-zçğıöşü\-]{2,30})"
                    r"\s+MADENİ\b"
                ),
                (
                    r"\b([A-ZÇĞİÖŞÜa-zçğıöşü]"
                    r"[A-ZÇĞİÖŞÜa-zçğıöşü\-]{2,30})"
                    r"\s+MADENCİLİĞİ\b"
                ),
                (
                    r"\b(?:I|II|III|IV|V)\.?\s*"
                    r"GRUP\s+"
                    r"([A-ZÇĞİÖŞÜa-zçğıöşü]"
                    r"[A-ZÇĞİÖŞÜa-zçğıöşü\-]{2,30})"
                ),
            ]

            for pattern in fallback_patterns:
                matches = re.findall(
                    pattern,
                    search_text,
                    flags=re.IGNORECASE,
                )

                for match in matches:
                    part = self._clean_mine_type(
                        match
                    )

                    if (
                        not part
                        or part == "Bilinmiyor"
                    ):
                        continue

                    normalized_part = (
                        part.upper()
                        .replace("Ç", "C")
                        .replace("Ğ", "G")
                        .replace("İ", "I")
                        .replace("Ö", "O")
                        .replace("Ş", "S")
                        .replace("Ü", "U")
                    )

                    existing_normalized = {
                        item.upper()
                        .replace("Ç", "C")
                        .replace("Ğ", "G")
                        .replace("İ", "I")
                        .replace("Ö", "O")
                        .replace("Ş", "S")
                        .replace("Ü", "U")
                        for item in candidates
                    }

                    if (
                        normalized_part
                        not in existing_normalized
                    ):
                        candidates.append(
                            part
                        )

        if not candidates:
            return "Bilinmiyor"

        return " / ".join(
            candidates
        )
    def _clean_mine_type(self, value):
        """
        Bulunan maden adındaki proje başlığı kaynaklı
        gereksiz ifadeleri temizler.
        """

        if not value:
            return "Bilinmiyor"

        value = self._clean_value(value)

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()
        # Ruhsat / sicil başlıklarından maden adına
        # taşınan ön ekleri temizle. "NUMARALI MANYEZİT"
        # gibi numara düşmüş kalıntılar da atılır.
        value = re.sub(
            r"^(?:"
            r"SİCİL\s*:?\s*\d+\s*|"
            r"SICIL\s*:?\s*\d+\s*|"
            r"S[Iİ]C[Iİ]L\s*:?\s*\d+\s*|"
            r"\d+\s+RUHSAT\s+NUMARALI\s+|"
            r"RUHSAT\s+NUMARALI\s+|"
            r"(?:\d+\s+)?NUMARALI\s+|"
            r"\d+\s+(?:SAYILI|NOLU|NO['’]?LU)\s+(?:RUHSAT\s+)?|"
            r"RUHSAT\s+NO(?:SU)?\s*:?\s*\d+\s*"
            r")+",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
        value = self._JUNK_MINE_TYPE_PREFIX.sub(
            "",
            value,
        ).strip()
        # Maden isminden sonra proje açıklaması başlamışsa kes.
        value = re.split(
            (
                r"\b(?:"
                r"KAPASİTE|KAPASITE|"
                r"ARTIŞI|ARTISI|"
                r"İLAVESİ|ILAVESI|"
                r"GENİŞLEME|GENISLEME|"
                r"PROJESİ|PROJESI|"
                r"FAALİYETİ|FAALIYETI"
                r")\b"
            ),
            value,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        value = value.strip(
            " \t\r\n:;,.-/|"
        )

        if not value:
            return "Bilinmiyor"

        # Maden adlarını standart biçimde döndür.
        return value.upper()
    def _extract_license_no(self, text):
        """
        Ruhsat veya sicil numarasını gerçek ruhsat
        bağlamından çıkarır.

        İR-1-1, R-1 vb. koordinat etiketleri ruhsat
        numarası olarak kabul edilmez.
        """

        # Türkçe İ/I ve satır kırıklı tablo düzenleri
        # (SİCİL NO / SICIL NO / 42077 sayılı ruhsat).
        labeled_patterns = [
            (
                r"\bS[Iİ]C[Iİ]L\s*"
                r"(?:NO(?:SU)?|NUMARASI)?"
                r"\s*[:.\-]?\s*(\d{4,10})\b",
                True,
            ),
            (
                r"\bRUHSAT\s+S[Iİ]C[Iİ]L\s*"
                r"(?:NO(?:SU)?|NUMARASI)?"
                r"\s*[:.\-]?\s*(\d{4,10})\b",
                True,
            ),
            (
                r"\b(\d{4,10})\s+"
                r"RUHSAT\s+NUMARALI\b",
                True,
            ),
            (
                r"\b(\d{4,10})\s+"
                r"(?:SAYILI|NOLU|NO['’]?LU|NO\.?\s*LU)\s+"
                r"RUHSAT\b",
                True,
            ),
            (
                r"\bRUHSAT\s*"
                r"(?:NO(?:SU)?|NUMARASI)"
                r"\s*[:.\-]?\s*(\d{4,10})\b",
                True,
            ),
            (
                r"\bRUHSAT\s*"
                r"[:.\-]\s*(\d{4,10})\b",
                True,
            ),
            (
                r"\b(\d{4,10})\s+NUMARALI\b",
                False,
            ),
            (
                r"\bER[Iİ][SŞ][Iİ]M\s*"
                r"(?:NO(?:SU)?|NUMARASI)?"
                r"\s*[:.\-]?\s*(\d{4,10})\b",
                False,
            ),
        ]

        for pattern, strong in labeled_patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match is None:
                continue

            candidate = self._clean_value(
                match.group(1)
            )

            if self._is_plausible_license_no(
                candidate,
                strong=strong,
            ):
                return candidate

        return "Bilinmiyor"

    @classmethod
    def _is_plausible_license_no(
        cls,
        value,
        strong=True,
    ):
        if not value or not str(value).isdigit():
            return False

        digits = str(value)
        length = len(digits)
        number = int(digits)

        if length < 4 or length > 10:
            return False

        # UTM kuzey değeri ruhsat değildir.
        if 3000000 <= number <= 4999999:
            return False

        # Etiketsiz "123456 NUMARALI" UTM doğu
        # değeri olabilir; yalnız 4-5 veya 8-10
        # haneli adayları kabul et.
        if not strong and 100000 <= number <= 899999:
            return False

        return True

    def _clean_company_value(self, value):
        value = self._clean_value(value)
        value = self._COMPANY_LABEL_PREFIX.sub(
            "",
            value,
        ).strip()
        value = value.strip(
            " \t\r\n:;-|"
        )

        if not value:
            return "Bilinmiyor"

        return value

    @classmethod
    def build_project_export_name(
        cls,
        project_info,
        default="eMadenCBS Projesi",
    ):
        """
        KML belge adı / dosya adı için şirket + sicil.

        Bilinmiyor ve "NUMARALI …" maden-cinsi
        kalıntıları ayırt edici parça olarak
        kullanılmaz.
        """

        info = project_info or {}

        company = cls._usable_name_token(
            info.get("company")
        )
        license_no = cls._usable_name_token(
            info.get("license_no")
        )

        parts = []

        if company:
            parts.append(company)

        if license_no:
            parts.append(license_no)

        if not parts:
            return default

        return " - ".join(parts)

    @classmethod
    def build_export_filename(
        cls,
        project_info,
        default="Proje",
    ):
        info = project_info or {}
        parts = []

        company = cls._usable_name_token(
            info.get("company")
        )
        license_no = cls._usable_name_token(
            info.get("license_no")
        )

        if company:
            parts.append(company)

        if license_no:
            parts.append(license_no)

        raw_name = "_".join(parts) if parts else default

        file_name = re.sub(
            r'[<>:"/\\|?*]',
            "_",
            raw_name,
        )
        file_name = re.sub(
            r"\s+",
            "_",
            file_name,
        ).strip("._ ")

        return file_name or default

    @classmethod
    def _usable_name_token(cls, value):
        if value is None:
            return ""

        text = str(value).strip()

        if not text or text == cls.UNKNOWN:
            return ""

        text = cls._COMPANY_LABEL_PREFIX.sub(
            "",
            text,
        ).strip()

        if not text or text == cls.UNKNOWN:
            return ""

        if cls._is_junk_distinguishing_token(text):
            return ""

        return text

    @classmethod
    def _is_junk_distinguishing_token(cls, value):
        if not value:
            return True

        folded = (
            str(value)
            .upper()
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )
        folded = re.sub(r"\s+", " ", folded).strip()

        if folded == cls.UNKNOWN.upper():
            return True

        if folded.startswith("NUMARALI"):
            return True

        if re.fullmatch(
            r"NUMARALI(?:\s+\S+){0,3}",
            folded,
        ):
            return True

        return False

    def _extract_location(self, text):
        patterns = [
            (
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
                r"\s+İLİ\s*,?\s*"
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
                r"\s+İLÇESİ"
            ),
            (
                r"İLİ\s*[:\-]?\s*"
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
                r".{0,100}?"
                r"İLÇESİ\s*[:\-]?\s*"
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
            ),
            (
                r"İL\s*[:\-]\s*"
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
                r".{0,100}?"
                r"İLÇE\s*[:\-]\s*"
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
            ),
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=(
                    re.IGNORECASE
                    | re.DOTALL
                ),
            )

            if match is None:
                continue

            province = self._format_location(
                match.group(1)
            )

            district = self._format_location(
                match.group(2)
            )

            return province, district

        return "Bilinmiyor", "Bilinmiyor"

    def _find_first_match(
        self,
        text,
        patterns,
    ):
        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=(
                    re.IGNORECASE
                    | re.MULTILINE
                ),
            )

            if match is None:
                continue

            value = self._clean_value(
                match.group(1)
            )

            if value:
                return value

        return "Bilinmiyor"

    def _normalize_text(self, text):
        if not text:
            return ""

        normalized_lines = []

        for line in str(text).splitlines():
            line = re.sub(
                r"[ \t]+",
                " ",
                line,
            ).strip()

            normalized_lines.append(line)

        return "\n".join(
            normalized_lines
        )

    def _clean_value(self, value):
        if not value:
            return ""

        value = re.sub(
            r"\s+",
            " ",
            value,
        ).strip()
        value = unicodedata.normalize(
            "NFC",
            value,
        )

        value = value.replace(
            "i\u0307",
            "i",
        )

        value = re.split(
            (
                r"\b(?:"
                r"ADRESİ|ADRES|TELEFON|TEL|"
                r"FAKS|FAX|E-POSTA|EMAIL"
                r")\b"
            ),
            value,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        return value.strip(
            " \t\r\n:;-|"
        )

    def _looks_like_company(self, value):
        upper = value.upper()

        company_markers = (
            "LTD",
            "ŞTİ",
            "STI",
            "A.Ş",
            "A.S",
            "ANONİM ŞİRKETİ",
            "LIMITED ŞİRKETİ",
            "LİMİTED ŞİRKETİ",
        )

        return any(
            marker in upper
            for marker in company_markers
        )

    def _looks_like_report_heading(self, value):
        upper = value.upper()

        heading_markers = (
            "ÇED RAPORU",
            "CED RAPORU",
            "NİHAİ ÇED",
            "NIHAI CED",
            "RUHSAT NUMARALI",
            "RUHSAT NO",
            "SİCİL",
            "SICIL",
        )

        return any(
            marker in upper
            for marker in heading_markers
        )

    def _format_location(self, value):
        value = self._clean_value(
            value
        )

        if value.isupper():
            return value.title()

        return value