"""Pre-export area / CRS / layer gate.

Named PDFs are not used. Fixtures encode the Destekci class:
table-declared ha vs computed ring ha, insane CRS, missing ÇED.
"""

import math
import tempfile
import unittest
from pathlib import Path

from src.coordinate.area_qa import (
    ABSOLUTE_FLOOR_HA,
    RELATIVE_TOLERANCE,
    compare_declared_vs_computed,
    evaluate_export_gate,
    heading_is_combined_ruhsat_ced,
    parse_declared_area_ha,
)
from src.coordinate.pipeline import run_coordinate_pipeline
from src.coordinate.pipeline_contract import (
    AREA_MISMATCH,
    CRS_AREA_INSANE,
    CRS_LONLAT_OUT_OF_RANGE,
    EXPORT_BLOCKED,
    MISSING_RUHSAT_OR_CED,
    collect_pipeline_diagnostics,
    reason_codes,
)
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.project_model import ProjectModel
from src.export.kml_exporter import KMLExporter


def page(page_number, *lines):
    return "\n".join(
        [
            f"--- Sayfa {page_number} [PDF METİN KATMANI] ---",
            *lines,
        ]
    )


CRS = (
    "Koordinat Sırası : Sağa Yukarı",
    "Datum : ED-50",
    "Türü : UTM",
    "Zon : 36",
)


def square_utm(start_y, start_x, size):
    return (
        (start_y, start_x),
        (start_y + size, start_x),
        (start_y + size, start_x + size),
        (start_y, start_x + size),
    )


def stacked_utm_lines(labels, pairs):
    lines = []
    for label, (easting, northing) in zip(labels, pairs):
        lines.extend((label, str(easting), str(northing)))
    return tuple(lines)


def _utm_point(
    name,
    easting,
    northing,
    table_type,
    heading,
    declared_ha=None,
    longitude=None,
    latitude=None,
    polygon_group="DEFAULT",
    table_index=1,
    section=None,
):
    point = {
        "name": name,
        "y": easting,
        "x": northing,
        "table_type": table_type,
        "section": section or heading,
        "table_index": table_index,
        "polygon_group": polygon_group,
        "polygon_heading": heading,
    }
    if declared_ha is not None:
        point["declared_ha"] = declared_ha
    if longitude is not None:
        point["longitude"] = longitude
        point["transformed_longitude"] = longitude
    if latitude is not None:
        point["latitude"] = latitude
        point["transformed_latitude"] = latitude
    return point


def ring_coordinates(
    table_type,
    heading,
    origin,
    area_ha,
    declared_ha=None,
    longitude=35.32,
    latitude=37.00,
    **kwargs,
):
    size = math.sqrt(area_ha * 10000)
    corners = square_utm(origin[0], origin[1], size)
    declared = area_ha if declared_ha is None else declared_ha
    coordinates = []
    for index, (easting, northing) in enumerate(corners):
        coordinates.append(
            _utm_point(
                f"{table_type[0]}{index + 1}",
                easting,
                northing,
                table_type,
                heading,
                declared_ha=declared,
                longitude=longitude,
                latitude=latitude,
                **kwargs,
            )
        )
    return coordinates


def build_model(coordinates, project_info=None, tables=None):
    polygons = PolygonBuilder.build(coordinates)
    model = ProjectModel(
        pdf_path="gate.pdf",
        coordinates=coordinates,
        polygons=polygons,
        tables=tables or ["table"],
    )
    if project_info:
        model.set_project_info(project_info)
    return model


