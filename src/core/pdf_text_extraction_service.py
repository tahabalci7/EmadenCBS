import re

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.table_detector import TableDetector
from src.ocr.ocr_engine import OCREngine


class PDFTextExtractionService:
    """UI'dan bağımsız ortak PDF metin çıkarma politikası."""

    FAST_SCAN_MAX_PAGES = 150
    MAX_STRONG_TARGETS = 12
    STRONG_TARGET_SCORE = 70
    TARGET_NEIGHBORHOOD = range(-1, 4)
    SELECTIVE_OCR_CHUNK_SIZE = 8

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
    def extract(
        cls,
        pdf_path,
        defer_heavy_fallback_if_useful=False,
    ):
        """PDF için ortak fast/selective/fallback metnini üretir."""

        pre_fallback_result = None

        try:
            fast_result = OCREngine.extract_text_layer(
                pdf_path,
                max_pages=cls.FAST_SCAN_MAX_PAGES,
            )

            if cls._has_required_polygons(
                fast_result.get("text", "")
            ):
                return cls._finalize_without_fallback(
                    cls._decorate_result(
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
                base_text=fast_result.get("text", ""),
                defer_when_useful=(
                    defer_heavy_fallback_if_useful
                ),
                stage="FAST_WINDOW",
            )
            pre_fallback_result = cls._build_selective_result(
                fast_result,
                selected,
                strategy="selective_ocr_fast_window",
                candidate_page_scores=fast_scores,
                use_best=defer_heavy_fallback_if_useful,
            )

            if selected["execution_error"]:
                return cls._fallback_with_preservation(
                    pdf_path,
                    pre_fallback_result,
                    reason="selective_extraction_error",
                    candidate_page_scores=fast_scores,
                    error=selected["execution_error"],
                )

            if selected["has_required_polygons"]:
                return cls._finalize_without_fallback(
                    pre_fallback_result
                )

            if (
                defer_heavy_fallback_if_useful
                and selected["has_useful_result"]
            ):
                return cls._defer_heavy_fallback(
                    pre_fallback_result,
                    reason="fast_window_usable",
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
                    return cls._finalize_without_fallback(
                        cls._decorate_result(
                            full_result,
                            strategy="full_text_layer",
                            ocr_page_numbers=[],
                            ocr_attempted_page_numbers=[],
                            candidate_page_scores=fast_scores,
                            full_document_ocr=False,
                        )
                    )

                if defer_heavy_fallback_if_useful:
                    pre_fallback_result = (
                        cls._build_selective_result(
                            full_result,
                            selected,
                            strategy=(
                                "selective_ocr_full_discovery"
                            ),
                            candidate_page_scores=all_scores,
                        )
                    )
                    full_quality = cls._record_selective_quality(
                        selected,
                        pre_fallback_result.get("text", ""),
                    )
                    selected["has_required_polygons"] = full_quality[
                        "has_required_polygons"
                    ]
                    selected["has_useful_result"] = full_quality[
                        "has_useful_result"
                    ]

                    if selected["has_required_polygons"]:
                        return cls._finalize_without_fallback(
                            pre_fallback_result
                        )

                    if selected["has_useful_result"]:
                        cls._mark_selective_early_exit(
                            selected,
                            stage="FULL_TEXT_DISCOVERY",
                            reason="usable_polygon_found",
                        )
                        pre_fallback_result = (
                            cls._build_selective_result(
                                full_result,
                                selected,
                                strategy=(
                                    "selective_ocr_full_discovery"
                                ),
                                candidate_page_scores=all_scores,
                                use_best=True,
                            )
                        )
                        return cls._defer_heavy_fallback(
                            pre_fallback_result,
                            reason="full_text_discovery_usable",
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
                    base_text=full_result.get("text", ""),
                    defer_when_useful=(
                        defer_heavy_fallback_if_useful
                    ),
                    stage="FULL_DISCOVERY_OCR",
                )
                pre_fallback_result = cls._build_selective_result(
                    full_result,
                    selected,
                    strategy="selective_ocr_full_discovery",
                    candidate_page_scores=all_scores,
                    use_best=defer_heavy_fallback_if_useful,
                )

                if selected["execution_error"]:
                    return cls._fallback_with_preservation(
                        pdf_path,
                        pre_fallback_result,
                        reason="selective_extraction_error",
                        candidate_page_scores=all_scores,
                        error=selected["execution_error"],
                    )

                if selected["has_required_polygons"]:
                    return cls._finalize_without_fallback(
                        pre_fallback_result
                    )

                if (
                    defer_heavy_fallback_if_useful
                    and selected["has_useful_result"]
                ):
                    return cls._defer_heavy_fallback(
                        pre_fallback_result,
                        reason="full_discovery_ocr_usable",
                    )

            if defer_heavy_fallback_if_useful:
                deferred_result = cls._defer_heavy_fallback(
                    pre_fallback_result,
                    reason="targeted_extraction_insufficient",
                )
                if deferred_result is not None:
                    return deferred_result

            return cls._fallback_with_preservation(
                pdf_path,
                pre_fallback_result,
                reason="targeted_extraction_insufficient",
                candidate_page_scores=all_scores,
            )

        except Exception as error:
            if defer_heavy_fallback_if_useful:
                deferred_result = cls._defer_heavy_fallback(
                    pre_fallback_result,
                    reason="selective_extraction_error",
                )
                if deferred_result is not None:
                    return deferred_result

            return cls._fallback_with_preservation(
                pdf_path,
                pre_fallback_result,
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
        base_text="",
        defer_when_useful=False,
        stage="",
    ):
        selected_text = "\n".join(selected["parts"])
        candidate_text = base_text + "\n" + selected_text
        if defer_when_useful:
            quality = cls._record_selective_quality(
                selected,
                candidate_text,
            )
            selected["has_required_polygons"] = quality[
                "has_required_polygons"
            ]
            selected["has_useful_result"] = quality[
                "has_useful_result"
            ]
        else:
            selected["has_required_polygons"] = (
                cls._has_required_polygons(candidate_text)
            )
        if selected["has_required_polygons"]:
            return

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

            page_chunks = [group_pages]
            if defer_when_useful:
                page_chunks = [
                    group_pages[
                        start : start + cls.SELECTIVE_OCR_CHUNK_SIZE
                    ]
                    for start in range(
                        0,
                        len(group_pages),
                        cls.SELECTIVE_OCR_CHUNK_SIZE,
                    )
                ]

            for chunk_pages in page_chunks:
                print("OCR SAYFALARI:", chunk_pages)
                try:
                    group_result = OCREngine.extract_selected_pages(
                        pdf_path,
                        chunk_pages,
                    )
                except Exception as error:
                    if not defer_when_useful:
                        raise
                    selected["execution_error"] = str(error)
                    return

                selected["attempted_pages"].extend(chunk_pages)
                selected["failed_pages"] += group_result.get(
                    "failed_pages",
                    0,
                )
                if defer_when_useful:
                    selected["selective_ocr_chunks_processed"] += 1
                    selected[
                        "selective_ocr_processed_pages"
                    ].extend(chunk_pages)

                group_text = group_result.get("text", "")
                if group_text.strip():
                    selected["parts"].append(group_text)
                    selected["ocr_pages"].extend(
                        cls._page_numbers(group_text, "OCR")
                    )

                selected_text = "\n".join(selected["parts"])
                candidate_text = base_text + "\n" + selected_text
                if defer_when_useful:
                    quality = cls._record_selective_quality(
                        selected,
                        candidate_text,
                    )
                    selected["has_required_polygons"] = quality[
                        "has_required_polygons"
                    ]
                    selected["has_useful_result"] = quality[
                        "has_useful_result"
                    ]
                    if selected["has_required_polygons"]:
                        cls._mark_selective_early_exit(
                            selected,
                            stage=stage,
                            reason="complete_criterion_met",
                        )
                        return
                    if selected["has_useful_result"]:
                        cls._mark_selective_early_exit(
                            selected,
                            stage=stage,
                            reason="usable_polygon_found",
                        )
                        return
                else:
                    selected["has_required_polygons"] = (
                        cls._has_required_polygons(candidate_text)
                    )
                    if selected["has_required_polygons"]:
                        return

    @staticmethod
    def _new_selected_result():
        return {
            "parts": [],
            "attempted_pages": [],
            "ocr_pages": [],
            "failed_pages": 0,
            "has_required_polygons": False,
            "has_useful_result": False,
            "best_text": "",
            "best_quality": None,
            "best_ocr_pages": [],
            "best_attempted_pages": [],
            "best_failed_pages": 0,
            "execution_error": "",
            "selective_ocr_early_exit": False,
            "selective_ocr_early_exit_stage": "",
            "selective_ocr_early_exit_reason": "",
            "selective_ocr_chunks_processed": 0,
            "selective_ocr_processed_pages": [],
        }

    @classmethod
    def _record_selective_quality(cls, selected, text):
        quality = cls._measure_text_quality(text)
        best_quality = selected.get("best_quality")
        should_replace = best_quality is None
        if best_quality is not None:
            if (
                quality["has_required_polygons"]
                and not best_quality["has_required_polygons"]
            ):
                should_replace = True
            elif (
                quality["has_required_polygons"]
                == best_quality["has_required_polygons"]
                and cls._quality_rank(quality)
                >= cls._quality_rank(best_quality)
            ):
                should_replace = True

        if should_replace:
            selected["best_text"] = text
            selected["best_quality"] = quality
            selected["best_ocr_pages"] = list(
                selected["ocr_pages"]
            )
            selected["best_attempted_pages"] = list(
                selected["attempted_pages"]
            )
            selected["best_failed_pages"] = selected[
                "failed_pages"
            ]
        return quality

    @staticmethod
    def _mark_selective_early_exit(selected, stage, reason):
        selected["selective_ocr_early_exit"] = True
        selected["selective_ocr_early_exit_stage"] = stage
        selected["selective_ocr_early_exit_reason"] = reason

    @classmethod
    def _build_selective_result(
        cls,
        text_layer_result,
        selected,
        strategy,
        candidate_page_scores,
        use_best=False,
    ):
        selected_text = "\n".join(selected["parts"])
        final_text = (
            text_layer_result.get("text", "")
            + "\n"
            + selected_text
        )
        ocr_pages = selected["ocr_pages"]
        attempted_pages = selected["attempted_pages"]
        failed_pages = selected["failed_pages"]
        if use_best and selected.get("best_text"):
            final_text = selected["best_text"]
            ocr_pages = selected["best_ocr_pages"]
            attempted_pages = selected["best_attempted_pages"]
            failed_pages = selected["best_failed_pages"]
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
            "ocr_pages": len(set(ocr_pages)),
            "failed_pages": failed_pages,
            "ocr_page_numbers": sorted(set(ocr_pages)),
            "ocr_attempted_page_numbers": sorted(
                set(attempted_pages)
            ),
            "strategy": strategy,
            "candidate_page_scores": candidate_page_scores,
            "full_document_ocr": False,
            "error": "",
            "selective_ocr_early_exit": selected[
                "selective_ocr_early_exit"
            ],
            "selective_ocr_early_exit_stage": selected[
                "selective_ocr_early_exit_stage"
            ],
            "selective_ocr_early_exit_reason": selected[
                "selective_ocr_early_exit_reason"
            ],
            "selective_ocr_chunks_processed": selected[
                "selective_ocr_chunks_processed"
            ],
            "selective_ocr_pages_processed": len(
                set(selected["selective_ocr_processed_pages"])
            ),
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
    def _fallback_with_preservation(
        cls,
        pdf_path,
        pre_fallback_result,
        reason,
        candidate_page_scores=None,
        error="",
    ):
        fallback_result = cls._general_fallback(
            pdf_path,
            reason=reason,
            candidate_page_scores=candidate_page_scores,
            error=error,
        )
        return cls._preserve_fallback_result(
            pre_fallback_result,
            fallback_result,
            reason,
        )

    @classmethod
    def _preserve_fallback_result(
        cls,
        pre_fallback_result,
        fallback_result,
        reason,
    ):
        pre_quality = cls._measure_text_quality(
            (pre_fallback_result or {}).get("text", "")
        )
        fallback_quality = cls._measure_text_quality(
            fallback_result.get("text", "")
        )

        has_pre_fallback_text = bool(
            (pre_fallback_result or {}).get("text", "").strip()
        )
        if (
            has_pre_fallback_text
            and cls._quality_rank(pre_quality)
            >= cls._quality_rank(fallback_quality)
        ):
            final_result = dict(pre_fallback_result)
            final_result_source = "pre_fallback"
        else:
            final_result = dict(fallback_result)
            final_result_source = "general_fallback"

        final_quality = (
            pre_quality
            if final_result_source == "pre_fallback"
            else fallback_quality
        )
        final_result.update(
            {
                "pre_fallback_coordinate_count": pre_quality[
                    "coordinate_count"
                ],
                "pre_fallback_polygon_count": pre_quality[
                    "polygon_count"
                ],
                "pre_fallback_table_count": pre_quality[
                    "table_count"
                ],
                "pre_fallback_has_required_polygons": pre_quality[
                    "has_required_polygons"
                ],
                "general_fallback_used": True,
                "general_fallback_reason": reason,
                "fallback_coordinate_count": fallback_quality[
                    "coordinate_count"
                ],
                "fallback_polygon_count": fallback_quality[
                    "polygon_count"
                ],
                "fallback_table_count": fallback_quality[
                    "table_count"
                ],
                "final_result_source": final_result_source,
                "has_useful_result": final_quality[
                    "has_useful_result"
                ],
                "heavy_fallback_deferred": False,
                "heavy_fallback_defer_reason": "",
                "result_completeness": cls._result_completeness(
                    final_quality
                ),
                "general_fallback_error": fallback_result.get(
                    "error",
                    "",
                ),
            }
        )
        return final_result

    @classmethod
    def _defer_heavy_fallback(
        cls,
        pre_fallback_result,
        reason,
    ):
        if pre_fallback_result is None:
            return None

        quality = cls._measure_text_quality(
            pre_fallback_result.get("text", "")
        )
        if not quality["has_useful_result"]:
            return None

        final_result = dict(pre_fallback_result)
        final_result.update(
            {
                "pre_fallback_coordinate_count": quality[
                    "coordinate_count"
                ],
                "pre_fallback_polygon_count": quality[
                    "polygon_count"
                ],
                "pre_fallback_table_count": quality[
                    "table_count"
                ],
                "pre_fallback_has_required_polygons": quality[
                    "has_required_polygons"
                ],
                "general_fallback_used": False,
                "general_fallback_reason": reason,
                "fallback_coordinate_count": None,
                "fallback_polygon_count": None,
                "fallback_table_count": None,
                "final_result_source": "pre_fallback",
                "has_useful_result": True,
                "heavy_fallback_deferred": True,
                "heavy_fallback_defer_reason": (
                    "useful_pre_fallback_result"
                ),
                "result_completeness": "USEFUL_PARTIAL",
                "general_fallback_error": "",
            }
        )
        return final_result

    @classmethod
    def _finalize_without_fallback(cls, result):
        final_result = dict(result)
        quality = cls._measure_text_quality(
            final_result.get("text", "")
        )
        final_result.update(
            {
                "general_fallback_used": False,
                "general_fallback_reason": "",
                "final_result_source": final_result.get(
                    "strategy",
                    "extraction",
                ),
                "has_useful_result": quality[
                    "has_useful_result"
                ],
                "heavy_fallback_deferred": False,
                "heavy_fallback_defer_reason": "",
                "result_completeness": cls._result_completeness(
                    quality
                ),
            }
        )
        return final_result

    @classmethod
    def _measure_text_quality(cls, text):
        if not text.strip():
            return cls._empty_quality()

        try:
            tables = TableDetector.find_tables(text)
            coordinates = CoordinateEngine.extract_coordinates(text)
            polygons = PolygonBuilder.build(coordinates)
        except Exception:
            return cls._empty_quality()

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
        return {
            "coordinate_count": len(coordinates),
            "polygon_count": len(polygons),
            "table_count": len(tables),
            "has_required_polygons": (
                has_license and has_ced_or_project
            ),
            "has_useful_result": bool(polygons),
        }

    @staticmethod
    def _empty_quality():
        return {
            "coordinate_count": 0,
            "polygon_count": 0,
            "table_count": 0,
            "has_required_polygons": False,
            "has_useful_result": False,
        }

    @staticmethod
    def _quality_rank(quality):
        return (
            quality["polygon_count"],
            quality["coordinate_count"],
            quality["table_count"],
        )

    @staticmethod
    def _result_completeness(quality):
        if quality["has_required_polygons"]:
            return "COMPLETE"
        if quality["has_useful_result"]:
            return "USEFUL_PARTIAL"
        return "INSUFFICIENT"

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
