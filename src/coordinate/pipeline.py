"""Run the coordinate pipeline as one contract-aware pass.

GUI and batch can still call detector / engine / builder separately.
This helper is the supported way to get tables, points, polygons, and
reason codes together without silent tables>0 / coords=0.
"""

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.pipeline_contract import (
    collect_pipeline_diagnostics,
    compact_diagnostics,
    reason_codes,
)
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.table_detector import TableDetector


def run_coordinate_pipeline(text, pdf_path=None, tables=None):
    if tables is None:
        tables = TableDetector.find_tables(text)

    extraction = CoordinateEngine.extract_pipeline(
        text,
        pdf_path=pdf_path,
        tables=tables,
    )
    coordinates = extraction["coordinates"]
    polygons = PolygonBuilder.build(coordinates)
    diagnostics = collect_pipeline_diagnostics(
        extraction["tables"],
        coordinates,
        polygons,
        extra=extraction["diagnostics"],
    )
    return {
        "tables": extraction["tables"],
        "coordinates": coordinates,
        "polygons": polygons,
        "diagnostics": diagnostics,
        "reason_codes": reason_codes(diagnostics),
        "compact_diagnostics": compact_diagnostics(diagnostics),
    }