class DeclaredAreaParsingTests(unittest.TestCase):
    def test_prefers_ha_when_m2_and_ha_both_present(self):
        self.assertAlmostEqual(
            parse_declared_area_ha("183.081 m² (18,30 ha)"),
            18.30,
            places=2,
        )
        self.assertAlmostEqual(
            parse_declared_area_ha("ALAN =50.500 m2 (5,05 HEKTAR)"),
            5.05,
            places=2,
        )

    def test_standalone_m2_converts_to_hectares(self):
        self.assertAlmostEqual(
            parse_declared_area_ha("183.081 m²"),
            18.3081,
            places=3,
        )
        self.assertAlmostEqual(
            parse_declared_area_ha("Alan: 50.500 m2"),
            5.05,
            places=2,
        )

    def test_comma_ha_and_ignores_file_total(self):
        self.assertAlmostEqual(
            parse_declared_area_ha("1 No.lu ÇED Poligonu (12,4 ha)"),
            12.4,
            places=2,
        )
        self.assertIsNone(
            parse_declared_area_ha("Toplam Alan: 262,57 ha")
        )


class AreaComparisonTests(unittest.TestCase):
    def test_match_within_relative_tolerance(self):
        declared = 18.30
        computed = declared * (1.0 + RELATIVE_TOLERANCE * 0.5)
        comparison = compare_declared_vs_computed(declared, computed)
        self.assertTrue(comparison["match"])
        self.assertAlmostEqual(comparison["declared_ha"], 18.30, places=2)

    def test_mismatch_merged_ced_scale(self):
        comparison = compare_declared_vs_computed(18.30, 1509.0)
        self.assertFalse(comparison["match"])
        self.assertGreater(comparison["ratio"], 50)

    def test_tiny_parcel_uses_absolute_floor(self):
        comparison = compare_declared_vs_computed(
            0.05,
            0.08,
            absolute_floor_ha=ABSOLUTE_FLOOR_HA,
        )
        self.assertTrue(comparison["match"])
        self.assertEqual(comparison["allowed_ha"], ABSOLUTE_FLOOR_HA)


