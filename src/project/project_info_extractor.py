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
                r"\s*[:\-]?\s*\n+\s*([^\n]+)"
            ),
            (
                r"PROJE\s+SAHİBİNİN\s+ÜNVANI"
                r"\s*[:\-]?\s*\n+\s*([^\n]+)"
            ),
            (
                r"PROJE\s+SAHİBİ"
                r"\s*[:\-]?\s*\n+\s*([^\n]+)"
            ),
            (
                r"FİRMA\s+ÜNVANI"
                r"\s*[:\-]?\s*\n+\s*([^\n]+)"
            ),
        ]

        value = self._find_first_match(
            text,
            patterns,
        )

        if value != "Bilinmiyor":
            return value

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
                return candidate

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
        # taşınan ön ekleri temizle.
        value = re.sub(
            r"^(?:"
            r"SİCİL\s*:?\s*\d+\s*|"
            r"SICIL\s*:?\s*\d+\s*|"
            r"\d+\s+RUHSAT\s+NUMARALI\s+|"
            r"RUHSAT\s+NUMARALI\s+|"
            r"RUHSAT\s+NO(?:SU)?\s*:?\s*\d+\s*"
            r")+",
            "",
            value,
            flags=re.IGNORECASE,
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

        patterns = [
            # SİCİL 74362
            # SİCİL: 74362
            # SİCİL NO: 74362
            r"\bSİCİL\s*"
            r"(?:NO(?:SU)?|NUMARASI)?"
            r"\s*[:\-]?\s*(\d{3,})\b",

            # 74362 RUHSAT NUMARALI
            r"\b(\d{3,})\s+"
            r"RUHSAT\s+NUMARALI\b",

            # RUHSAT NO: 74362
            # RUHSAT NOSU: 74362
            # RUHSAT NUMARASI: 74362
            r"\bRUHSAT\s*"
            r"(?:NO(?:SU)?|NUMARASI)"
            r"\s*[:\-]?\s*(\d{3,})\b",

            # RUHSAT: 74362
            r"\bRUHSAT\s*"
            r"[:\-]\s*(\d{3,})\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                text,
                flags=re.IGNORECASE,
            )

            if match is None:
                continue

            return self._clean_value(
                match.group(1)
            )

        return "Bilinmiyor"

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