from functools import lru_cache


class CRSResolver:
    """Projected UTM metadata'sını güvenli biçimde çözer."""

    DATUM_ALIASES = {
        "ED50": "ED50",
        "WGS84": "WGS84",
    }

    UTM_TYPES = {
        "UTM",
    }

    UTM_PROJECTIONS = {
        "",
        "6DERECE",
        "6DERECELIK",
        "UTM",
    }

    @classmethod
    def resolve_projected_crs(cls, metadata):
        """
        Metadata açıkça desteklenen projected UTM CRS'ini
        tanımlıyorsa ``pyproj.CRS``, aksi halde ``None`` döndürür.

        ``geographic_datum`` PDF'deki coğrafik referans kolonunu
        tanımlayabildiği için projected source datum yerine kullanılmaz.
        """
        if not isinstance(metadata, dict):
            return None

        datum = cls._normalize_text(
            metadata.get("datum")
            or metadata.get("utm_datum")
        )
        datum = cls.DATUM_ALIASES.get(
            datum
        )

        coordinate_type = cls._normalize_text(
            metadata.get("type")
        )

        if (
            datum is None
            or coordinate_type
            not in cls.UTM_TYPES
        ):
            return None

        projection = cls._normalize_text(
            metadata.get("projection")
        )

        if projection in {
            "BILINMIYOR",
            "UNRESOLVED",
            "NONE",
            "UNKNOWN",
        }:
            projection = ""

        if projection not in cls.UTM_PROJECTIONS:
            return None

        zone = cls._parse_zone(
            metadata.get("zone")
        )

        if zone is None:
            return None

        return cls._resolve_utm_crs(
            datum,
            zone,
        )

    @classmethod
    def transform_to_wgs84(
        cls,
        easting,
        northing,
        metadata,
    ):
        """
        Projected source koordinatını WGS84'e dönüştürür.

        eMadenCBS'in mevcut alan anlamı:
            easting  = point["utm_y"] / point["y"]
            northing = point["utm_x"] / point["x"]

        Sonuç ``(longitude, latitude)`` sırasındadır. CRS
        metadata'sı çözülemezse ``None`` döndürülür.
        """
        source_crs = cls.resolve_projected_crs(
            metadata
        )

        if source_crs is None:
            return None

        try:
            easting = float(easting)
            northing = float(northing)
        except (TypeError, ValueError):
            return None

        _, Transformer = cls._load_pyproj()

        transformer = Transformer.from_crs(
            source_crs,
            "EPSG:4326",
            always_xy=True,
        )

        longitude, latitude = transformer.transform(
            easting,
            northing,
        )

        return longitude, latitude

    @classmethod
    @lru_cache(maxsize=128)
    def _resolve_utm_crs(cls, datum, zone):
        CRS, _ = cls._load_pyproj()

        try:
            if datum == "ED50":
                crs = CRS.from_user_input(
                    f"ED50 / UTM zone {zone}N"
                )
            elif datum == "WGS84":
                crs = CRS.from_epsg(
                    32600 + zone
                )
            else:
                return None
        except Exception:
            return None

        if not crs.is_projected:
            return None

        return crs

    @staticmethod
    def _parse_zone(value):
        if isinstance(value, bool):
            return None

        try:
            zone = int(str(value).strip())
        except (TypeError, ValueError):
            return None

        if not 1 <= zone <= 60:
            return None

        return zone

    @staticmethod
    def _normalize_text(value):
        if value is None:
            return ""

        return (
            str(value)
            .upper()
            .replace("-", "")
            .replace("_", "")
            .replace(" ", "")
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

    @staticmethod
    def _load_pyproj():
        try:
            from pyproj import CRS, Transformer
        except ImportError as exc:
            raise RuntimeError(
                "CRS resolution requires pyproj. "
                "Install project dependencies with: "
                "python -m pip install -r requirements.txt"
            ) from exc

        return CRS, Transformer