class ExportGateTests(unittest.TestCase):
    def test_matching_ruhsat_and_ced_writes_kml(self):
        coordinates = []
        coordinates.extend(
            ring_coordinates(
                "RUHSAT_ALANI",
                "Ruhsat Alanı (100,00 ha)",
                (500000.0, 4100000.0),
                100.0,
                table_index=1,
                polygon_group="POLIGON_R",
            )
        )
        coordinates.extend(
            ring_coordinates(
                "CED_ALANI",
                "ÇED Alanı (18,30 ha)",
                (501000.0, 4101000.0),
                18.30,
                table_index=2,
                polygon_group="POLIGON_1",
            )
        )
        model = build_model(
            coordinates,
            project_info={"province": "Adana"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "Adana" / "Ek-1" / "ok.kml"
            result = KMLExporter.export(model, str(path))
            self.assertTrue(result["ok"])
            self.assertTrue(result["written"])
            self.assertTrue(path.is_file())
            self.assertGreater(path.stat().st_size, 0)
        self.assertFalse(any(p.get("area_mismatch") for p in model.polygons))

    def test_mismatch_does_not_create_or_overwrite_kml(self):
        coordinates = []
        coordinates.extend(
            ring_coordinates(
                "RUHSAT_ALANI",
                "Ruhsat Alanı (100,00 ha)",
                (500000.0, 4100000.0),
                100.0,
                table_index=1,
            )
        )
        coordinates.extend(
            ring_coordinates(
                "CED_ALANI",
                "ÇED Alanı-1 (18,30 ha)",
                (434529.0, 4205189.0),
                1509.0,
                declared_ha=18.30,
                table_index=2,
            )
        )
        model = build_model(coordinates)
        diagnostics = collect_pipeline_diagnostics(
            ["t1", "t2"],
            coordinates,
            model.polygons,
        )
        self.assertIn(AREA_MISMATCH, reason_codes(diagnostics))

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ok.kml"
            path.write_text("EXISTING", encoding="utf-8")
            result = KMLExporter.export(model, str(path))
            self.assertFalse(result["ok"])
            self.assertFalse(result["written"])
            self.assertIn("AREA_MISMATCH", result["codes"])
            self.assertIn("EXPORT_BLOCKED", result["codes"])
            self.assertEqual(path.read_text(encoding="utf-8"), "EXISTING")
            quarantine = Path(tmp) / "_Duzeltme" / "ok.json"
            self.assertTrue(quarantine.is_file())
            payload = quarantine.read_text(encoding="utf-8")
            self.assertIn("AREA_MISMATCH", payload)
            self.assertIn("18.3", payload)

    def test_huge_area_crs_failure_blocks_write(self):
        coordinates = ring_coordinates(
            "CED_ALANI",
            "ÇED Alanı",
            (500000.0, 4100000.0),
            1_200_000.0,
            declared_ha=None,
            table_index=1,
        )
        coordinates.extend(
            ring_coordinates(
                "RUHSAT_ALANI",
                "Ruhsat Alanı (80,00 ha)",
                (600000.0, 4200000.0),
                80.0,
                table_index=2,
                polygon_group="POLIGON_R",
            )
        )
        for point in coordinates:
            if point["table_type"] == "CED_ALANI":
                point.pop("declared_ha", None)
                point["polygon_heading"] = "ÇED Alanı"
                point["section"] = "ÇED Alanı"
        model = build_model(coordinates)
        gate = evaluate_export_gate(model)
        self.assertFalse(gate["ok"])
        self.assertIn(CRS_AREA_INSANE, gate["codes"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "huge.kml"
            result = KMLExporter.export(model, str(path))
            self.assertFalse(path.exists())
            self.assertIn(CRS_AREA_INSANE, result["codes"])

    def test_missing_ced_blocks_write(self):
        coordinates = ring_coordinates(
            "RUHSAT_ALANI",
            "Ruhsat Alanı (100,00 ha)",
            (500000.0, 4100000.0),
            100.0,
        )
        model = build_model(coordinates)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ruhsat-only.kml"
            result = KMLExporter.export(model, str(path))
            self.assertFalse(result["ok"])
            self.assertFalse(path.exists())
            self.assertIn(MISSING_RUHSAT_OR_CED, result["codes"])
            self.assertIn(EXPORT_BLOCKED, result["codes"])

    def test_adana_lon_outside_province_blocks(self):
        coordinates = []
        coordinates.extend(
            ring_coordinates(
                "RUHSAT_ALANI",
                "Ruhsat Alanı (80,00 ha)",
                (500000.0, 4100000.0),
                80.0,
                longitude=30.1,
                latitude=37.0,
                table_index=1,
            )
        )
        coordinates.extend(
            ring_coordinates(
                "CED_ALANI",
                "ÇED Alanı (12,00 ha)",
                (501000.0, 4101000.0),
                12.0,
                longitude=30.1,
                latitude=37.0,
                table_index=2,
                polygon_group="POLIGON_1",
            )
        )
        model = build_model(
            coordinates,
            project_info={"province": "Adana"},
        )
        gate = evaluate_export_gate(model)
        self.assertFalse(gate["ok"])
        self.assertIn(CRS_LONLAT_OUT_OF_RANGE, gate["codes"])

    def test_diger_identical_to_ced_is_suppressed_not_a_second_success(self):
        ced = ring_coordinates(
            "CED_ALANI",
            "ÇED Alanı (10,00 ha)",
            (501000.0, 4101000.0),
            10.0,
            table_index=1,
        )
        ruhsat = ring_coordinates(
            "RUHSAT_ALANI",
            "Ruhsat Alanı (80,00 ha)",
            (500000.0, 4100000.0),
            80.0,
            table_index=2,
            polygon_group="POLIGON_R",
        )
        diger = ring_coordinates(
            "DIGER",
            "Alan",
            (501000.0, 4101000.0),
            10.0,
            declared_ha=10.0,
            table_index=3,
            polygon_group="DEFAULT",
        )
        model = build_model(ced + ruhsat + diger)
        gate = evaluate_export_gate(model)
        self.assertTrue(gate["ok"], gate)
        diger_polygons = [
            polygon
            for polygon in model.polygons
            if polygon["table_type"] == "DIGER"
        ]
        self.assertTrue(diger_polygons)
        self.assertTrue(
            all(polygon.get("export_suppressed") for polygon in diger_polygons)
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "typed.kml"
            result = KMLExporter.export(model, str(path))
            self.assertTrue(result["ok"])
            text = path.read_text(encoding="utf-8")
            self.assertIn("ÇED", text)
            self.assertNotIn("Diğer Alan", text)

    def test_combined_heading_allows_shared_ruhsat_ced_ring(self):
        heading = "Ruhsat ve ÇED Alanı Koordinatları (25,00 ha)"
        self.assertTrue(heading_is_combined_ruhsat_ced(heading))
        ruhsat = ring_coordinates(
            "RUHSAT_ALANI",
            heading,
            (500000.0, 4100000.0),
            25.0,
            table_index=1,
        )
        ced = ring_coordinates(
            "CED_ALANI",
            heading,
            (500000.0, 4100000.0),
            25.0,
            table_index=2,
            polygon_group="POLIGON_1",
        )
        model = build_model(ruhsat + ced)
        gate = evaluate_export_gate(model)
        self.assertTrue(gate["ok"], gate)
        self.assertNotIn("DUPLICATE_LAYER_GEOMETRY", gate["codes"])

    def test_silent_ruhsat_ced_copy_is_blocked(self):
        ruhsat = ring_coordinates(
            "RUHSAT_ALANI",
            "Ruhsat Alanı (25,00 ha)",
            (500000.0, 4100000.0),
            25.0,
            table_index=1,
        )
        ced = ring_coordinates(
            "CED_ALANI",
            "ÇED Alanı (25,00 ha)",
            (500000.0, 4100000.0),
            25.0,
            table_index=2,
            polygon_group="POLIGON_1",
        )
        model = build_model(ruhsat + ced)
        gate = evaluate_export_gate(model)
        self.assertFalse(gate["ok"])
        self.assertIn("DUPLICATE_LAYER_GEOMETRY", gate["codes"])


class PipelineDeclaredAreaTests(unittest.TestCase):
    def test_heading_ha_attaches_and_matches_computed_ring(self):
        ring = square_utm(434529, 4205189, math.sqrt(18.30 * 10000))
        text = page(
            12,
            "Tablo 4. ÇED Alanı Koordinatları",
            *CRS,
            "ÇED Alanı (18,30 ha)",
            *stacked_utm_lines(("C1", "C2", "C3", "C4"), ring),
        )
        pipeline = run_coordinate_pipeline(text)
        ced = [
            polygon
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "CED_ALANI"
        ]
        self.assertEqual(len(ced), 1)
        self.assertAlmostEqual(ced[0]["declared_ha"], 18.30, places=2)
        self.assertAlmostEqual(ced[0]["area_ha"], 18.30, delta=0.05)
        self.assertFalse(ced[0].get("area_mismatch"))
        self.assertNotIn(AREA_MISMATCH, pipeline["reason_codes"])

    def test_numbered_ced_labels_stay_separate_rings(self):
        ced_one = square_utm(434529, 4205189, math.sqrt(18.30 * 10000))
        ced_two = square_utm(436000, 4207000, math.sqrt(3.00 * 10000))
        text = page(
            20,
            "Tablo 3. ÇED Alanları Koordinatları",
            *CRS,
            "ÇED Alanı-1 (18,30 ha)",
            *stacked_utm_lines(("A1", "A2", "A3", "A4"), ced_one),
            "ÇED Alanı-2 (3,00 ha)",
            *stacked_utm_lines(("B1", "B2", "B3", "B4"), ced_two),
        )
        pipeline = run_coordinate_pipeline(text)
        ced = [
            polygon
            for polygon in pipeline["polygons"]
            if polygon["table_type"] == "CED_ALANI"
        ]
        self.assertEqual(len(ced), 2)
        areas = sorted(polygon["area_ha"] for polygon in ced)
        self.assertAlmostEqual(areas[0], 3.00, delta=0.05)
        self.assertAlmostEqual(areas[1], 18.30, delta=0.05)
        self.assertTrue(
            all(not polygon.get("area_mismatch") for polygon in ced)
        )
        groups = {polygon.get("polygon_group") for polygon in ced}
        self.assertGreaterEqual(len(groups), 2)


if __name__ == "__main__":
    unittest.main()
