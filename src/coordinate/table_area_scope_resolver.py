import re
import unicodedata
from decimal import Decimal, InvalidOperation

from src.coordinate.table_area_scope_extractor import (
    TableAreaScopeExtractor,
)
from src.coordinate.table_layout_extractor import TableLayoutExtractor


class TableAreaScopeResolver:
    """Apply unambiguous native table area scopes to parsed points."""

    _ENCODED_DIGITS = str.maketrans(
        {
            chr(0x03EC + digit): str(digit)
            for digit in range(10)
        }
    )
    _NUMBER_PATTERN = re.compile(
        r"[+-]?\d+(?:[.,]\d+)?"
    )

    @classmethod
    def apply_pdf(cls, pdf_path, points):
        """Mutate matched point table types in place and return diagnostics."""

        diagnostics = cls._empty_diagnostics()
        pages = sorted(
            {
                point.get("source_page")
                for point in points
                if cls._valid_page_number(
                    point.get("source_page")
                )
            }
        )

        for page_number in pages:
            try:
                layout_metadata = TableLayoutExtractor.extract_page(
                    pdf_path,
                    page_number,
                )
                scope_metadata = TableAreaScopeExtractor.extract(
                    layout_metadata
                )

                page_diagnostics = cls.resolve(
                    layout_metadata=layout_metadata,
                    scope_metadata=scope_metadata,
                    points=points,
                )
            except Exception:
                continue

            diagnostics["pages_processed"] += 1
            diagnostics["scope_count"] += len(
                scope_metadata["area_scopes"]
            )

            for key in (
                "matched",
                "overridden",
                "ambiguous",
                "unmatched",
            ):
                diagnostics[key] += page_diagnostics[key]

            diagnostics["matches"].extend(
                page_diagnostics["matches"]
            )

        return diagnostics

    @classmethod
    def resolve(
        cls,
        layout_metadata,
        scope_metadata,
        points,
    ):
        """Mutate only unambiguous point table types for one page."""

        diagnostics = cls._empty_diagnostics()
        page_number = layout_metadata.get("page_number")
        scopes = scope_metadata.get("area_scopes", []) or []

        if not scopes:
            return diagnostics

        tables_by_index = {
            table.get("table_index"): table
            for table in layout_metadata.get("tables", []) or []
        }
        coordinate_matches = {}
        candidates_by_row = {}
        pending_overrides = []

        for table_index, table in tables_by_index.items():
            for row in table.get("rows", []) or []:
                row_match = cls._extract_row_match(row)

                if row_match is None:
                    continue

                candidate = {
                    "area_types": set(),
                    "table_index": table_index,
                    "row_index": row.get("row_index"),
                    "label_signals": row_match["label_signals"],
                }

                coordinate_matches.setdefault(
                    row_match["coordinate_key"],
                    [],
                ).append(candidate)
                candidates_by_row[
                    (
                        table_index,
                        row.get("row_index"),
                    )
                ] = candidate

        for scope in scopes:
            if scope.get("page_number") != page_number:
                continue

            area_type = scope.get("area_type")

            if not area_type:
                continue

            table = tables_by_index.get(
                scope.get("table_index")
            )

            if table is None:
                continue

            for row_index in scope.get(
                "covered_row_indexes",
                [],
            ):
                candidate = candidates_by_row.get(
                    (
                        scope.get("table_index"),
                        row_index,
                    )
                )

                if candidate is not None:
                    candidate["area_types"].add(
                        area_type
                    )

        for point in points:
            if point.get("source_page") != page_number:
                continue

            coordinate_key = cls._point_coordinate_key(point)

            if coordinate_key is None:
                diagnostics["unmatched"] += 1
                continue

            candidates = coordinate_matches.get(
                coordinate_key,
                [],
            )
            match, match_status = cls._select_match(
                candidates,
                point.get("name") or point.get("text"),
            )

            if match is None:
                if match_status == "ambiguous":
                    diagnostics["ambiguous"] += 1
                else:
                    diagnostics["unmatched"] += 1
                continue

            diagnostics["matched"] += 1
            old_area_type = point.get("table_type")
            new_area_type = next(
                iter(match["area_types"])
            )

            if old_area_type != new_area_type:
                pending_overrides.append(
                    (
                        point,
                        new_area_type,
                    )
                )
                diagnostics["overridden"] += 1

            diagnostics["matches"].append(
                {
                    "source_page": page_number,
                    "coordinate_pair": [
                        point.get("y"),
                        point.get("x"),
                    ],
                    "label": point.get("name") or point.get("text"),
                    "table_index": match["table_index"],
                    "row_index": match["row_index"],
                    "old_area_type": old_area_type,
                    "area_type": new_area_type,
                }
            )

        for point, area_type in pending_overrides:
            point["table_type"] = area_type

        return diagnostics

    @classmethod
    def _extract_row_match(cls, row):
        if not row:
            return None

        values = []
        label_signals = set()

        for cell_text in row.get("cell_texts", []) or []:
            raw_text = str(cell_text)
            label_signals.update(
                cls._label_signals(raw_text)
            )
            values.extend(
                cls._numeric_values(raw_text)
            )

        projected_pairs = []

        for index, easting in enumerate(values):
            if not Decimal("100000") <= easting <= Decimal("999999"):
                continue

            for northing in values[index + 1:]:
                if Decimal("3000000") <= northing <= Decimal("5000000"):
                    projected_pairs.append(
                        (
                            easting.normalize(),
                            northing.normalize(),
                        )
                    )

        projected_pairs = list(dict.fromkeys(projected_pairs))

        if len(projected_pairs) != 1:
            return None

        return {
            "coordinate_key": projected_pairs[0],
            "label_signals": label_signals,
        }

    @classmethod
    def _numeric_values(cls, raw_text):
        values = []

        for token in cls._NUMBER_PATTERN.findall(raw_text):
            value = cls._to_decimal(token)

            if value is not None:
                values.append(value)

        encoded_characters = set(
            chr(codepoint)
            for codepoint in cls._ENCODED_DIGITS
        )

        for token in str(raw_text).split():
            candidate = token.strip("()[]{};:|")

            if not any(
                character in encoded_characters
                for character in candidate
            ):
                continue

            if not all(
                character in encoded_characters
                or character in "+-.,"
                for character in candidate
            ):
                continue

            decoded = candidate.translate(
                cls._ENCODED_DIGITS
            )

            if cls._NUMBER_PATTERN.fullmatch(decoded) is None:
                continue

            value = cls._to_decimal(decoded)

            if value is None:
                continue

            if (
                Decimal("100000") <= value <= Decimal("999999")
                or Decimal("3000000") <= value <= Decimal("5000000")
            ):
                values.append(value)

        return values

    @staticmethod
    def _to_decimal(token):
        try:
            return Decimal(
                token.replace(",", ".")
            )
        except InvalidOperation:
            return None

    @classmethod
    def _point_coordinate_key(cls, point):
        try:
            return (
                Decimal(str(point.get("y"))).normalize(),
                Decimal(str(point.get("x"))).normalize(),
            )
        except InvalidOperation:
            return None

    @classmethod
    def _select_match(cls, candidates, point_label):
        if not candidates:
            return None, "unmatched"

        if len(candidates) == 1:
            candidate = candidates[0]

            if len(candidate["area_types"]) == 1:
                return candidate, "matched"

            return None, "unmatched"

        point_label_signals = cls._label_signals(point_label)

        if not point_label_signals:
            return None, "ambiguous"

        label_matches = [
            candidate
            for candidate in candidates
            if candidate["label_signals"] & point_label_signals
        ]

        if len(label_matches) == 1:
            candidate = label_matches[0]

            if len(candidate["area_types"]) == 1:
                return candidate, "matched"

            return None, "unmatched"

        return None, "ambiguous"

    @staticmethod
    def _label_signals(value):
        signals = set()
        current = []

        for character in str(value or "").upper():
            is_latin_letter = (
                character.isalpha()
                and "LATIN" in unicodedata.name(
                    character,
                    "",
                )
            )

            if is_latin_letter:
                current.append(character)
            elif current:
                signals.add("".join(current))
                current = []

        if current:
            signals.add("".join(current))

        return signals

    @staticmethod
    def _valid_page_number(value):
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        )

    @staticmethod
    def _empty_diagnostics():
        return {
            "pages_processed": 0,
            "scope_count": 0,
            "matched": 0,
            "overridden": 0,
            "ambiguous": 0,
            "unmatched": 0,
            "matches": [],
        }
