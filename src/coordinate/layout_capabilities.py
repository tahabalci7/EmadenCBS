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
            "late_caption_not_previous_continuation",
            "split_area_heading_starts_table",
        ),
        "contract": (
            "A headerless next page that continues UTM rows stays in the "
            "same table. Scale factors and latitudes are not section numbers. "
            "Headerless UTM rows before a same-page caption of a different "
            "area type are that caption's body (reading-order inversion), "
            "not a continuation of the previous table. This includes rows "
            "already appended to an open numbered STOK/auxiliary table on "
            "the same page. Split captions such as Yeni ÇED / Alanı / "
            "Koordinatları start a new table."
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
            "geographic_only_unlabeled_ring",
            "dual_crs_yx_then_split_lat_lon",
        ),
        "contract": (
            "Accepted numeric tokens in Y+X, UTM-only, column-major, "
            "swapped northing/easting, unlabeled, grouped-thousands, "
            "unlabeled lon/lat-only rings, or dual-CRS side-by-side "
            "rows (index; SAĞA/YUKARI on one line; ENLEM then BOYLAM "
            "on the following lines, including the live text-layer "
            "interleave index+lat then Y/X+lon) become points."
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
            "ed50_space_and_dilim_zone_aliases",
        ),
        "contract": (
            "Zone/datum may live outside the table slice. Document-level or "
            "prior-table HIGH CRS is used for WGS84. UTM points are not "
            "dropped from KML only because the table-local Zon line is missing. "
            "PTD/ÇED aliases ED 50 and Dilim 35–39 count as explicit CRS."
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
            "nolu_vertex_is_not_polygon_group",
            "area_heading_nolu_poligons",
            "ced_vs_ruhsat_typing",
            "keep_distinct_types_on_shared_geometry",
            "report_groups_below_three_vertices",
            "auxiliary_not_inherit_dominant_ring",
            "parenthetical_ced_is_not_tesisi_type",
            "geo_ring_not_inherit_auxiliary",
            "unattested_lattice_not_composite_ring",
        ),
        "contract": (
            "NOLU POLİGON / ÇED / ruhsat headings type and group points. "
            "NOLU NOKTA / KÖŞE vertex labels stay in one ring; they are not "
            "polygon headings. Groups with fewer than 3 vertices are "
            "reported, not silent. Dedup must not erase RUHSAT when "
            "geometry matches ÇED. An auxiliary ring (STOK/tesis/pasa) "
            "must not inherit a ÇED-scale footprint from a misattached "
            "or late-caption table. A tesisi/stok/ünite caption with "
            "parenthetical (Talep Edilen ÇED Alanı) stays tesisi/stok; "
            "a leftover 15-pt geographic ring after Malzeme Stok is ÇED, "
            "not STOK. A 500 m cartesian lattice mixed with real tesisi "
            "verts, or UTM pairs absent from the table text, is not a "
            "STOK ring — including lon/lat y/x rings and L-shaped / "
            "partial 500 m meshes mixed with a compact tesisi cluster "
            "(do not require 60% of the full cartesian product)."
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
            "ek_tip_from_ced_or_ptd_title",
            "export_path_il_ek_sicil_company",
        ),
        "contract": (
            "Restore {İL}/{Ek-1|Ek-2}/{sicil} - {firma}.kml. PR #2 "
            "(33cc525) inverted the stem to company-then-sicil; GUI "
            "since 6e2515c wrote flat under the root. Ek-1 is ÇED "
            "Raporu / Nihai ÇED; Ek-2 is PTD. Missing il, Ek tip, "
            "sicil, or firma stay visible as Bilinmiyor."
        ),
    },
    {
        "id": "coordinate_appendix_index",
        "title": "EK-1 selected-site coordinate appendix",
        "modules": (
            "src.coordinate.table_index",
        ),
        "capabilities": (
            "toc_ek1_appendix_to_target_pages",
            "appendix_pages_beyond_fast_scan",
            "toc_ek1_unnumbered_or_wrapped",
            "appendix_body_scan_without_printed_page",
        ),
        "contract": (
            "İÇİNDEKİLER / EKLER entries for the selected-site "
            "coordinate appendix (EK-1 / Ek 1 / Ek 1- / 1- Proje "
            "için seçilen yerin koordinatları) add those pages to "
            "target_pages even when they are beyond the fast-scan "
            "max_pages window (150). Wrapped titles and lines "
            "without dotted leaders / page numbers still resolve "
            "via a late appendix body scan. Folder EK-2 (PTD "
            "project type) is not the same as this appendix label "
            "EK-1."
        ),
    },
    {
        "id": "scanned_coordinate_appendix",
        "title": "Scanned EK-1 coordinate appendix",
        "modules": (
            "src.coordinate.table_index",
            "src.core.pdf_text_extraction_service",
        ),
        "capabilities": (
            "ocr_when_appendix_lacks_utm_pairs",
        ),
        "contract": (
            "When the selected-site coordinate appendix is "
            "referenced but the text layer of those pages has no "
            "6-digit UTM pairs, the live export path OCRs the "
            "planned appendix pages. A dust-monitor / hava "
            "kalitesi X/Y table is not a substitute for the "
            "scanned appendix rings."
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
