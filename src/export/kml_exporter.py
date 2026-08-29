import html
import math
import xml.etree.ElementTree as ET


class KMLExporter:

    KML_NAMESPACE = "http://www.opengis.net/kml/2.2"

    POLYGON_COLORS = {
        # Ana proje alanları
        "RUHSAT_ALANI": "7f0000ff",
        "CED_ALANI": "7f00ffff",
        "MEVCUT_CED_ALANI": "7f00ff00",
        "YENI_CED_ALANI": "7f00a5ff",
        "PROJE_ALANI": "7fff0000",
        "ISLETME_IZIN_ALANI": "7fff00ff",

        # Madencilik / yardımcı alanlar
        "OCAK_ALANI": "7f0080ff",
        "GALERI_ALANI": "7f800080",
        "SANTIYE_ALANI": "7f808080",
        "BITKISEL_TOPRAK_ALANI": "7f00ff80",
        "PASA_ALANI": "7f404080",
        "STOK_ALANI": "7f80ffff",
        "KIRMA_ELEME_ALANI": "7f008080",
        "CEVHER_HAZIRLAMA_ALANI": "7fff8080",
        "ATIK_ALANI": "7f8000ff",
        "HAVUZ_ALANI": "7fffff00",

        # Mevcut diğer sınıflar
        "TESIS_ALANI": "7f8080ff",
        "DEPOLAMA_ALANI": "7f80ff80",
        "CALISILMAYACAK_ALAN": "7f404040",

        # Tanımlanamayan alan
        "DIGER": "7fc0c0c0",
    }

    @classmethod
    def export(
        cls,
        project_model,
        file_path,
    ):
        ET.register_namespace(
            "",
            cls.KML_NAMESPACE,
        )

        kml = ET.Element(
            cls._tag("kml")
        )

        document = ET.SubElement(
            kml,
            cls._tag("Document"),
        )

        document_name = ET.SubElement(
            document,
            cls._tag("name"),
        )
        document_name.text = cls._document_name(
            project_model
        )

        cls._add_styles(
            document
        )

        cls._add_polygons(
            document,
            project_model,
        )

        tree = ET.ElementTree(kml)

        ET.indent(
            tree,
            space="  ",
        )

        tree.write(
            file_path,
            encoding="utf-8",
            xml_declaration=True,
        )

    @classmethod
    def _add_styles(cls, document):
        layer_types = list(
            cls.POLYGON_COLORS.keys()
        )

        for layer_type in layer_types:
            color = cls.POLYGON_COLORS.get(
                layer_type,
                cls.POLYGON_COLORS["DIGER"],
            )

            style = ET.SubElement(
                document,
                cls._tag("Style"),
                id=f"style_{layer_type}",
            )

            line_style = ET.SubElement(
                style,
                cls._tag("LineStyle"),
            )

            line_color = ET.SubElement(
                line_style,
                cls._tag("color"),
            )
            line_color.text = color

            line_width = ET.SubElement(
                line_style,
                cls._tag("width"),
            )
            line_width.text = "4"

            poly_style = ET.SubElement(
                style,
                cls._tag("PolyStyle"),
            )

            poly_color = ET.SubElement(
                poly_style,
                cls._tag("color"),
            )
            poly_color.text = color

    @classmethod
    def _add_project_info(
        cls,
        document,
        project_model,
    ):
        project_info = getattr(
            project_model,
            "project_info",
            {},
        )

        folder = ET.SubElement(
            document,
            cls._tag("Folder"),
        )

        folder_name = ET.SubElement(
            folder,
            cls._tag("name"),
        )
        folder_name.text = "Proje Bilgileri"

        placemark = ET.SubElement(
            folder,
            cls._tag("Placemark"),
        )

        placemark_name = ET.SubElement(
            placemark,
            cls._tag("name"),
        )
        placemark_name.text = cls._document_name(
            project_model
        )

        description = ET.SubElement(
            placemark,
            cls._tag("description"),
        )

        description.text = cls._project_description(
            project_info
        )

    @classmethod
    def _add_polygons(
        cls,
        document,
        project_model,
    ):
        polygons = getattr(
            project_model,
            "polygons",
            [],
        )

        # -------------------------------------------------
        # POLİGONLARI TÜRLERİNE GÖRE GRUPLA
        # -------------------------------------------------

        grouped_polygons = {}

        for polygon in polygons:
            table_type = polygon.get(
                "table_type",
                "DIGER",
            )

            if table_type not in grouped_polygons:
                grouped_polygons[table_type] = []

            grouped_polygons[table_type].append(
                polygon
            )

        # -------------------------------------------------
        # HER ALAN TÜRÜ İÇİN TEK ANA KLASÖR
        # -------------------------------------------------

        for table_type, type_polygons in (
            grouped_polygons.items()
        ):
            folder = ET.SubElement(
                document,
                cls._tag("Folder"),
            )

            folder_name = ET.SubElement(
                folder,
                cls._tag("name"),
            )

            folder_name.text = (
                cls._display_table_type(
                    table_type
                )
            )

            # ---------------------------------------------
            # AYNI TÜRDEKİ ALT POLİGONLAR
            # ---------------------------------------------

            for polygon_index, polygon in enumerate(
                type_polygons,
                start=1,
            ):
                coordinate_text = (
                    cls._build_coordinate_text(
                        polygon
                    )
                )

                if not coordinate_text:
                    continue

                placemark = ET.SubElement(
                    folder,
                    cls._tag("Placemark"),
                )

                placemark_name = ET.SubElement(
                    placemark,
                    cls._tag("name"),
                )

                polygon_group = polygon.get(
                    "polygon_group",
                    "DEFAULT",
                )

                placemark_name.text = (
                    cls._polygon_display_name(
                        table_type,
                        polygon_group,
                        polygon_index,
                    )
                )

                style_url = ET.SubElement(
                    placemark,
                    cls._tag("styleUrl"),
                )

                style_url.text = (
                    f"#style_{table_type}"
                    if table_type
                    in cls.POLYGON_COLORS
                    else "#style_DIGER"
                )

                description = ET.SubElement(
                    placemark,
                    cls._tag("description"),
                )

                description.text = (
                    cls._polygon_description(
                        project_model,
                        polygon,
                        polygon_index,
                    )
                )

                polygon_element = ET.SubElement(
                    placemark,
                    cls._tag("Polygon"),
                )

                tessellate = ET.SubElement(
                    polygon_element,
                    cls._tag("tessellate"),
                )

                tessellate.text = "1"

                outer_boundary = ET.SubElement(
                    polygon_element,
                    cls._tag("outerBoundaryIs"),
                )

                linear_ring = ET.SubElement(
                    outer_boundary,
                    cls._tag("LinearRing"),
                )

                coordinates_element = ET.SubElement(
                    linear_ring,
                    cls._tag("coordinates"),
                )

                coordinates_element.text = (
                    coordinate_text
                )

    @staticmethod
    def _display_table_type(
        table_type,
    ):
        names = {
            "RUHSAT_ALANI": "Ruhsat Alanı",
            "CED_ALANI": "ÇED Alanı",
            "MEVCUT_CED_ALANI": "Mevcut ÇED Alanı",
            "YENI_CED_ALANI": "Yeni ÇED Alanı",
            "PROJE_ALANI": "Proje Alanı",
            "ISLETME_IZIN_ALANI": "İşletme İzin Alanı",
            "TESIS_ALANI": "Tesis Alanı",
            "DEPOLAMA_ALANI": "Depolama Alanı",
            "GALERI_ALANI": "Galeri Alanı",
            "CALISILMAYACAK_ALAN": "Çalışılmayacak Alan",
            "SANTIYE_ALANI": "Şantiye Alanı",
            "BITKISEL_TOPRAK_ALANI": (
                "Bitkisel Toprak Alanı"
            ),
            "PASA_ALANI": "Pasa Alanı",
            "STOK_ALANI": "Stok Alanı",
            "OCAK_ALANI": "Ocak Alanı",
            "KIRMA_ELEME_ALANI": (
                "Kırma Eleme Alanı"
            ),
            "CEVHER_HAZIRLAMA_ALANI": (
                "Cevher Hazırlama Alanı"
            ),
            "ATIK_ALANI": "Atık Alanı",
            "HAVUZ_ALANI": "Havuz Alanı",
            "DIGER": "Diğer Alanlar",
        }

        return names.get(
            table_type,
            table_type.replace(
                "_",
                " ",
            ).title(),
        )

    @classmethod
    def _polygon_display_name(
        cls,
        table_type,
        polygon_group,
        polygon_index,
    ):
        base_name = cls._display_table_type(
            table_type
        )

        number = polygon_index

        if (
            polygon_group
            and polygon_group != "DEFAULT"
        ):
            clean_group = (
                str(polygon_group)
                .replace("LABEL_", "")
                .replace("POLIGON_", "")
                .replace("_", " ")
                .strip()
            )

            parts = clean_group.split()

            if (
                parts
                and parts[-1].isdigit()
            ):
                number = int(
                    parts[-1]
                )

        # Tek ruhsat için numara göstermeye gerek yok.
        if table_type == "RUHSAT_ALANI":
            return "Ruhsat Alanı"

        names = {
            "CED_ALANI": "ÇED",
            "MEVCUT_CED_ALANI": "Mevcut ÇED",
            "YENI_CED_ALANI": "Yeni ÇED",
            "PROJE_ALANI": "Proje Alanı",
            "ISLETME_IZIN_ALANI": "İşletme İzin Alanı",
            "OCAK_ALANI": "Ocak Alanı",
            "GALERI_ALANI": "Galeri Alanı",
            "SANTIYE_ALANI": "Şantiye Alanı",
            "BITKISEL_TOPRAK_ALANI": "Bitkisel Toprak Alanı",
            "PASA_ALANI": "Pasa Alanı",
            "STOK_ALANI": "Stok Alanı",
            "KIRMA_ELEME_ALANI": "Kırma Eleme Alanı",
            "CEVHER_HAZIRLAMA_ALANI": "Cevher Hazırlama Alanı",
            "ATIK_ALANI": "Atık Alanı",
            "HAVUZ_ALANI": "Havuz Alanı",
            "TESIS_ALANI": "Tesis Alanı",
            "DEPOLAMA_ALANI": "Depolama Alanı",
            "CALISILMAYACAK_ALAN": "Çalışılmayacak Alan",
            "DIGER": "Diğer Alan",
        }

        display_name = names.get(
            table_type,
            base_name,
        )

        return (
            f"{display_name} {number}"
        )
    @classmethod
    def _build_coordinate_text(
        cls,
        polygon,
    ):
        coordinate_lines = []

        points = polygon.get(
            "points",
            [],
        )

        transformed_points = (
            cls._coordinate_pairs(
                points,
                "transformed_longitude",
                "transformed_latitude",
            )
        )

        if transformed_points is not None:
            valid_points = transformed_points
        else:
            valid_points = cls._coordinate_pairs(
                points,
                "longitude",
                "latitude",
            )

        if not valid_points:
            return ""

        for longitude, latitude in valid_points:
            coordinate_lines.append(
                f"{longitude},{latitude},0"
            )

        first_longitude, first_latitude = (
            valid_points[0]
        )

        last_longitude, last_latitude = (
            valid_points[-1]
        )

        if (
            first_longitude != last_longitude
            or first_latitude != last_latitude
        ):
            coordinate_lines.append(
                f"{first_longitude},"
                f"{first_latitude},0"
            )

        return "\n".join(
            coordinate_lines
        )

    @staticmethod
    def _coordinate_pairs(
        points,
        longitude_field,
        latitude_field,
    ):
        coordinate_pairs = []

        for point in points:
            longitude = point.get(
                longitude_field
            )
            latitude = point.get(
                latitude_field
            )

            if longitude in (None, "") or latitude in (
                None,
                "",
            ):
                return None

            try:
                coordinate_pair = (
                    float(longitude),
                    float(latitude),
                )
            except (TypeError, ValueError):
                return None

            if not all(
                math.isfinite(value)
                for value in coordinate_pair
            ):
                return None

            coordinate_pairs.append(
                coordinate_pair
            )

        return coordinate_pairs or None

    @classmethod
    def _project_description(
        cls,
        project_info,
    ):
        rows = [
            (
                "Proje Sahibi Ünvanı",
                project_info.get(
                    "company",
                    "Bilinmiyor",
                ),
            ),
            (
                "Maden Cinsi",
                project_info.get(
                    "mine_type",
                    "Bilinmiyor",
                ),
            ),
            (
                "Ruhsat No",
                project_info.get(
                    "license_no",
                    "Bilinmiyor",
                ),
            ),
            (
                "İl",
                project_info.get(
                    "province",
                    "Bilinmiyor",
                ),
            ),
            (
                "İlçe",
                project_info.get(
                    "district",
                    "Bilinmiyor",
                ),
            ),
        ]

        return cls._html_table(
            rows
        )
    @classmethod
    def _polygon_description(
        cls,
        project_model,
        polygon,
        polygon_index,
    ):
        project_info = getattr(
            project_model,
            "project_info",
            {},
        )

        table_type = polygon.get(
            "table_type",
            "DIGER",
        )

        polygon_group = polygon.get(
            "polygon_group",
            "DEFAULT",
        )

        folder_name = cls._display_table_type(
            table_type
        )

        polygon_name = cls._polygon_display_name(
            table_type,
            polygon_group,
            polygon_index,
        )

        rows = [
            (
                "Klasör",
                folder_name,
            ),
            (
                "Poligon",
                polygon_name,
            ),
            (
                "Alan",
                (
                    f"{polygon.get('area_ha', 0):,.4f}"
                    " ha"
                ),
            ),
        ]

        # -------------------------------------------------
        # SADECE RUHSAT ALANINDA
        # RUHSAT / PROJE BİLGİLERİNİ GÖSTER
        # -------------------------------------------------

        if table_type == "RUHSAT_ALANI":
            rows.extend(
                [
                    (
                        "İl",
                        project_info.get(
                            "province",
                            "Bilinmiyor",
                        ),
                    ),
                    (
                        "İlçe",
                        project_info.get(
                            "district",
                            "Bilinmiyor",
                        ),
                    ),
                    (
                        "Sicil / Ruhsat No",
                        project_info.get(
                            "license_no",
                            "Bilinmiyor",
                        ),
                    ),
                    (
                        "Firma Ünvanı",
                        project_info.get(
                            "company",
                            "Bilinmiyor",
                        ),
                    ),
                    (
                        "Maden Cinsi",
                        project_info.get(
                            "mine_type",
                            "Bilinmiyor",
                        ),
                    ),
                ]
            )

        return cls._html_table(
            rows
        )

    @classmethod
    def _html_table(
        cls,
        rows,
    ):
        html_rows = []

        for title, value in rows:
            safe_title = html.escape(
                str(title)
            )

            safe_value = html.escape(
                str(value)
            )

            html_rows.append(
                "<tr>"
                f"<td><b>{safe_title}</b></td>"
                f"<td>{safe_value}</td>"
                "</tr>"
            )

        return (
            "<table border='1' "
            "cellpadding='4' "
            "cellspacing='0'>"
            + "".join(html_rows)
            + "</table>"
        )

    @classmethod
    def _document_name(
        cls,
        project_model,
    ):
        project_info = getattr(
            project_model,
            "project_info",
            {},
        )

        company = project_info.get(
            "company",
            "eMadenCBS Projesi",
        )

        license_no = project_info.get(
            "license_no",
            "",
        )

        name_parts = []

        if company and company != "Bilinmiyor":
            name_parts.append(company)

        if license_no and license_no != "Bilinmiyor":
            name_parts.append(license_no)

        if not name_parts:
            return "eMadenCBS Projesi"

    @classmethod
    def _tag(
        cls,
        name,
    ):
        return (
            f"{{{cls.KML_NAMESPACE}}}"
            f"{name}"
        )
