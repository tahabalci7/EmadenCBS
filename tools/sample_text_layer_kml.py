"""OCR-free sample: corpus PDFs -> KML via text layer + current parser."""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.batch.corpus_preflight import discover_preflight_pdfs
from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.pipeline_contract import (
    collect_pipeline_diagnostics,
    compact_diagnostics,
    reason_codes,
)
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.project_model import ProjectModel
from src.coordinate.ring_geometry import count_lonlat_crossings
from src.coordinate.table_detector import TableDetector
from src.coordinate.table_index import TableIndexLocator
from src.export.kml_exporter import KMLExporter
from src.ocr.ocr_engine import OCREngine
from src.project.project_info_extractor import ProjectInfoExtractor


def _count_crossed_kml_rings(polygons):
    crossed = 0
    for polygon in polygons:
        for text in KMLExporter._build_coordinate_texts(polygon):
            pairs = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                parts = line.split(",")
                pairs.append((float(parts[0]), float(parts[1])))
            if (
                len(pairs) >= 2
                and pairs[0][0] == pairs[-1][0]
                and pairs[0][1] == pairs[-1][1]
            ):
                pairs = pairs[:-1]
            if count_lonlat_crossings(pairs):
                crossed += 1
    return crossed


def safe_name(value):
    text = re.sub(r'[<>:"/\\|?*]', "_", str(value or "proje"))
    text = re.sub(r"\s+", "_", text).strip("._")
    return text[:120] or "proje"


def load_excluded_paths(summary_path):
    if summary_path is None:
        return set()
    data = json.loads(
        Path(summary_path).read_text(encoding="utf-8")
    )
    return {
        item.get("relative_path")
        for item in data.get("pdfs", [])
        if item.get("relative_path")
    }


def extract_ocr_free(pdf_path, max_pages):
    plan = TableIndexLocator.plan(pdf_path)
    page_count = int(plan.get("page_count") or 0)
    target_pages = list(plan.get("target_pages") or [])
    if page_count < 1:
        extraction = OCREngine.extract_text_layer(
            pdf_path,
            max_pages=max_pages,
        )
        extraction["index_found"] = False
        extraction["index_target_pages"] = []
        return extraction

    pages = set(range(1, min(max_pages, page_count) + 1))
    pages.update(target_pages)
    extraction = OCREngine.extract_text_layer_pages(
        pdf_path,
        sorted(pages),
    )
    extraction["index_found"] = bool(plan.get("index_found"))
    extraction["index_target_pages"] = target_pages
    return extraction


def process_pdf(record, max_pages):
    started = time.perf_counter()
    extraction = extract_ocr_free(
        record["path"],
        max_pages,
    )
    text = extraction.get("text", "") or ""
    tables = TableDetector.find_tables(text)
    coordinates = CoordinateEngine.extract_coordinates(
        text,
        pdf_path=record["path"],
    )
    polygons = PolygonBuilder.build(coordinates)
    pipeline_diagnostics = collect_pipeline_diagnostics(
        tables,
        coordinates,
        polygons,
    )
    project = ProjectModel(
        pdf_path=str(record["path"]),
        coordinates=coordinates,
        polygons=polygons,
        tables=tables,
        diagnostics=pipeline_diagnostics,
    )
    project.set_project_info(ProjectInfoExtractor().extract(text))
    type_counts = Counter(
        polygon.get("table_type", "DIGER")
        for polygon in polygons
    )
    return {
        "relative_path": record["relative_path"],
        "province": record["province"],
        "project_type": record["project_type"],
        "page_count": extraction.get("page_count"),
        "scanned_pages": extraction.get("scanned_pages"),
        "ocr_pages": 0,
        "method": extraction.get("method"),
        "index_found": bool(extraction.get("index_found")),
        "index_target_pages": extraction.get("index_target_pages") or [],
        "table_count": len(tables),
        "coordinate_count": len(coordinates),
        "polygon_count": len(polygons),
        "polygon_types": dict(type_counts),
        "pipeline_reason_codes": reason_codes(pipeline_diagnostics),
        "pipeline_diagnostics": compact_diagnostics(pipeline_diagnostics),
        "kml_crossed_rings": _count_crossed_kml_rings(polygons),
        "company": project.project_info.get("company"),
        "license_no": project.project_info.get("license_no"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "project": project,
    }


def configure_console_encoding():
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if not callable(reconfigure):
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def main():
    configure_console_encoding()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(r"E:\eMadenCBS_Downloads"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "tools" / "output" / "sample10_kml",
    )
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260831)
    parser.add_argument("--max-pages", type=int, default=150)
    parser.add_argument(
        "--exclude-summary",
        type=Path,
        default=None,
        help="Onceki sample10_summary.json; bu PDF'ler secilmez.",
    )
    args = parser.parse_args()

    records = discover_preflight_pdfs(args.root, args.output)
    excluded = load_excluded_paths(args.exclude_summary)
    if excluded:
        records = [
            record
            for record in records
            if record["relative_path"] not in excluded
        ]
    if len(records) < args.count:
        raise SystemExit(
            f"Corpus'ta {len(records)} uygun PDF var, {args.count} istendi."
        )

    selected = random.Random(args.seed).sample(records, args.count)
    args.output.mkdir(parents=True, exist_ok=True)
    kml_dir = args.output / "kml"
    kml_dir.mkdir(exist_ok=True)

    summaries = []
    for index, record in enumerate(selected, start=1):
        relative = record["relative_path"]
        print(f"[{index}/{args.count}] {relative}")
        try:
            result = process_pdf(record, args.max_pages)
        except Exception as error:
            print(f"  HATA: {error}")
            summaries.append(
                {
                    "relative_path": relative,
                    "province": record.get("province"),
                    "project_type": record.get("project_type"),
                    "ocr_pages": 0,
                    "table_count": 0,
                    "coordinate_count": 0,
                    "polygon_count": 0,
                    "polygon_types": {},
                    "kml_path": "",
                    "kml_skipped": "hata",
                    "error": str(error),
                }
            )
            continue
        project = result.pop("project")
        file_name = safe_name(
            "_".join(
                part
                for part in (
                    result.get("company") or "Proje",
                    result.get("license_no") or "",
                    Path(record["relative_path"]).stem,
                )
                if part
            )
        )
        kml_path = kml_dir / f"{file_name}.kml"
        if result["polygon_count"]:
            KMLExporter.export(project, kml_path)
            result["kml_path"] = str(kml_path)
        else:
            result["kml_path"] = ""
            result["kml_skipped"] = "polygon_yok"
        summaries.append(result)
        print(
            "  tables={table_count} coords={coordinate_count} "
            "polygons={polygon_count} types={polygon_types} "
            "index={index_found}".format(
                **result
            )
        )

    summary_path = args.output / "sample10_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "ocr_used": False,
                "seed": args.seed,
                "max_pages": args.max_pages,
                "excluded_count": len(excluded),
                "pdfs": summaries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print("SUMMARY", summary_path)
    print("KML_DIR", kml_dir)


if __name__ == "__main__":
    main()
