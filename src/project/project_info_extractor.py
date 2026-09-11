import re
import unicodedata
from pathlib import Path


class ProjectInfoExtractor:

    UNKNOWN = "Bilinmiyor"
    EK_TIP_EK1 = "Ek-1"
    EK_TIP_EK2 = "Ek-2"
    EK_FOLDER_NAMES = (
        EK_TIP_EK1,
        EK_TIP_EK2,
    )

    def extract(
        self,
        text,
        source_path=None,
        project_type=None,
    ):
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

        info = {
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
            "ek_tip": self._extract_ek_tip(
                normalized_text
            ),
        }

        return self._fill_missing_context(
            info,
            source_path=source_path,
            project_type=project_type,
        )

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

    _UNSAFE_PATH_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

    _EK2_TITLE = re.compile(
        r"\b(?:PROJE\s+TANITIM\s+DOSYASI|PTD\s+DOSYASI)\b",
        flags=re.IGNORECASE,
    )
    _EK1_TITLE = re.compile(
        r"\b(?:"
        r"NIHAI\s+CED|"
        r"CED\s+RAPORU|"
        r"CED\s+BASVURU\s+DOSYASI|"
        r"CEVRESEL\s+ETKI\s+DEGERLENDIRMESI"
        r")\b",
        flags=re.IGNORECASE,
    )
    _EK_EXPLICIT_LINE = re.compile(
        r"^\s*EK[\s.\-]*([12]|II|I)\s*$",
        flags=re.IGNORECASE | re.MULTILINE,
    )

    def _extract_ek_tip(self, text):
        """
        ÇED Ek tipi / belge sınıfı: Ek-1 (ÇED Raporu) veya
        Ek-2 (Proje Tanıtım Dosyası / PTD). Kapak ve başlık
        penceresine bakılır; yönetmelik metnindeki EK-1/EK-2
        listeleri belge sınıfı sayılmaz.
        """

        if not text:
            return self.UNKNOWN

        search_text = self._fold_ascii_tr(text[:4000])
        ptd_match = self._EK2_TITLE.search(search_text)
        ced_match = self._EK1_TITLE.search(search_text)

        if ptd_match and ced_match:
            if ptd_match.start() <= ced_match.start():
                return self.EK_TIP_EK2
            return self.EK_TIP_EK1

        if ptd_match:
            return self.EK_TIP_EK2

        if ced_match:
            return self.EK_TIP_EK1

        explicit = self._EK_EXPLICIT_LINE.search(search_text)
        if explicit is not None:
            token = self._fold_ascii_tr(explicit.group(1))
            token = re.sub(r"[\s._\-]+", "", token)
            if token in {"1", "I"}:
                return self.EK_TIP_EK1
            if token in {"2", "II"}:
                return self.EK_TIP_EK2

        return self.UNKNOWN

    def _fill_missing_context(
        self,
        info,
        source_path=None,
        project_type=None,
    ):
        path_province, path_ek = self.context_from_source_path(
            source_path
        )
        hint_ek = self.normalize_ek_tip(project_type)

        if (
            not self._usable_name_token(info.get("province"))
            and path_province
        ):
            info["province"] = self._format_location(
                path_province
            )

        if not self._is_known_ek_tip(info.get("ek_tip")):
            if self._is_known_ek_tip(path_ek):
                info["ek_tip"] = path_ek
            elif self._is_known_ek_tip(hint_ek):
                info["ek_tip"] = hint_ek

        return info

    @classmethod
    def context_from_source_path(cls, source_path):
        """
        e-ÇED indirme düzeni: .../{İL}/{EK-1|EK-2}/dosya.pdf

        İl veya Ek tipi allowlist değildir; yalnız bu genel
        klasör kalıbını okur.
        """

        if not source_path:
            return "", ""

        try:
            parts = Path(source_path).parts
        except TypeError:
            return "", ""

        for index, part in enumerate(parts):
            ek_tip = cls.normalize_ek_tip(part)
            if not cls._is_known_ek_tip(ek_tip):
                continue
            province = parts[index - 1] if index > 0 else ""
            return str(province or ""), ek_tip

        return "", ""

    @classmethod
    def normalize_ek_tip(cls, value):
        if value is None:
            return cls.UNKNOWN

        raw = str(value).strip()
        if not raw:
            return cls.UNKNOWN

        folded = cls._fold_ascii_tr(raw)
        compact = re.sub(r"[\s._\-]+", "", folded)

        if compact in {"EK1", "EKI"}:
            return cls.EK_TIP_EK1
        if compact in {"EK2", "EKII"}:
            return cls.EK_TIP_EK2

        if compact in {
            "CEDRAPORU",
            "NIHAICED",
            "NIHAICEDRAPORU",
            "CEDBASVURUDOSYASI",
        }:
            return cls.EK_TIP_EK1

        if compact in {
            "PTD",
            "PTDDOSYASI",
            "PROJETANITIMDOSYASI",
        }:
            return cls.EK_TIP_EK2

        return cls.UNKNOWN

    @classmethod
    def _is_known_ek_tip(cls, value):
        return cls.normalize_ek_tip(value) in cls.EK_FOLDER_NAMES

    @classmethod
    def _fold_ascii_tr(cls, value):
        text = unicodedata.normalize(
            "NFKC",
            str(value or ""),
        ).upper()
        return (
            text.replace("İ", "I")
            .replace("I\u0307", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
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
                r"\bS[Iİ]C[Iİ]L\b"
                r"(?:[^\d\n]{0,40})"
                r"(\d{4,10})\b",
                False,
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

        # Kapak yılı (2024) sicil değildir; sıkı
        # "SİCİL NO: 2024" etiketi strong=True ile kalır.
        if not strong and 1990 <= number <= 2035:
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
        KML belge adı: `{sicil} - {firma}`.

        Destekci / ürün sözleşmesi sicil-önde ister. PR #2
        (33cc525) `build_project_export_name` içinde
        şirket-sonra-sicil sırasını kodladı; bu fonksiyon
        o regresyonu geri alır. Sicil yoksa Bilinmiyor önde
        kalır; şirket-only stem üretilmez.
        """

        return cls.build_export_filename(
            project_info,
            default=default,
        )

    @classmethod
    def build_export_filename(
        cls,
        project_info,
        default="Proje",
    ):
        """Dosya gövdesi: `{sicil} - {firma}` (klasörsüz)."""

        info = project_info or {}
        license_no = (
            cls._usable_name_token(info.get("license_no"))
            or cls.UNKNOWN
        )
        company = (
            cls._usable_name_token(info.get("company"))
            or cls.UNKNOWN
        )
        stem = f"{license_no} - {company}"
        return cls._sanitize_path_component(stem, default=default)

    @classmethod
    def build_export_relative_path(
        cls,
        project_info,
        default_stem="Proje",
    ):
        """
        KML yazım yolu (ürün sözleşmesi / regresyon geri alımı):

        `{İL}/Ek-1|Ek-2/{sicil} - {firma}.kml`

        Bu iç içe yol builder git geçmişinde baseline
        (6e2515c) sonrası yok: GUI düz `{root}/{firma}_{sicil}`
        yazıyordu; `src/core/kml_export.py` o günden beri
        boş stub. e-ÇED indirme ağacı
        `{İL}/EK-1|EK-2/` (`CEDBatchProcessor`) aynı klasör
        sözleşmesini koruyordu. Eksik il / Ek / sicil / firma
        Bilinmiyor olarak görünür.
        """

        info = project_info or {}
        province = cls._sanitize_path_component(
            cls._usable_name_token(info.get("province"))
            or cls.UNKNOWN,
            default=cls.UNKNOWN,
        )
        ek_source = info.get("ek_tip")
        if not cls._is_known_ek_tip(ek_source):
            ek_source = info.get("project_type")
        ek_folder = cls._ek_folder_name(ek_source)
        stem = cls.build_export_filename(
            info,
            default=default_stem,
        )
        return str(
            Path(province) / ek_folder / f"{stem}.kml"
        )

    @classmethod
    def _ek_folder_name(cls, value):
        ek_tip = cls.normalize_ek_tip(value)
        if cls._is_known_ek_tip(ek_tip):
            return ek_tip
        return cls.UNKNOWN

    @classmethod
    def _sanitize_path_component(cls, value, default=""):
        text = cls._normalize_turkish_unicode(
            str(value or "")
        )
        text = cls._UNSAFE_PATH_CHARS.sub("_", text)
        text = re.sub(r"\s+", " ", text).strip(" ._")
        if text in {"", ".", ".."}:
            return default
        if len(text) > 150:
            text = text[:150].rstrip(" ._")
        return text or default

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

        search_text = text[:20000] if text else ""
        province = self._extract_province_only(search_text)
        district = self._extract_district_only(search_text)
        return province, district

    def _extract_province_only(self, text):
        patterns = [
            (
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
                r"\s+İLİ\b"
            ),
            (
                r"\bİLİ?\s*[:.\-]\s*"
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
            ),
        ]
        value = self._find_first_match(text, patterns)
        if value == self.UNKNOWN:
            return self.UNKNOWN
        return self._format_location(value)

    def _extract_district_only(self, text):
        patterns = [
            (
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
                r"\s+İLÇESİ\b"
            ),
            (
                r"\bİLÇE(?:Sİ)?\s*[:.\-]\s*"
                r"([A-ZÇĞİÖŞÜ]"
                r"[A-ZÇĞİÖŞÜa-zçğıöşü]+)"
            ),
        ]
        value = self._find_first_match(text, patterns)
        if value == self.UNKNOWN:
            return self.UNKNOWN
        return self._format_location(value)

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