from src.coordinate.table_classifier import TableClassifier
from src.coordinate.datum_detector import DatumDetector
from src.coordinate.state_machine import parse_coordinate_blocks
from src.coordinate.table_detector import TableDetector


class CoordinateEngine:

    @classmethod
    def extract_coordinates(cls, text):
        tables = TableDetector.find_tables(
            text
        )

        if not tables:
            return []

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
                table
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
        }

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