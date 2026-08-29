import re

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.ocr.ocr_engine import OCREngine


class PDFTextExtractionService:
    """UI'dan bağımsız ortak PDF metin çıkarma politikası."""

    FAST_SCAN_MAX_PAGES = 150
    MAX_STRONG_TARGETS = 12
    STRONG_TARGET_SCORE = 70
    TARGET_NEIGHBORHOOD = range(-1, 4)

    PAGE_PATTERN = re.compile(
        r"--- Sayfa (\d+) \[PDF METİN KATMANI\] ---"
    )

    AREA_KEYWORDS = (
        "RUHSAT ALANI",
        "RUHSAT SAHASI",
        "ÇED ALANI",
        "CED ALANI",
        "ÇED İZİN",
        "CED IZIN",
        "YENİ ÇED",
        "YENI CED",
        "PROJE ALANI",
        "PROJEYE KONU",
        "TALEP EDİLEN",
        "TALEP EDILEN",
    )

    STRUCTURE_KEYWORDS = (
        "KOORDİNAT",
        "KOORDINAT",
        "UTM",
        "DATUM",
        "SAĞA",
        "SAGA",
        "YUKARI",
        "ENLEM",
        "BOYLAM",
    )

    ROBUST_STRUCTURE_KEYWORDS = (
        "UTM",
        "WGS",
        "ED-50",
        "ED 50",
        "SAĞA",
        "SAGA",
        "D.O.M",
        "DOM",
        "ZON",
    )

    CONTENTS_KEYWORDS = {
        "İÇİNDEKİLER",
        "ICINDEKILER",
        "İÇİNDEKİLER TABLOSU",
        "ICINDEKILER TABLOSU",
        "TABLOLAR LİSTESİ",
        "TABLOLAR LISTESI",
        "ÇİZELGELER LİSTESİ",
        "CIZELGELER LISTESI",
        "ŞEKİLLER LİSTESİ",
        "SEKILLER LISTESI",
    }

    NEGATIVE_KEYWORDS = {
        "SONDAJ",
        "SONDAJ KOORDİNAT",
        "SONDAJ KOORDINAT",
        "MODELLEME",
        "MODELLEME ÇALIŞMASI",
        "MODELLEME CALISMASI",
        "BLOK MODEL",
        "REZERV HESABI",
        "REZERV HESAPLAMA",
        "TENÖR",
        "TENOR",
        "JEOLOJİK MODEL",
        "JEOLOJIK MODEL",
    }

    @classmethod
    def extract(cls, pdf_path):
        """PDF için ortak fast/selective/fallback metnini üretir."""

        try:
            fast_result = OCREngine.extract_text_layer(
                pdf_path,
                max_pages=cls.FAST_SCAN_MAX_PAGES,
            )

            if cls._has_required_polygons(
                fast_result.get("text", "")
            ):
                return cls._decorate_result(
                    fast_result,
                    method=(
                        "PDF Metin Katmanı "
                        "(OCR Gerekmedi)"
                    ),
                    strategy="fast_text_layer",
                    ocr_page_numbers=[],
                    ocr_attempted_page_numbers=[],
                    candidate_page_scores={},
                    full_document_ocr=False,
                )

            selected = cls._new_selected_result()
            fast_groups, fast_scores = cls._target_groups(
                fast_result.get("text", "")
            )
            cls._run_target_groups(
                pdf_path,
                fast_groups,
                fast_result.get("page_count", 0),
                selected,
            )

            if selected["has_required_polygons"]:
                return cls._build_selective_result(
                    fast_result,
                    selected,
                    strategy="selective_ocr_fast_window",
                    candidate_page_scores=fast_scores,
                )

            full_result = fast_result
            all_scores = dict(fast_scores)

            if (
                fast_result.get("scanned_pages", 0)
                < fast_result.get("page_count", 0)
            ):
                full_result = OCREngine.extract_text_layer(
                    pdf_path,
                    max_pages=None,
                )

                if cls._has_required_polygons(
                    full_result.get("text", "")
                ):
                    return cls._decorate_result(
                        full_result,
                        strategy="full_text_layer",
                        ocr_page_numbers=[],
                        ocr_attempted_page_numbers=[],
                        candidate_page_scores=fast_scores,
                        full_document_ocr=False,
                    )

                full_groups, full_scores = cls._target_groups(
                    full_result.get("text", "")
                )
                all_scores.update(full_scores)
                cls._run_target_groups(
                    pdf_path,
                    full_groups,
                    full_result.get("page_count", 0),
                    selected,
                )

                if selected["has_required_polygons"]:
                    return cls._build_selective_result(
                        full_result,
                        selected,
                        strategy="selective_ocr_full_discovery",
                        candidate_page_scores=all_scores,
                    )

            return cls._general_fallback(
                pdf_path,
                reason="targeted_extraction_insufficient",
                candidate_page_scores=all_scores,
            )

        except Exception as error:
            return cls._general_fallback(
                pdf_path,
                reason="selective_extraction_error",
                error=str(error),
            )

    @classmethod
    def _has_required_polygons(cls, text):
        if not text.strip():
            return False

        coordinates = CoordinateEngine.extract_coordinates(text)
        polygons = PolygonBuilder.build(coordinates)

        has_license = any(
            polygon.get("table_type") == "RUHSAT_ALANI"
            for polygon in polygons
        )
        has_ced_or_project = any(
            polygon.get("table_type")
            in {
                "CED_ALANI",
                "MEVCUT_CED_ALANI",
                "YENI_CED_ALANI",
                "PROJE_ALANI",
                "ISLETME_IZIN_ALANI",
            }
            for polygon in polygons
        )

        return has_license and has_ced_or_project

    @classmethod
    def _target_groups(cls, text):
        page_matches = list(cls.PAGE_PATTERN.finditer(text))
        target_pages = set()
        page_texts = {}

        for index, match in enumerate(page_matches):
            page_number = int(match.group(1))
            start = match.end()
            end = (
                page_matches[index + 1].start()
                if index + 1 < len(page_matches)
                else len(text)
            )
            page_text = text[start:end].upper()
            page_texts[page_number] = page_text

            has_area = any(
                keyword in page_text
                for keyword in cls.AREA_KEYWORDS
            )
            structure_score = sum(
                keyword in page_text
                for keyword in cls.STRUCTURE_KEYWORDS
            )
            strong_project_heading = any(
                keyword in page_text
                for keyword in (
                    "PROJEYE KONU",
                    "TALEP EDİLEN",
                    "TALEP EDILEN",
                )
            )
            has_target_reference = any(
                keyword in page_text
                for keyword in (
                    "RUHSAT",
                    "ÇED",
                    "CED",
                    "PROJE",
                )
            )
            robust_structure_score = sum(
                keyword in page_text
                for keyword in cls.ROBUST_STRUCTURE_KEYWORDS
            )

            if has_area and structure_score >= 4:
                target_pages.add(page_number)
            elif strong_project_heading and (
                "KOORDİNAT" in page_text
                or "KOORDINAT" in page_text
            ):
                target_pages.add(page_number)
            elif (
                has_target_reference
                and "TABLO" in page_text
                and robust_structure_score >= 2
            ):
                target_pages.add(page_number)

        scores = {
            page_number: cls._score_target_page(
                page_texts[page_number]
            )
            for page_number in target_pages
        }
        ranked_targets = sorted(
            target_pages,
            key=lambda page_number: (
                scores.get(page_number, 0),
                -page_number,
            ),
            reverse=True,
        )

        print(
            "OCR ADAY PUANLARI:",
            [
                (page_number, scores.get(page_number, 0))
                for page_number in ranked_targets[:20]
            ],
        )

        strong_targets = [
            page_number
            for page_number in ranked_targets
            if scores.get(page_number, 0)
            >= cls.STRONG_TARGET_SCORE
        ]
        selected_targets = (
            strong_targets[: cls.MAX_STRONG_TARGETS]
            if strong_targets
            else ranked_targets[: cls.MAX_STRONG_TARGETS]
        )

        groups = []
        for page_number in selected_targets:
            if not groups:
                groups.append([page_number])
            elif page_number - groups[-1][-1] <= 3:
                groups[-1].append(page_number)
            else:
                groups.append([page_number])

        return groups, scores

    @classmethod
    def _score_target_page(cls, page_text):
        score = 0
        has_coordinate_word = (
            "KOORDİNAT" in page_text
            or "KOORDINAT" in page_text
        )
        has_table_word = "TABLO " in page_text

        if has_coordinate_word:
            score += 60
        if has_table_word and has_coordinate_word:
            score += 40
        if any(
            keyword in page_text
            for keyword in cls.CONTENTS_KEYWORDS
        ):
            score -= 300

        has_license_word = (
            "RUHSAT ALANI" in page_text
            or "RUHSAT SAHASI" in page_text
        )
        if has_license_word:
            score += 40
        if has_license_word and has_coordinate_word:
            score += 60

        has_ced_word = any(
            keyword in page_text
            for keyword in (
                "ÇED ALANI",
                "CED ALANI",
                "ÇED İZİN",
                "CED IZIN",
                "YENİ ÇED",
                "YENI CED",
            )
        )
        has_project_word = any(
            keyword in page_text
            for keyword in (
                "PROJE ALANI",
                "PROJE ALANLARI",
                "PROJEYE KONU ALAN",
                "İŞLETME İZİN ALANI",
                "ISLETME IZIN ALANI",
            )
        )
        if has_ced_word:
            score += 40
        if has_project_word:
            score += 40
        if has_coordinate_word and (
            has_ced_word or has_project_word
        ):
            score += 60

        structure_score = sum(
            keyword in page_text
            for keyword in cls.STRUCTURE_KEYWORDS
        )
        score += structure_score * 10

        utm_number_count = len(
            re.findall(
                r"\b\d{6,7}(?:[.,]\d+)?\b",
                page_text,
            )
        )
        if has_coordinate_word and utm_number_count >= 4:
            score += 30
        elif has_coordinate_word and (
            has_license_word
            or has_ced_word
            or has_project_word
        ):
            score += 80

        negative_score = sum(
            keyword in page_text
            for keyword in cls.NEGATIVE_KEYWORDS
        )
        score -= negative_score * 40

        if (
            "EKTE VERİLMEKTEDİR" in page_text
            or "EKTE VERILMEKTEDIR" in page_text
        ):
            score -= 50

        return score

    @classmethod
    def _run_target_groups(
        cls,
        pdf_path,
        groups,
        page_count,
        selected,
    ):
        for group in groups:
            group_pages = sorted(
                {
                    target_page + offset
                    for target_page in group
                    for offset in cls.TARGET_NEIGHBORHOOD
                    if 1 <= target_page + offset <= page_count
                }
                - set(selected["attempted_pages"])
            )

            if not group_pages:
                continue

            print("OCR SAYFALARI:", group_pages)
            group_result = OCREngine.extract_selected_pages(
                pdf_path,
                group_pages,
            )
            selected["attempted_pages"].extend(group_pages)
            selected["failed_pages"] += group_result.get(
                "failed_pages",
                0,
            )

            group_text = group_result.get("text", "")
            if not group_text.strip():
                continue

            selected["parts"].append(group_text)
            selected["ocr_pages"].extend(
                cls._page_numbers(group_text, "OCR")
            )
            selected_text = "\n".join(selected["parts"])
            selected["has_required_polygons"] = (
                cls._has_required_polygons(selected_text)
            )

            if selected["has_required_polygons"]:
                break

    @staticmethod
    def _new_selected_result():
        return {
            "parts": [],
            "attempted_pages": [],
            "ocr_pages": [],
            "failed_pages": 0,
            "has_required_polygons": False,
        }

    @classmethod
    def _build_selective_result(
        cls,
        text_layer_result,
        selected,
        strategy,
        candidate_page_scores,
    ):
        selected_text = "\n".join(selected["parts"])
        final_text = (
            text_layer_result.get("text", "")
            + "\n"
            + selected_text
        )
        return {
            "success": bool(final_text.strip()),
            "method": "PDF Metin Katmanı + Seçili Sayfa OCR",
            "text": final_text,
            "page_count": text_layer_result.get("page_count", 0),
            "scanned_pages": text_layer_result.get(
                "scanned_pages",
                0,
            ),
            "text_layer_pages": text_layer_result.get(
                "text_layer_pages",
                0,
            ),
            "ocr_pages": len(set(selected["ocr_pages"])),
            "failed_pages": selected["failed_pages"],
            "ocr_page_numbers": sorted(set(selected["ocr_pages"])),
            "ocr_attempted_page_numbers": sorted(
                set(selected["attempted_pages"])
            ),
            "strategy": strategy,
            "candidate_page_scores": candidate_page_scores,
            "full_document_ocr": False,
            "error": "",
        }

    @classmethod
    def _general_fallback(
        cls,
        pdf_path,
        reason,
        candidate_page_scores=None,
        error="",
    ):
        try:
            result = OCREngine.extract_text(
                pdf_path,
                max_pages=None,
            )
        except Exception as fallback_error:
            return {
                "success": False,
                "method": "Metin çıkarılamadı",
                "text": "",
                "page_count": 0,
                "scanned_pages": 0,
                "text_layer_pages": 0,
                "ocr_pages": 0,
                "failed_pages": 0,
                "ocr_page_numbers": [],
                "ocr_attempted_page_numbers": [],
                "strategy": "general_ocr_fallback_failed",
                "candidate_page_scores": (
                    candidate_page_scores or {}
                ),
                "full_document_ocr": True,
                "fallback_reason": reason,
                "error": str(fallback_error),
            }

        result = dict(result)
        result.update(
            {
                "ocr_page_numbers": cls._page_numbers(
                    result.get("text", ""),
                    "OCR",
                ),
                "ocr_attempted_page_numbers": [],
                "strategy": "general_ocr_fallback",
                "candidate_page_scores": (
                    candidate_page_scores or {}
                ),
                "full_document_ocr": True,
                "fallback_reason": reason,
                "error": error,
            }
        )
        return result

    @classmethod
    def _decorate_result(cls, result, **metadata):
        decorated = dict(result)
        decorated.update(metadata)
        decorated.setdefault("error", "")
        return decorated

    @staticmethod
    def _page_numbers(text, source):
        return sorted(
            {
                int(page_number)
                for page_number in re.findall(
                    rf"^--- Sayfa (\d+) \[{re.escape(source)}\] ---$",
                    text,
                    re.MULTILINE,
                )
            }
        )
