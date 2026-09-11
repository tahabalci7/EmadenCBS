"""Late-document UTM appendix in long PDFs — discovery plus parse.

Named PDFs are witnesses only. No filename allowlists.
"""

import os
import tempfile
import unittest

import fitz

from src.coordinate.pipeline import run_coordinate_pipeline
from src.coordinate.pipeline_contract import POINTS_NO_POLYGON
from src.coordinate.table_index import (
    TableIndexLocator,
    merge_extraction_pages,
)
from src.export.kml_exporter import KMLExporter
from tools.sample_text_layer_kml import extract_ocr_free


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
    )


CRS = (
    "Datum : ED-50",
    "Turu : UTM",
    "Zon : 36",
)
SAGA_HEADERS = (
    "Saga (Y)",
    "Yukari (X)",
)
COMPANY = "Ornek Madencilik A.S."


def cell_points(labels, start_y, start_x, size=100):
    pairs = (
        (start_y, start_x),
        (start_y + size, start_x),
        (start_y + size, start_x + size),
        (start_y, start_x + size),
    )
    lines = []
    for label, (easting, northing) in zip(labels, pairs):
        lines.extend(
            (
                label,
                f"{easting:.3f}",
                f"{northing:.3f}",
            )
        )
    return tuple(lines), pairs


def late_appendix_text():
    ruhsat, _ = cell_points(("R1", "R2", "R3", "R4"), 442400, 4064825)
    ced, ced_pairs = cell_points(("C1", "C2", "C3", "C4"), 442600, 4065000)
    stok, _ = cell_points(("S1", "S2", "S3", "S4"), 442800, 4065200)
    toprak, _ = cell_points(("T1", "T2", "T3", "T4"), 443000, 4065400)
    galeri, _ = cell_points(("G1", "G2", "G3", "G4"), 443200, 4065600)
    santiye, _ = cell_points(("Y1", "Y2", "Y3", "Y4"), 443400, 4065800)
    return "\n".join(
        [
            page(
                181,
                COMPANY,
                "Ruhsat Alani Koordinatlari",
                *CRS,
                *SAGA_HEADERS,
                *ruhsat,
            ),
            page(
                182,
                COMPANY,
                "Ced Alani Koordinatlari",
                *SAGA_HEADERS,
                "C1",
                f"{ced_pairs[0][0]:.3f}",
                f"{ced_pairs[0][1]:.3f}",
                "C2",
                f"{ced_pairs[1][0]:.3f}",
                f"{ced_pairs[1][1]:.3f}",
            ),
            page(
                183,
                COMPANY,
                "C3",
                f"{ced_pairs[2][0]:.3f}",
                f"{ced_pairs[2][1]:.3f}",
                "C4",
                f"{ced_pairs[3][0]:.3f}",
                f"{ced_pairs[3][1]:.3f}",
            ),
            page(
                184,
                COMPANY,
                "Stok Alani Koordinatlari",
                *SAGA_HEADERS,
                *stok,
                "Bitkisel Toprak Alani Koordinatlari",
                *SAGA_HEADERS,
                *toprak,
            ),
            page(
                185,
                COMPANY,
                "Galeri Alani Koordinatlari",
                *SAGA_HEADERS,
                *galeri,
                "Santiye Alani Koordinatlari",
                *SAGA_HEADERS,
                *santiye,
            ),
        ]
    )


def write_long_pdf(path):
    document = fitz.open()
    toc = "\n".join(
        [
            "ICINDEKILER",
            "1. Giris ................................ 1",
            "2.3 Proje Alani Koordinatlari ......... 181",
        ]
    )
    appendix = {
        181: "\n".join(
            [
                COMPANY,
                "Ruhsat Alani Koordinatlari",
                *CRS,
                *SAGA_HEADERS,
                *cell_points(("R1", "R2", "R3", "R4"), 442400, 4064825)[0],
            ]
        ),
        182: "\n".join(
            [
                COMPANY,
                "Ced Alani Koordinatlari",
                *SAGA_HEADERS,
                "C1",
                "442600.000",
                "4065000.000",
                "C2",
                "442700.000",
                "4065000.000",
            ]
        ),
        183: "\n".join(
            [
                COMPANY,
                "C3",
                "442700.000",
                "4065100.000",
                "C4",
                "442600.000",
                "4065100.000",
            ]
        ),
        184: "\n".join(
            [
                COMPANY,
                "Stok Alani Koordinatlari",
                *SAGA_HEADERS,
                *cell_points(("S1", "S2", "S3", "S4"), 442800, 4065200)[0],
            ]
        ),
        185: "\n".join(
            [
                COMPANY,
                "Galeri Alani Koordinatlari",
                *SAGA_HEADERS,
                *cell_points(("G1", "G2", "G3", "G4"), 443200, 4065600)[0],
            ]
        ),
    }
    for page_number in range(1, 186):
        pdf_page = document.new_page()
        if page_number == 1:
            pdf_page.insert_textbox(pdf_page.rect, toc, fontsize=9)
        elif page_number in appendix:
            pdf_page.insert_textbox(
                pdf_page.rect,
                appendix[page_number],
                fontsize=9,
            )
        else:
            pdf_page.insert_textbox(
                pdf_page.rect,
                "Proje tanimi ve is akimi metni. Koordinat yok.",
                fontsize=9,
            )
    document.save(path)
    document.close()


class LateDocumentUtmAppendixTests(unittest.TestCase):
    def test_synthetic_late_pages_parse_to_polygons(self):
        text = late_appendix_text()
        pipeline = run_coordinate_pipeline(text)
        self.assertGreater(len(pipeline["coordinates"]), 0)
        self.assertGreater(
            len(pipeline["polygons"]),
            0,
            pipeline["reason_codes"],
        )
        self.assertNotIn(POINTS_NO_POLYGON, pipeline["reason_codes"])
        self.assertTrue(
            any(
                KMLExporter._build_coordinate_texts(polygon)
                for polygon in pipeline["polygons"]
            )
        )
        types = {
            polygon.get("table_type") for polygon in pipeline["polygons"]
        }
        self.assertTrue(
            types.intersection(
                {
                    "RUHSAT_ALANI",
                    "CED_ALANI",
                    "STOK_ALANI",
                    "BITKISEL_TOPRAK_ALANI",
                    "GALERI_ALANI",
                    "SANTIYE_ALANI",
                }
            ),
            types,
        )

    def test_extract_ocr_free_merges_pages_beyond_max_pages(self):
        with tempfile.TemporaryDirectory() as folder:
            pdf_path = os.path.join(folder, "late_appendix.pdf")
            write_long_pdf(pdf_path)
            plan = TableIndexLocator.plan(pdf_path)
            self.assertGreaterEqual(plan["page_count"], 185)
            self.assertIn(181, plan["target_pages"])
            merged = merge_extraction_pages(
                150,
                plan["target_pages"],
                plan["page_count"],
            )
            self.assertIn(181, merged)
            self.assertNotIn(181, set(range(1, 151)))

            extraction = extract_ocr_free(pdf_path, max_pages=150)
            extracted = set(
                extraction.get("extracted_page_numbers") or []
            )
            self.assertIn(181, extracted)
            text = extraction.get("text", "")
            self.assertIn("442400", text)
            self.assertIn("--- Sayfa 181", text)

            pipeline = run_coordinate_pipeline(text)
            self.assertGreater(
                len(pipeline["polygons"]),
                0,
                pipeline["reason_codes"],
            )


if __name__ == "__main__":
    unittest.main()
