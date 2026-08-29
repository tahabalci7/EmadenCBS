import fitz


class TableLayoutExtractor:
    """Extract native PDF table geometry without changing parser behavior."""

    BBOX_TOLERANCE = 0.01

    @classmethod
    def extract_page(
        cls,
        pdf_path,
        page_number,
    ):
        """Return table metadata for a 1-based PDF page number."""

        if (
            not isinstance(page_number, int)
            or isinstance(page_number, bool)
            or page_number < 1
        ):
            raise ValueError(
                "page_number must be a positive 1-based integer"
            )

        metadata = {
            "page_number": page_number,
            "tables": [],
        }

        with fitz.open(pdf_path) as document:
            if page_number > len(document):
                return metadata

            page = document[page_number - 1]

            try:
                finder = page.find_tables()
                tables = list(
                    getattr(finder, "tables", [])
                    or []
                )
            except Exception:
                return metadata

            for table_index, table in enumerate(
                tables
            ):
                metadata["tables"].append(
                    cls._build_table_metadata(
                        page=page,
                        table=table,
                        table_index=table_index,
                    )
                )

        return metadata

    @classmethod
    def _build_table_metadata(
        cls,
        page,
        table,
        table_index,
    ):
        table_rows = list(
            getattr(table, "rows", [])
            or []
        )

        rows = []

        for row_index, row in enumerate(
            table_rows
        ):
            bbox = cls._bbox_list(
                getattr(row, "bbox", None)
            )

            rows.append(
                {
                    "row_index": row_index,
                    "bbox": bbox,
                    "y0": (
                        bbox[1]
                        if bbox is not None
                        else None
                    ),
                    "y1": (
                        bbox[3]
                        if bbox is not None
                        else None
                    ),
                }
            )

        cells = []

        for cell_index, cell in enumerate(
            list(
                getattr(table, "cells", [])
                or []
            )
        ):
            bbox = cls._bbox_list(cell)

            if bbox is None:
                continue

            row_index, col_index = (
                cls._find_cell_position(
                    table_rows=table_rows,
                    cell_bbox=bbox,
                )
            )

            covered_row_indexes = (
                cls._covered_row_indexes(
                    rows=rows,
                    cell_bbox=bbox,
                    row_index=row_index,
                )
            )

            try:
                text = page.get_textbox(
                    fitz.Rect(bbox)
                )
            except Exception:
                text = ""

            cells.append(
                {
                    "cell_index": cell_index,
                    "row_index": row_index,
                    "col_index": col_index,
                    "bbox": bbox,
                    "text": text,
                    "text_normalized": " ".join(
                        text.split()
                    ),
                    "rowspan": (
                        len(covered_row_indexes)
                        if row_index is not None
                        else None
                    ),
                    "colspan": None,
                    "covered_row_indexes": (
                        covered_row_indexes
                    ),
                    "is_merged_vertical": (
                        len(covered_row_indexes) > 1
                    ),
                }
            )

        return {
            "table_index": table_index,
            "bbox": cls._bbox_list(
                getattr(table, "bbox", None)
            ),
            "row_count": getattr(
                table,
                "row_count",
                len(rows),
            ),
            "col_count": getattr(
                table,
                "col_count",
                None,
            ),
            "rows": rows,
            "cells": cells,
        }

    @classmethod
    def _find_cell_position(
        cls,
        table_rows,
        cell_bbox,
    ):
        for row_index, row in enumerate(
            table_rows
        ):
            for col_index, row_cell in enumerate(
                getattr(row, "cells", [])
                or []
            ):
                row_cell_bbox = cls._bbox_list(
                    row_cell
                )

                if (
                    row_cell_bbox is not None
                    and cls._same_bbox(
                        cell_bbox,
                        row_cell_bbox,
                    )
                ):
                    return row_index, col_index

        return None, None

    @classmethod
    def _covered_row_indexes(
        cls,
        rows,
        cell_bbox,
        row_index,
    ):
        covered = set()

        if row_index is not None:
            covered.add(row_index)

        cell_y0 = cell_bbox[1]
        cell_y1 = cell_bbox[3]

        for row in rows:
            bbox = row["bbox"]

            if bbox is None:
                continue

            if (
                bbox[1]
                >= cell_y0 - cls.BBOX_TOLERANCE
                and bbox[3]
                <= cell_y1 + cls.BBOX_TOLERANCE
            ):
                covered.add(
                    row["row_index"]
                )

        return sorted(covered)

    @classmethod
    def _same_bbox(
        cls,
        first,
        second,
    ):
        return all(
            abs(left - right)
            <= cls.BBOX_TOLERANCE
            for left, right in zip(
                first,
                second,
            )
        )

    @staticmethod
    def _bbox_list(value):
        if value is None:
            return None

        try:
            bbox = [
                float(component)
                for component in value
            ]
        except (TypeError, ValueError):
            return None

        if len(bbox) != 4:
            return None

        return bbox
