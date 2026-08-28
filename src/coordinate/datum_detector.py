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

        if "ED-50" in upper or "ED50" in upper:
            utm_datum = "ED-50"

        if "WGS-84" in upper or "WGS84" in upper:
            geographic_datum = "WGS-84"

        zone_match = re.search(
            r"\bZON(?:E)?\s*[:\-]?\s*(35|36|37|38|39)\b",
            upper
        )

        if zone_match:
            zone = zone_match.group(1)

        dom_match = re.search(
            r"\bDOM\s*[:\-]?\s*(\d{1,3})\b",
            upper
        )

        if dom_match:
            dom = dom_match.group(1)

        if (
            "6 DERECE" in upper
            or "6°" in upper
            or "6 DERECELİK" in upper
        ):
            projection = "6 Derece"

        elif (
            "3 DERECE" in upper
            or "3°" in upper
            or "3 DERECELİK" in upper
        ):
            projection = "3 Derece"

        return {
            "utm_datum": utm_datum,
            "geographic_datum": geographic_datum,
            "zone": zone,
            "dom": dom,
            "projection": projection,
        }
