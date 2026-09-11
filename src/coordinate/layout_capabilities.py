"""Layout difference classes handled by the coordinate pipeline.

eMadenCBS is a general ÇED/PTD text-layer app. Named PDFs in QA are
witnesses for these classes, never allowlists. To add a new class:

1. Add an entry to LAYOUT_CLASSES with owning modules and capabilities.
2. Encode the class as a synthetic fixture in tests (no PDF bytes).
3. Implement the capability in the owning module, not as a filename rule.
4. If a stage can accept input and emit nothing, add a reason code in
   ``pipeline_contract`` so GUI/batch can surface the miss.
"""

LAYOUT_CLASSES = (
    {
        "id": "table_continuation",
        "title": "Table continuation / Tip2",
        "modules": (
            "src.coordinate.table_detector",
            "src.coordinate.table_classifier",
            "src.coordinate.coordinate_engine",
        ),
        "capabilities": (
            "headerless_multipage_continuation",
            "crs_decimal_is_not_section_number",
            "inherit_table_type_and_section",
        ),
        "contract": (
            "A headerless next page that continues UTM rows stays in the "
            "same table. Scale factors and latitudes are not section numbers."
        ),
    },
    {
        "id": "coordinate_record_layouts",
        "title": "Coordinate record layouts",
        "modules": (
            "src.coordinate.state_machine",
        ),
        "capabilities": (
            "full_y_x_lat_lon_block",
            "utm_only_block",
            "column_major_dump",
            "northing_easting_order",
            "unlabeled_pairs",
            "space_dot_comma_thousands",
        ),
        "contract": (
            "Accepted numeric tokens in Y+X, UTM-only, column-major, "
            "swapped northing/easting, unlabeled, or grouped-thousands "
            "forms become points."
        ),
    },
    {
        "id": "detector_parser_contract",
        "title": "Detector vs parser contract",
        "modules": (
            "src.coordinate.table_detector",
            "src.coordinate.state_machine",
            "src.coordinate.coordinate_engine",
            "src.coordinate.pipeline_contract",
        ),
        "capabilities": (
            "accepted_table_must_parse_or_report",
        ),
        "contract": (
            "If TableDetector accepts a coordinate table, the parser must "
            "emit points or the pipeline must report DETECTED_TABLE_NO_POINTS. "
            "Never silent tables>0 / coords=0."
        ),
    },
    {
        "id": "crs_inheritance",
        "title": "CRS inheritance / transform",
        "modules": (
            "src.coordinate.datum_detector",
            "src.coordinate.crs_resolver",
            "src.coordinate.coordinate_engine",
        ),
        "capabilities": (
            "document_level_high_crs",
            "previous_table_high_crs",
            "export_utm_without_table_local_zone",
        ),
        "contract": (
            "Zone/datum may live outside the table slice. Document-level or "
            "prior-table HIGH CRS is used for WGS84. UTM points are not "
            "dropped from KML only because the table-local Zon line is missing."
        ),
    },
    {
        "id": "ring_geometry",
        "title": "Ring geometry",
        "modules": (
            "src.coordinate.ring_geometry",
            "src.coordinate.polygon_builder",
            "src.export.kml_exporter",
        ),
        "capabilities": (
            "simple_bowtie_uncross",
            "multi_cross_split",
            "lonlat_vs_utm_independent_repair",
            "degree_scale_not_metre_collapse",
            "compact_degree_no_leftover_crossings",
        ),
        "contract": (
            "Bow-tie and multi-cross rings are uncrossed or split. KML lon/lat "
            "repair is independent of UTM. Degree-scale rings must not use a "
            "~0.01 collapse that smashes small ÇED polygons. Compact rings "
            "(span ≪ 0.01°) must not leave multi-cross leftovers in exported "
            "KML coordinate text."
        ),
    },
    {
        "id": "grouping_typing",
        "title": "Grouping / typing",
        "modules": (
            "src.coordinate.table_classifier",
            "src.coordinate.state_machine",
            "src.coordinate.polygon_builder",
        ),
        "capabilities": (
            "area_heading_nolu_poligons",
            "ced_vs_ruhsat_typing",
            "keep_distinct_types_on_shared_geometry",
            "report_groups_below_three_vertices",
        ),
        "contract": (
            "NOLU POLİGON / ÇED / ruhsat headings type and group points. "
            "Groups with fewer than 3 vertices are reported, not silent. "
            "Dedup must not erase RUHSAT when geometry matches ÇED."
        ),
    },
    {
        "id": "metadata_kml_naming",
        "title": "Metadata / KML naming",
        "modules": (
            "src.project.project_info_extractor",
            "src.export.kml_exporter",
        ),
        "capabilities": (
            "sicil_from_prose_or_label",
            "strip_company_label_junk",
            "usable_export_name_tokens_only",
        ),
        "contract": (
            "Sicil and company tokens come from general extractor rules. "
            "Page headers and field labels are not export-name tokens."
        ),
    },
)

LAYOUT_CLASS_IDS = tuple(item["id"] for item in LAYOUT_CLASSES)

LAYOUT_CLASS_BY_ID = {
    item["id"]: item
    for item in LAYOUT_CLASSES
}


def layout_class(class_id):
    return LAYOUT_CLASS_BY_ID[class_id]


def modules_for_class(class_id):
    return layout_class(class_id)["modules"]
