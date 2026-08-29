import hashlib
import re
import unicodedata

from src.coordinate.table_classifier import TableClassifier
from src.coordinate.crs_resolver import CRSResolver
from src.coordinate.datum_detector import DatumDetector
from src.coordinate.state_machine import parse_coordinate_blocks
from src.coordinate.table_area_scope_resolver import (
    TableAreaScopeResolver,
)
from src.coordinate.table_detector import TableDetector


class CoordinateEngine:

    PAGE_HEADER_PATTERN = re.compile(
        r"^--- Sayfa (?P<page>\d+) "
        r"\[(?P<source>[^\]\r\n]+)\] ---$"
    )

    SOURCE_METHODS = {
        "OCR": "ocr",
        "PDF METİN KATMANI": "text_layer",
        (
            "PDF METİN KATMANI "
            "- TESSERACT YOK"
        ): "text_layer",
        (
            "PDF METİN KATMANI "
            "- OCR BAŞARISIZ"
        ): "text_layer",
    }

    @classmethod
    def extract_coordinates(
        cls,
        text,
        pdf_path=None,
    ):
        tables = TableDetector.find_tables(
            text
        )

        if not tables:
            return []

        table_line_sources = (
            cls._match_table_line_sources(
                text,
                tables,
            )
        )

        observation_identities = (
            cls._build_observation_identities(
                tables,
                table_line_sources,
            )
        )

        results = []
        seen = set()
        observation_records = []

        for table_index, table in enumerate(
            tables,
            start=1,
        ):
            section = cls._detect_section(
                table
            )

            table_type = TableClassifier.classify(
                table
            )

            datum_info = DatumDetector.detect(
                table
            )

            crs_metadata = {
                "datum": datum_info[
                    "utm_datum"
                ],
                "type": "UTM",
                "zone": datum_info[
                    "zone"
                ],
                "dom": datum_info[
                    "dom"
                ],
                "projection": datum_info[
                    "projection"
                ],
            }

            projected_crs = (
                CRSResolver.resolve_projected_crs(
                    crs_metadata
                )
            )

            transformed_coordinate_cache = {}

            table_points = parse_coordinate_blocks(
                table,
                line_sources=(
                    table_line_sources[
                        table_index - 1
                    ]
                ),
            )

            observation_records.append(
                cls._build_table_identity_record(
                    table=table,
                    line_sources=(
                        table_line_sources[
                            table_index - 1
                        ]
                    ),
                    table_points=table_points,
                    source_observation_identity=(
                        observation_identities[
                            table_index - 1
                        ]
                    ),
                )
            )

            for point in table_points:
                polygon_group = point.get(
                    "polygon_group",
                    "DEFAULT",
                )                
            for point in table_points:
                polygon_group = point.get(
                    "polygon_group",
                    "DEFAULT",
                )

                key = (
                    table_index,
                    polygon_group,
                    point["label"],
                    point["utm_y"],
                    point["utm_x"],
                )

                if key in seen:
                    continue

                seen.add(
                    key
                )

                point_table_type = point.get(
                    "table_type_override"
                ) or table_type

                transform_metadata = (
                    cls._build_transform_metadata(
                        point=point,
                        crs_metadata=crs_metadata,
                        projected_crs=projected_crs,
                        coordinate_cache=(
                            transformed_coordinate_cache
                        ),
                    )
                )

                results.append(
                    cls._make_result(
                        point=point,
                        table_index=table_index,
                        section=section,
                        table_type=point_table_type,
                        datum_info=datum_info,
                        source_observation_identity=(
                            observation_identities[
                                table_index - 1
                            ]
                        ),
                        transform_metadata=(
                            transform_metadata
                        ),
                    )
                )

        table_identities = (
            cls._build_table_identities(
                observation_records
            )
        )

        for result in results:
            result[
                "source_table_identity"
            ] = table_identities[
                result[
                    "source_observation_identity"
                ]
            ]

        if pdf_path is not None:
            try:
                TableAreaScopeResolver.apply_pdf(
                    pdf_path,
                    results,
                )
            except Exception:
                pass

        results.sort(
            key=cls._priority_score,
            reverse=True,
        )

        return results

    @classmethod
    def _make_result(
        cls,
        point,
        table_index,
        section,
        table_type,
        datum_info,
        source_observation_identity,
        transform_metadata,
    ):
        return {
            "line": 0,
            "value": (
                f'{point["label"]} | '
                f'Y: {point["utm_y"]} | '
                f'X: {point["utm_x"]}'
            ),
            "score": cls._section_score(
                section
            ),
            "text": point["label"],
            "section": section,
            "table_type": table_type,
            "table_index": table_index,

            # ---------------------------------------------
            # ALT POLİGON BİLGİSİ
            # ---------------------------------------------

            "polygon_group": point.get(
                "polygon_group",
                "DEFAULT",
            ),
            "polygon_heading": point.get(
                "polygon_heading",
                "",
            ),

            # ---------------------------------------------
            # KOORDİNAT SİSTEMİ
            # ---------------------------------------------

            "datum": datum_info[
                "utm_datum"
            ],
            "geographic_datum": datum_info[
                "geographic_datum"
            ],
            "type": "UTM",
            "zone": datum_info[
                "zone"
            ],
            "dom": datum_info[
                "dom"
            ],
            "projection": datum_info[
                "projection"
            ],

            # ---------------------------------------------
            # NOKTA
            # ---------------------------------------------

            "name": point["label"],
            "y": point["utm_y"],
            "x": point["utm_x"],
            "latitude": point[
                "latitude"
            ],
            "longitude": point[
                "longitude"
            ],
            "source_page": point.get(
                "source_page"
            ),
            "source_method": point.get(
                "source_method"
            ),
            "source_observation_identity": (
                source_observation_identity
            ),
            "projected_crs_epsg": (
                transform_metadata[
                    "projected_crs_epsg"
                ]
            ),
            "projected_crs_name": (
                transform_metadata[
                    "projected_crs_name"
                ]
            ),
            "transformed_longitude": (
                transform_metadata[
                    "transformed_longitude"
                ]
            ),
            "transformed_latitude": (
                transform_metadata[
                    "transformed_latitude"
                ]
            ),
        }

    @classmethod
    def _build_transform_metadata(
        cls,
        point,
        crs_metadata,
        projected_crs,
        coordinate_cache,
    ):
        metadata = {
            "projected_crs_epsg": None,
            "projected_crs_name": None,
            "transformed_longitude": None,
            "transformed_latitude": None,
        }

        if projected_crs is None:
            return metadata

        metadata[
            "projected_crs_epsg"
        ] = projected_crs.to_epsg()
        metadata[
            "projected_crs_name"
        ] = projected_crs.name

        coordinate_key = (
            point["utm_y"],
            point["utm_x"],
        )

        if coordinate_key not in coordinate_cache:
            coordinate_cache[coordinate_key] = (
                CRSResolver.transform_to_wgs84(
                    easting=point["utm_y"],
                    northing=point["utm_x"],
                    metadata=crs_metadata,
                )
            )

        transformed = coordinate_cache[
            coordinate_key
        ]

        if transformed is None:
            return metadata

        (
            metadata["transformed_longitude"],
            metadata["transformed_latitude"],
        ) = transformed

        return metadata

    @classmethod
    def _build_observation_identities(
        cls,
        tables,
        table_line_sources,
    ):
        identities = []
        fingerprint_counts = {}

        for table, line_sources in zip(
            tables,
            table_line_sources,
        ):
            source_methods = []
            source_pages = []

            for source in line_sources:
                source_method = source.get(
                    "source_method"
                )
                source_page = source.get(
                    "source_page"
                )

                if (
                    source_method
                    and source_method
                    not in source_methods
                ):
                    source_methods.append(
                        source_method
                    )

                if isinstance(source_page, int):
                    source_pages.append(
                        source_page
                    )

            page_start = (
                min(source_pages)
                if source_pages
                else None
            )
            page_end = (
                max(source_pages)
                if source_pages
                else None
            )

            normalized_table = (
                cls._normalize_observation_text(
                    table
                )
            )

            canonical_fingerprint = (
                "source_method="
                + ",".join(source_methods)
                + "\nsource_page_start="
                + str(page_start)
                + "\nsource_page_end="
                + str(page_end)
                + "\ntable_text=\n"
                + normalized_table
            )

            base_digest = hashlib.sha256(
                canonical_fingerprint.encode(
                    "utf-8"
                )
            ).hexdigest()

            collision_index = (
                fingerprint_counts.get(
                    base_digest,
                    0,
                )
            )
            fingerprint_counts[base_digest] = (
                collision_index + 1
            )

            if collision_index:
                identity_digest = hashlib.sha256(
                    (
                        canonical_fingerprint
                        + "\ncollision="
                        + str(collision_index + 1)
                    ).encode(
                        "utf-8"
                    )
                ).hexdigest()
            else:
                identity_digest = base_digest

            identities.append(
                "obs_" + identity_digest
            )

        return identities

    @staticmethod
    def _normalize_observation_text(
        table_text,
    ):
        normalized_lines = []

        for raw_line in table_text.splitlines():
            normalized_line = " ".join(
                raw_line.split()
            )

            if normalized_line:
                normalized_lines.append(
                    normalized_line
                )

        return "\n".join(
            normalized_lines
        )

    @classmethod
    def _build_table_identity_record(
        cls,
        table,
        line_sources,
        table_points,
        source_observation_identity,
    ):
        source_methods = []
        source_pages = []

        for source in line_sources:
            source_method = source.get(
                "source_method"
            )
            source_page = source.get(
                "source_page"
            )

            if (
                source_method
                and source_method
                not in source_methods
            ):
                source_methods.append(
                    source_method
                )

            if isinstance(source_page, int):
                source_pages.append(
                    source_page
                )

        normalized_heading = (
            TableClassifier._normalize(
                TableClassifier._extract_heading(
                    table
                )
            ).strip()
        )

        table_number_match = re.match(
            r"^TABLO\s+(\d+)\b",
            normalized_heading,
        )

        return {
            "source_observation_identity": (
                source_observation_identity
            ),
            "source_method": (
                source_methods[0]
                if len(source_methods) == 1
                else None
            ),
            "page_start": (
                min(source_pages)
                if source_pages
                else None
            ),
            "page_end": (
                max(source_pages)
                if source_pages
                else None
            ),
            "normalized_heading": (
                normalized_heading
            ),
            "table_number": (
                table_number_match.group(1)
                if table_number_match
                else None
            ),
            "point_count": len(
                table_points
            ),
            "coordinates": tuple(
                (
                    point["utm_y"],
                    point["utm_x"],
                )
                for point in table_points
            ),
            "labels": tuple(
                cls._normalize_table_label(
                    point["label"]
                )
                for point in table_points
            ),
        }

    @classmethod
    def _build_table_identities(
        cls,
        observation_records,
    ):
        identities = {
            record[
                "source_observation_identity"
            ]: cls._make_table_identity(
                "observation="
                + record[
                    "source_observation_identity"
                ]
            )
            for record in observation_records
        }

        candidates = {
            record[
                "source_observation_identity"
            ]: []
            for record in observation_records
        }

        for record_index, record_a in enumerate(
            observation_records
        ):
            for record_b in observation_records[
                record_index + 1:
            ]:
                if not cls._is_confirmed_table_duplicate(
                    record_a,
                    record_b,
                ):
                    continue

                observation_a = record_a[
                    "source_observation_identity"
                ]
                observation_b = record_b[
                    "source_observation_identity"
                ]

                candidates[observation_a].append(
                    observation_b
                )
                candidates[observation_b].append(
                    observation_a
                )

        records_by_identity = {
            record[
                "source_observation_identity"
            ]: record
            for record in observation_records
        }

        for observation_a, matches in candidates.items():
            if len(matches) != 1:
                continue

            observation_b = matches[0]

            if candidates.get(
                observation_b
            ) != [observation_a]:
                continue

            record_a = records_by_identity[
                observation_a
            ]
            record_b = records_by_identity[
                observation_b
            ]

            text_layer_record = (
                record_a
                if record_a["source_method"]
                == "text_layer"
                else record_b
            )

            shared_identity = (
                cls._make_table_identity(
                    "text_layer_observation="
                    + text_layer_record[
                        "source_observation_identity"
                    ]
                )
            )

            identities[observation_a] = (
                shared_identity
            )
            identities[observation_b] = (
                shared_identity
            )

        return identities

    @staticmethod
    def _is_confirmed_table_duplicate(
        record_a,
        record_b,
    ):
        if {
            record_a["source_method"],
            record_b["source_method"],
        } != {
            "text_layer",
            "ocr",
        }:
            return False

        if (
            record_a["page_start"] is None
            or record_a["page_end"] is None
            or record_b["page_start"] is None
            or record_b["page_end"] is None
        ):
            return False

        if (
            record_a["page_start"]
            > record_b["page_end"]
            or record_b["page_start"]
            > record_a["page_end"]
        ):
            return False

        if (
            not record_a["normalized_heading"]
            or record_a["normalized_heading"]
            != record_b["normalized_heading"]
        ):
            return False

        if (
            record_a["point_count"] == 0
            or record_a["point_count"]
            != record_b["point_count"]
        ):
            return False

        if sorted(
            record_a["coordinates"]
        ) != sorted(
            record_b["coordinates"]
        ):
            return False

        if record_a["labels"] != record_b["labels"]:
            return False

        table_number_a = record_a[
            "table_number"
        ]
        table_number_b = record_b[
            "table_number"
        ]

        if (
            table_number_a is not None
            and table_number_b is not None
            and table_number_a != table_number_b
        ):
            return False

        return True

    @staticmethod
    def _normalize_table_label(
        label,
    ):
        return unicodedata.normalize(
            "NFC",
            " ".join(
                str(label).split()
            ),
        ).casefold()

    @staticmethod
    def _make_table_identity(
        canonical_anchor,
    ):
        digest = hashlib.sha256(
            canonical_anchor.encode(
                "utf-8"
            )
        ).hexdigest()

        return "tbl_" + digest

    @classmethod
    def _match_table_line_sources(
        cls,
        text,
        tables,
    ):
        raw_lines = cls._build_raw_line_sources(
            text
        )

        table_sources = []
        cursor = 0

        for table in tables:
            table_lines = [
                line.strip()
                for line in table.splitlines()
                if line.strip()
            ]

            empty_sources = [
                {
                    "source_page": None,
                    "source_method": None,
                }
                for _ in table_lines
            ]

            if not table_lines:
                table_sources.append(
                    empty_sources
                )
                continue

            match_start = None
            last_start = (
                len(raw_lines)
                - len(table_lines)
            )

            for start in range(
                cursor,
                last_start + 1,
            ):
                if all(
                    raw_lines[
                        start + offset
                    ]["text"]
                    == table_line
                    for offset, table_line in enumerate(
                        table_lines
                    )
                ):
                    match_start = start
                    break

            if match_start is None:
                table_sources.append(
                    empty_sources
                )
                continue

            matched_sources = []

            for offset in range(
                len(table_lines)
            ):
                raw_line = raw_lines[
                    match_start + offset
                ]

                matched_sources.append(
                    {
                        "source_page": raw_line[
                            "source_page"
                        ],
                        "source_method": raw_line[
                            "source_method"
                        ],
                    }
                )

            table_sources.append(
                matched_sources
            )

            cursor = (
                match_start
                + len(table_lines)
            )

        return table_sources

    @classmethod
    def _build_raw_line_sources(
        cls,
        text,
    ):
        lines = []
        source_page = None
        source_method = None

        for raw_line in text.splitlines():
            line = raw_line.strip()

            if not line:
                continue

            header_match = (
                cls.PAGE_HEADER_PATTERN.fullmatch(
                    line
                )
            )

            if header_match:
                source = header_match.group(
                    "source"
                )

                source_method = (
                    cls.SOURCE_METHODS.get(
                        source
                    )
                )

                if source_method is None:
                    source_page = None
                else:
                    source_page = int(
                        header_match.group(
                            "page"
                        )
                    )

            lines.append(
                {
                    "text": line,
                    "source_page": source_page,
                    "source_method": source_method,
                }
            )

        return lines

    @staticmethod
    def _detect_section(
        table_text,
    ):
        for line in table_text.splitlines()[:20]:
            upper = line.upper()

            if "PROJEYE KONU ALAN" in upper:
                return line.strip()

            if "RUHSAT SAHASI" in upper:
                return line.strip()

            if "RUHSAT ALANI" in upper:
                return line.strip()

            if (
                "PROJE ALANI KOORDİNATLARI"
                in upper
                or "PROJE ALANI KOORDINATLARI"
                in upper
            ):
                return line.strip()

            if (
                "KOORDİNAT" in upper
                or "KOORDINAT" in upper
            ):
                return line.strip()

        return "Bilinmeyen Alan"

    @staticmethod
    def _section_score(
        section,
    ):
        upper = section.upper()

        if "PROJEYE KONU ALAN" in upper:
            return 100

        if (
            "PROJE ALANI KOORDİNATLARI"
            in upper
            or "PROJE ALANI KOORDINATLARI"
            in upper
        ):
            return 90

        if "RUHSAT SAHASI" in upper:
            return 80

        if "RUHSAT ALANI" in upper:
            return 80

        if (
            "KOORDİNAT" in upper
            or "KOORDINAT" in upper
        ):
            return 60

        return 10

    @classmethod
    def _priority_score(
        cls,
        item,
    ):
        return item["score"]
