from collections import OrderedDict

from src.coordinate.ring_geometry import (
    repair_self_intersecting_rings,
)


class PolygonBuilder:

    @classmethod
    def build(cls, coordinates):
        grouped = OrderedDict()

        for item in coordinates:
            polygon_group = item.get(
                "polygon_group",
                "DEFAULT",
            )

            group_key = (
                item.get(
                    "table_type",
                    "DIGER",
                ),
                item.get(
                    "section",
                    "Bilinmeyen Alan",
                ),
                item.get(
                    "table_index",
                    0,
                ),
                polygon_group,
            )

            if group_key not in grouped:
                grouped[group_key] = {
                    "table_type": item.get(
                        "table_type",
                        "DIGER",
                    ),
                    "section": item.get(
                        "section",
                        "Bilinmeyen Alan",
                    ),
                    "table_index": item.get(
                        "table_index",
                        0,
                    ),
                    "polygon_group": polygon_group,
                    "polygon_heading": item.get(
                        "polygon_heading",
                        "",
                    ),
                    "datum": item.get(
                        "datum",
                        "Bilinmiyor",
                    ),
                    "geographic_datum": item.get(
                        "geographic_datum",
                        "Bilinmiyor",
                    ),
                    "zone": item.get(
                        "zone",
                        "Bilinmiyor",
                    ),
                    "dom": item.get(
                        "dom",
                        "Bilinmiyor",
                    ),
                    "projection": item.get(
                        "projection",
                        "Bilinmiyor",
                    ),
                    "projected_crs_epsg": item.get(
                        "projected_crs_epsg"
                    ),
                    "projected_crs_name": item.get(
                        "projected_crs_name"
                    ),
                    "crs_source": item.get(
                        "crs_source",
                        "UNRESOLVED",
                    ),
                    "crs_confidence": item.get(
                        "crs_confidence",
                        "UNRESOLVED",
                    ),
                    "crs_conflict": item.get(
                        "crs_conflict",
                        False,
                    ),
                    "crs_conflicting_epsg": list(
                        item.get(
                            "crs_conflicting_epsg",
                            [],
                        )
                    ),
                    "points": [],
                }

            grouped[group_key]["points"].append(
                {
                    "name": item["name"],
                    "y": item["y"],
                    "x": item["x"],
                    "latitude": item.get(
                        "latitude"
                    ),
                    "longitude": item.get(
                        "longitude"
                    ),
                    "projected_crs_epsg": item.get(
                        "projected_crs_epsg"
                    ),
                    "projected_crs_name": item.get(
                        "projected_crs_name"
                    ),
                    "crs_source": item.get(
                        "crs_source",
                        "UNRESOLVED",
                    ),
                    "crs_confidence": item.get(
                        "crs_confidence",
                        "UNRESOLVED",
                    ),
                    "crs_conflict": item.get(
                        "crs_conflict",
                        False,
                    ),
                    "crs_conflicting_epsg": list(
                        item.get(
                            "crs_conflicting_epsg",
                            [],
                        )
                    ),
                    "crs_zone_candidates": list(
                        item.get(
                            "crs_zone_candidates",
                            [],
                        )
                    ),
                    "crs_datum_candidates": list(
                        item.get(
                            "crs_datum_candidates",
                            [],
                        )
                    ),
                    "crs_conflict_reason": item.get(
                        "crs_conflict_reason",
                        "",
                    ),
                    "transformed_longitude": item.get(
                        "transformed_longitude"
                    ),
                    "transformed_latitude": item.get(
                        "transformed_latitude"
                    ),
                }
            )

        polygons = []
        seen_geometries = set()

        for group in grouped.values():
            rings = repair_self_intersecting_rings(
                group["points"]
            )

            if not rings:
                rings = [group["points"]]

            for points in rings:
                if len(points) < 3:
                    continue

                ring_group = dict(group)
                ring_group["points"] = points

                cls._summarize_crs_metadata(
                    ring_group
                )

                geometry_key = (
                    ring_group.get(
                        "table_type",
                        "DIGER",
                    ),
                    cls._geometry_key(
                        points
                    ),
                )

                if geometry_key in seen_geometries:
                    continue

                seen_geometries.add(
                    geometry_key
                )

                area = cls._calculate_area(
                    points
                )

                polygon = {
                    **ring_group,
                    "point_count": len(points),
                    "is_closed": cls._is_closed(
                        points
                    ),
                    "area_m2": round(
                        area,
                        2,
                    ),
                    "area_ha": round(
                        area / 10000,
                        4,
                    ),
                }

                polygons.append(
                    polygon
                )

        polygons = cls._remove_subset_polygons(
            polygons
        )

        return polygons

    @staticmethod
    def _summarize_crs_metadata(group):
        points = group.get("points", [])
        resolved_epsg = sorted(
            {
                point.get("projected_crs_epsg")
                for point in points
                if isinstance(
                    point.get("projected_crs_epsg"),
                    int,
                )
            }
        )
        conflicting_epsg = sorted(
            {
                epsg
                for point in points
                for epsg in point.get(
                    "crs_conflicting_epsg",
                    [],
                )
                if isinstance(epsg, int)
            }
        )
        has_cross_or_point_conflict = (
            any(
                point.get("crs_conflict") is True
                for point in points
            )
            or len(resolved_epsg) > 1
        )
        confidences = {
            point.get(
                "crs_confidence",
                "UNRESOLVED",
            )
            for point in points
        }

        group["crs_conflict"] = has_cross_or_point_conflict
        group["crs_conflicting_epsg"] = (
            conflicting_epsg
            if conflicting_epsg
            else resolved_epsg
            if has_cross_or_point_conflict
            else []
        )
        if (
            "CONFLICTING" in confidences
            or len(resolved_epsg) > 1
        ):
            group["crs_confidence"] = "CONFLICTING"
        elif confidences == {"HIGH"}:
            group["crs_confidence"] = "HIGH"
        else:
            group["crs_confidence"] = "UNRESOLVED"

    @classmethod
    def _remove_subset_polygons(
        cls,
        polygons,
    ):
        """
        Aynı alan türündeki eksik veya mükerrer
        polygonları temizler.
        """
        result = []

        for polygon in polygons:
            polygon_type = polygon.get(
                "table_type",
                "DIGER",
            )

            polygon_points = polygon.get(
                "points",
                [],
            )

            skip_polygon = False

            # ---------------------------------------------
            # DAHA ÖNCE TUTULAN POLYGONLARLA KARŞILAŞTIR
            # ---------------------------------------------

            for kept_polygon in result:
                if (
                    kept_polygon.get(
                        "table_type",
                        "DIGER",
                    )
                    != polygon_type
                ):
                    continue

                kept_points = kept_polygon.get(
                    "points",
                    [],
                )

                # -----------------------------------------
                # AYNI GEOMETRİNİN KÜÇÜK SAYISAL
                # FARKLARLA TEKRARI
                # -----------------------------------------

                if cls._geometries_match(
                    polygon_points,
                    kept_points,
                    tolerance=1.0,
                ):
                    skip_polygon = True
                    break

            if skip_polygon:
                continue

            # ---------------------------------------------
            # EKSİK / ALT KÜME POLYGON KONTROLÜ
            # ---------------------------------------------

            polygon_key = set(
                cls._geometry_key(
                    polygon_points
                )
            )

            is_subset = False

            for other in polygons:
                if other is polygon:
                    continue

                if (
                    other.get(
                        "table_type",
                        "DIGER",
                    )
                    != polygon_type
                ):
                    continue

                other_key = set(
                    cls._geometry_key(
                        other.get(
                            "points",
                            [],
                        )
                    )
                )

                if (
                    len(other_key)
                    <= len(polygon_key)
                ):
                    continue

                if polygon_key.issubset(
                    other_key
                ):
                    is_subset = True
                    break

            if is_subset:
                continue

            result.append(
                polygon
            )

        return result
    @staticmethod
    def _geometries_match(
        points_a,
        points_b,
        tolerance=1.0,
    ):
        """
        Aynı polygonun küçük koordinat farklarıyla
        tekrar edilip edilmediğini kontrol eder.

        Nokta sırası önemli değildir.
        """

        if len(points_a) != len(points_b):
            return False

        if len(points_a) < 3:
            return False

        unmatched = list(
            points_b
        )

        for point_a in points_a:
            match_index = None

            y_a = float(
                point_a["y"]
            )

            x_a = float(
                point_a["x"]
            )

            for index, point_b in enumerate(
                unmatched
            ):
                y_b = float(
                    point_b["y"]
                )

                x_b = float(
                    point_b["x"]
                )

                distance_squared = (
                    (y_a - y_b) ** 2
                    + (x_a - x_b) ** 2
                )

                if (
                    distance_squared
                    <= tolerance ** 2
                ):
                    match_index = index
                    break

            if match_index is None:
                return False

            unmatched.pop(
                match_index
            )

        return True
    @staticmethod
    def _geometry_key(points):
        """
        Aynı geometri farklı tablo veya rapor bölümünde
        tekrar geçse bile tek polygon olarak kabul edilir.

        Başlangıç noktası veya yön farklı olsa bile
        aynı koordinat kümesini aynı geometri sayar.
        """

        normalized_points = []

        for point in points:
            y = round(
                float(point["y"]),
                3,
            )

            x = round(
                float(point["x"]),
                3,
            )

            normalized_points.append(
                (
                    y,
                    x,
                )
            )

        unique_points = set(
            normalized_points
        )

        return tuple(
            sorted(
                unique_points
            )
        )

    @staticmethod
    def _is_closed(points):
        if len(points) < 3:
            return False

        first = points[0]
        last = points[-1]

        return (
            first["y"] == last["y"]
            and first["x"] == last["x"]
        )

    @staticmethod
    def _calculate_area(points):
        """
        Shoelace yöntemi ile UTM koordinatlarından
        gerçek alanı (m²) hesaplar.
        """

        if len(points) < 3:
            return 0

        area = 0

        for i in range(len(points)):
            j = (i + 1) % len(points)

            area += (
                points[i]["y"]
                * points[j]["x"]
            )

            area -= (
                points[j]["y"]
                * points[i]["x"]
            )

        return abs(area) / 2
