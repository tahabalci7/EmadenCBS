import json
from pathlib import Path

from src.batch.heavy_refinement_queue import (
    build_compact_geometry_snapshot,
)
from src.core.pdf_text_extraction_service import (
    PDFTextExtractionService,
)
from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.table_detector import TableDetector
from src.coordinate.project_model import ProjectModel
from src.project.project_info_extractor import (
    ProjectInfoExtractor,
)


class CEDBatchProcessor:

    def __init__(
        self,
        province,
        downloads_root="downloads",
    ):
        self.province = province.upper()

        self.downloads_root = Path(
            downloads_root
        )

        self.province_dir = (
            self.downloads_root
            / self.province
        )

        self.project_info_extractor = (
            ProjectInfoExtractor()
        )

    def process_all(self):
        results = []

        for project_type in [
            "EK-1",
            "EK-2",
        ]:
            type_dir = (
                self.province_dir
                / project_type
            )

            if not type_dir.exists():
                print(
                    f"Klasör bulunamadı: "
                    f"{type_dir}"
                )
                continue

            pdf_files = sorted(
                type_dir.glob("*.pdf")
            )

            print()
            print("=" * 70)

            print(
                f"{self.province} | "
                f"{project_type}"
            )

            print(
                f"PDF sayısı: "
                f"{len(pdf_files)}"
            )

            print("=" * 70)

            for index, pdf_path in enumerate(
                pdf_files,
                start=1,
            ):
                print()
                print(
                    f"[{index}/{len(pdf_files)}] "
                    f"{pdf_path.name}"
                )

                result = self.process_pdf(
                    pdf_path=pdf_path,
                    project_type=project_type,
                )

                results.append(
                    result
                )

        self._print_summary(
            results
        )

        self._save_report(
            results
        )

        return results

    def process_pdf(
        self,
        pdf_path,
        project_type,
        defer_heavy_fallback_if_useful=False,
        include_geometry_snapshot=False,
    ):
        result = {
            "pdf": str(pdf_path),
            "file_name": pdf_path.name,
            "province": self.province,
            "project_type": project_type,
            "ocr_success": False,
            "ocr_method": "",
            "page_count": 0,
            "scanned_pages": 0,
            "text_layer_pages": 0,
            "ocr_pages": 0,
            "failed_pages": 0,
            "ocr_page_numbers": [],
            "extraction_strategy": "",
            "defer_heavy_fallback_if_useful": bool(
                defer_heavy_fallback_if_useful
            ),
            "result_completeness": "",
            "has_useful_result": False,
            "heavy_fallback_deferred": False,
            "general_fallback_used": False,
            "final_result_source": "",
            "pre_fallback_coordinate_count": None,
            "pre_fallback_polygon_count": None,
            "pre_fallback_table_count": None,
            "fallback_coordinate_count": None,
            "fallback_polygon_count": None,
            "fallback_table_count": None,
            "text_length": 0,
            "table_count": 0,
            "coordinate_count": 0,
            "polygon_count": 0,
            "status": "",
            "project_info": {},
            "error": "",
        }

        try:
            # -----------------------------
            # OCR / METİN ÇIKARMA
            # -----------------------------

            ocr_result = (
                PDFTextExtractionService.extract(
                    str(pdf_path),
                    defer_heavy_fallback_if_useful=(
                        defer_heavy_fallback_if_useful
                    ),
                )
            )

            result["ocr_success"] = (
                ocr_result.get(
                    "success",
                    False,
                )
            )

            result["ocr_method"] = (
                ocr_result.get(
                    "method",
                    "",
                )
            )

            result["page_count"] = (
                ocr_result.get(
                    "page_count",
                    0,
                )
            )

            result["scanned_pages"] = (
                ocr_result.get(
                    "scanned_pages",
                    0,
                )
            )

            result["text_layer_pages"] = (
                ocr_result.get(
                    "text_layer_pages",
                    0,
                )
            )

            result["ocr_pages"] = (
                ocr_result.get(
                    "ocr_pages",
                    0,
                )
            )

            result["failed_pages"] = (
                ocr_result.get(
                    "failed_pages",
                    0,
                )
            )

            result["ocr_page_numbers"] = list(
                ocr_result.get(
                    "ocr_page_numbers",
                    [],
                )
            )

            result["extraction_strategy"] = (
                ocr_result.get(
                    "strategy",
                    "",
                )
            )

            for diagnostic_field in (
                "result_completeness",
                "has_useful_result",
                "heavy_fallback_deferred",
                "general_fallback_used",
                "final_result_source",
                "pre_fallback_coordinate_count",
                "pre_fallback_polygon_count",
                "pre_fallback_table_count",
                "fallback_coordinate_count",
                "fallback_polygon_count",
                "fallback_table_count",
            ):
                if diagnostic_field in ocr_result:
                    result[diagnostic_field] = ocr_result[
                        diagnostic_field
                    ]

            extraction_error = ocr_result.get(
                "error",
                "",
            )

            if (
                not ocr_result.get("success", False)
                and extraction_error
            ):
                result["status"] = "HATA"
                result["error"] = extraction_error

                print(
                    f"  ✗ HATA: {extraction_error}"
                )

                return result

            raw_text = (
                ocr_result.get(
                    "text",
                    "",
                )
            )

            result["text_length"] = len(
                raw_text
            )

            if not raw_text.strip():
                result["status"] = (
                    "METIN_YOK"
                )

                print(
                    "  ✗ Metin çıkarılamadı."
                )

                return result

            # -----------------------------
            # TABLOLARI BUL
            # -----------------------------

            tables = (
                TableDetector.find_tables(
                    raw_text
                )
            )

            result["table_count"] = len(
                tables
            )

            # -----------------------------
            # KOORDİNATLARI BUL
            # -----------------------------

            coordinates = (
                CoordinateEngine
                .extract_coordinates(
                    raw_text,
                    pdf_path=str(pdf_path),
                )
            )

            result[
                "coordinate_count"
            ] = len(
                coordinates
            )

            # -----------------------------
            # POLYGON
            # -----------------------------

            polygons = (
                PolygonBuilder.build(
                    coordinates
                )
            )

            result[
                "polygon_count"
            ] = len(
                polygons
            )

            if include_geometry_snapshot:
                geometry_snapshot = (
                    build_compact_geometry_snapshot(
                        coordinates,
                        polygons,
                    )
                )
                result["geometry_snapshot"] = (
                    geometry_snapshot
                )
                result[
                    "transformed_coordinate_count"
                ] = geometry_snapshot[
                    "transformed_coordinate_count"
                ]

            # -----------------------------
            # PROJE BİLGİLERİ
            # -----------------------------

            project_info = (
                self.project_info_extractor
                .extract(
                    raw_text
                )
            )

            # e-ÇED klasör bilgisini de
            # modele ekliyoruz.
            project_info[
                "project_type"
            ] = project_type

            project_info[
                "source_pdf"
            ] = pdf_path.name

            result[
                "project_info"
            ] = project_info

            # -----------------------------
            # PROJECT MODEL
            # -----------------------------

            project_model = ProjectModel(
                pdf_path=str(
                    pdf_path
                ),
                coordinates=coordinates,
                polygons=polygons,
                tables=tables,
            )

            project_model.set_project_info(
                project_info
            )

            # -----------------------------
            # DURUM SINIFLANDIRMASI
            # -----------------------------

            if len(tables) == 0:
                result["status"] = (
                    "TABLO_BULUNAMADI"
                )

            elif len(coordinates) == 0:
                result["status"] = (
                    "TABLO_VAR_KOORDINAT_YOK"
                )

            elif len(polygons) == 0:
                result["status"] = (
                    "KOORDINAT_VAR_POLYGON_YOK"
                )

            else:
                result["status"] = (
                    "BASARILI"
                )

            print(
                f"  OCR       : "
                f"{result['ocr_method']}"
            )

            print(
                f"  Metin     : "
                f"{result['text_length']} karakter"
            )

            print(
                f"  Tablo     : "
                f"{result['table_count']}"
            )

            print(
                f"  Koordinat : "
                f"{result['coordinate_count']}"
            )

            print(
                f"  Polygon   : "
                f"{result['polygon_count']}"
            )

            print(
                f"  Durum     : "
                f"{result['status']}"
            )

            return result

        except Exception as exc:
            result["status"] = "HATA"

            result["error"] = str(
                exc
            )

            print(
                f"  ✗ HATA: {exc}"
            )

            return result

    def _print_summary(
        self,
        results,
    ):
        total = len(
            results
        )

        successful = sum(
            1
            for item in results
            if item["status"]
            == "BASARILI"
        )

        no_table = sum(
            1
            for item in results
            if item["status"]
            == "TABLO_BULUNAMADI"
        )

        no_coordinates = sum(
            1
            for item in results
            if item["status"]
            == "TABLO_VAR_KOORDINAT_YOK"
        )

        no_polygon = sum(
            1
            for item in results
            if item["status"]
            == "KOORDINAT_VAR_POLYGON_YOK"
        )

        errors = sum(
            1
            for item in results
            if item["status"]
            == "HATA"
        )

        print()
        print("=" * 70)
        print(
            f"{self.province} TOPLU ANALİZ ÖZETİ"
        )
        print("=" * 70)

        print(
            f"Toplam PDF                  : "
            f"{total}"
        )

        print(
            f"Başarılı                    : "
            f"{successful}"
        )

        print(
            f"Tablo bulunamadı            : "
            f"{no_table}"
        )

        print(
            f"Tablo var / koordinat yok   : "
            f"{no_coordinates}"
        )

        print(
            f"Koordinat var / polygon yok : "
            f"{no_polygon}"
        )

        print(
            f"Hata                        : "
            f"{errors}"
        )

        print()

        problem_files = [
            item
            for item in results
            if item["status"]
            != "BASARILI"
        ]

        if problem_files:
            print(
                "İNCELENECEK PDF DOSYALARI"
            )

            print(
                "-" * 70
            )

            for item in problem_files:
                print(
                    f"{item['project_type']} | "
                    f"{item['status']} | "
                    f"{item['file_name']}"
                )

    def _save_report(
        self,
        results,
    ):
        report_dir = Path(
            "reports"
        )

        report_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        report_file = (
            report_dir
            / (
                f"{self.province}_"
                f"coordinate_analysis.json"
            )
        )

        with report_file.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                results,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print()
        print(
            f"Analiz raporu kaydedildi:"
        )

        print(
            report_file.resolve()
        )


if __name__ == "__main__":
    processor = CEDBatchProcessor(
        province="ADANA",
    )

    processor.process_all()
