import re


class DatumDetector:

    @classmethod
    def detect(cls, table_text: str) -> dict:
        upper = table_text.upper()

        utm_datum = "Bilinmiyor"
        geographic_datum = "Bilinmiyor"
        zone = "Bilinmiyor"
        dom = "Bilinmiyor"
        projection = "Bilinmiyor"

        datum_candidates = []
        if "ED-50" in upper or "ED50" in upper:
            utm_datum = "ED-50"
            datum_candidates.append("ED-50")

        if "WGS-84" in upper or "WGS84" in upper:
            geographic_datum = "WGS-84"

        zone_matches = re.findall(
            r"\bZON(?:E)?\s*[:\-]?\s*(35|36|37|38|39)\b",
            upper
        )
        zone_candidates = list(dict.fromkeys(zone_matches))

        if zone_candidates:
            zone = zone_candidates[0]

        dom_match = re.search(
            r"\bDOM\s*[:\-]?\s*(\d{1,3})\b",
            upper
        )

        if dom_match:
            dom = dom_match.group(1)

        projection_candidates = []
        if (
            "6 DERECE" in upper
            or "6°" in upper
            or "6 DERECELİK" in upper
        ):
            projection = "6 Derece"
            projection_candidates.append("6 Derece")

        if (
            "3 DERECE" in upper
            or "3°" in upper
            or "3 DERECELİK" in upper
        ):
            if not projection_candidates:
                projection = "3 Derece"
            projection_candidates.append("3 Derece")

        conflict_reasons = []
        if len(datum_candidates) > 1:
            conflict_reasons.append(
                "SAME_OBSERVATION_DATUM_CONFLICT"
            )
        if len(zone_candidates) > 1:
            conflict_reasons.append(
                "SAME_OBSERVATION_ZONE_CONFLICT"
            )
        if len(projection_candidates) > 1:
            conflict_reasons.append(
                "SAME_OBSERVATION_PROJECTION_CONFLICT"
            )

        has_utm_compatible_projection = (
            not projection_candidates
            or projection_candidates == ["6 Derece"]
        )

        if conflict_reasons:
            crs_source = "EXPLICIT_TABLE_TEXT"
            crs_confidence = "CONFLICTING"
        elif (
            len(datum_candidates) == 1
            and len(zone_candidates) == 1
            and has_utm_compatible_projection
        ):
            crs_source = "EXPLICIT_TABLE_TEXT"
            crs_confidence = "HIGH"
        else:
            crs_source = "UNRESOLVED"
            crs_confidence = "UNRESOLVED"
            if (
                projection_candidates
                and not has_utm_compatible_projection
            ):
                conflict_reasons.append(
                    "UNSUPPORTED_PROJECTION_CONTEXT"
                )
            if (
                len(datum_candidates) != 1
                or len(zone_candidates) != 1
            ):
                conflict_reasons.append(
                    "MISSING_EXPLICIT_DATUM_OR_ZONE"
                )

        return {
            "utm_datum": utm_datum,
            "geographic_datum": geographic_datum,
            "zone": zone,
            "dom": dom,
            "projection": projection,
            "crs_source": crs_source,
            "crs_confidence": crs_confidence,
            "crs_datum_candidates": datum_candidates,
            "crs_zone_candidates": zone_candidates,
            "crs_projection_candidates": projection_candidates,
            "crs_conflict_reason": "|".join(conflict_reasons),
        }
