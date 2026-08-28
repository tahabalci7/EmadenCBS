import re

from src.coordinate.table_classifier import TableClassifier
from src.coordinate.datum_detector import DatumDetector
from src.coordinate.state_machine import parse_coordinate_blocks
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
    def extract_coordinates(cls, text):
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

        results = []
        seen = set()

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

            table_points = parse_coordinate_blocks(
                table,
                line_sources=(
                    table_line_sources[
                        table_index - 1
                    ]
                ),
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

                results.append(
                    cls._make_result(
                        point=point,
                        table_index=table_index,
                        section=section,
                        table_type=point_table_type,
                        datum_info=datum_info,
                    )
                )

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
        }

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
