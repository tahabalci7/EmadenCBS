# Layout difference classes

eMadenCBS is a general PySide6 app for Turkish ÇED/PTD **text-layer** PDFs.
QA PDFs are witnesses for layout **classes**. Do not add filename, province,
or project-specific parser branches.

## Pipeline

```
PDF text
  → TableDetector
  → TableClassifier / DatumDetector
  → state_machine (parse)
  → CoordinateEngine (CRS inherit + provenance)
  → PolygonBuilder
  → ring_geometry
  → KMLExporter
  → ProjectInfoExtractor (names)
```

`src/coordinate/layout_capabilities.py` is the capability map.
`src/coordinate/pipeline_contract.py` is the silent-failure contract.
`src/coordinate/pipeline.py` (`run_coordinate_pipeline`) returns tables,
coordinates, polygons, and reason codes together.

## Difference class → module

| Class | Owning modules | Capability |
| --- | --- | --- |
| Table continuation / Tip2 | `table_detector`, `table_classifier`, `coordinate_engine`, `table_index` | Headerless next-page rows stay in the same table. `0.9996` / latitudes are not section numbers. UTM-only Y(Sağa)/X(Yukarı) cell-per-line tables continue across page breaks and running headers/prose without a new full header. Index-guided extraction walks the mid-document coordinate chapter (one prose gap allowed), not only `CONTINUATION_AFTER=3`. |
| Coordinate record layouts | `state_machine` | Y+X+lat+lon, UTM-only, column-major, N/E order, unlabeled pairs, space/dot/comma thousands, cell-per-line Y(Sağa)/X(Yukarı). |
| Detector vs parser | `table_detector`, `state_machine`, `pipeline_contract` | Accepted table → points **or** `DETECTED_TABLE_NO_POINTS`. Never silent tables>0 / coords=0. |
| CRS inheritance | `datum_detector`, `crs_resolver`, `coordinate_engine` | Document or prior-table HIGH CRS supplies WGS84 when the table slice has no Zon. |
| Ring geometry | `ring_geometry`, `polygon_builder`, `kml_exporter` | Bow-tie uncross, multi-cross split, lon/lat repair independent of UTM, degree-scale collapse ≠ 0.01 m. Compact rings (span ≪ 0.01°) must not leave multi-cross leftovers in **exported KML text**. |
| Grouping / typing | `table_classifier`, `state_machine`, `polygon_builder` | NOLU POLİGON / Tablo-N / N. Poligon / ÇED / ruhsat. `<3` verts reported. RUHSAT not erased when geometry matches ÇED. |
| Metadata / KML naming | `project_info_extractor`, `kml_exporter` | Sicil + usable company tokens; strip page-header / label junk. |

## Reason codes

Stable identifiers for GUI and batch (`pipeline_reason_codes`):

- `NO_COORDINATE_TABLE`
- `DETECTED_TABLE_NO_POINTS`
- `POINTS_NO_POLYGON`
- `GROUP_BELOW_POLYGON_SIZE`
- `CRS_INHERITED`
- `CRS_UNRESOLVED_NO_TRANSFORM`
- `KML_NO_WGS84`
- `KML_RING_STILL_CROSSED`

## Destekci standing QA

Apply on this PR and later geometry work:

1. Destekci reviews KML lon/lat after export. Remaining kelebek is reported as a **geometry class** (vertex scale, leftover crossings after repair/split), not as a one-off PDF chase.
2. Prefer a general fix for that class. Named PDFs are witnesses only — no filename allowlists.
3. If a class still cannot yield clean ruhsat/ÇED rings after a good-faith general fix, Destekci opens the PDF UI so the owner can help select tables. Do not block the PR forever on one witness.

Compact-degree leftover class (span ≪ 0.01°, ~95 vertices, a handful of crossings after lon/lat repair): `repair_lonlat_rings` must finish remainders (iterative split or last-resort hull). Exported KML coordinate text, including closed LinearRings, must have 0 crossings. `tools/scan_kml_geometry.py` is the file-scan contract Destekci uses.

## How to add a new layout class

1. Add an entry to `LAYOUT_CLASSES` (id, modules, capabilities, contract).
2. Add a **synthetic** fixture in `tests/test_layout_class_contracts.py`. No PDF bytes, no filename allowlists.
3. Implement the capability in the owning module as a general rule.
4. If a stage can accept input and emit nothing, add a reason code and assert it in the fixture.
5. Keep `extract_coordinates(...)` returning `list` (GUI/batch wrappers).

## Local corpus re-check (not the product goal)

Named PDFs are only for the maintainer’s regression pass:

```bash
python -m unittest discover -s tests -v
python tools/sample_text_layer_kml.py --root <corpus> --output <out> --count 10
python tools/scan_kml_geometry.py <out>/kml
python tools/diagnose_table_coordinate_failure.py <pdf>
```

Look at `pipeline_reason_codes`, `kml_crossed_rings`, and empty/crossed rings.
A class miss is a contract gap; do not patch the witness PDF’s name.
