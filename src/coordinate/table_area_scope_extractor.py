from src.coordinate.state_machine import detect_area_type


class TableAreaScopeExtractor:
    """Derive area scopes from native PDF table cell geometry."""

    @classmethod
    def extract(cls, layout_metadata):
        """Return recognized area scopes without changing parser state."""

        page_number = layout_metadata.get("page_number")
        scopes = []

        for table in layout_metadata.get("tables", []) or []:
            table_index = table.get("table_index")

            for cell in table.get("cells", []) or []:
                covered_row_indexes = list(
                    cell.get("covered_row_indexes", []) or []
                )

                if len(covered_row_indexes) < 2:
                    continue

                cell_text = (
                    cell.get("text_normalized")
                    or cell.get("text")
                    or ""
                )
                area_type = cls._detect_scope_area_type(cell_text)

                if area_type is None:
                    continue

                scopes.append(
                    {
                        "area_type": area_type,
                        "page_number": page_number,
                        "table_index": table_index,
                        "cell_index": cell.get("cell_index"),
                        "cell_bbox": cell.get("bbox"),
                        "covered_row_indexes": covered_row_indexes,
                        "cell_text": cell_text,
                    }
                )

        return {
            "page_number": page_number,
            "area_scopes": scopes,
        }

    @staticmethod
    def _detect_scope_area_type(cell_text):
        normalized = (
            str(cell_text).upper()
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        # A vertically merged stock-area label can retain the stable
        # BITKISEL and STOK words even when an embedded PDF font makes
        # individual characters in TOPRAK / ALANI undecodable.
        if "BITKISEL" in normalized and "STOK" in normalized:
            return detect_area_type("STOK ALANI")

        return detect_area_type(cell_text)
