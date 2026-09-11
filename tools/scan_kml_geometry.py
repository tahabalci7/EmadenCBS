"""Scan exported KML polygons for empty or self-intersecting rings.

Local corpus re-check after batch KML export. Not a per-PDF allowlist.
"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.coordinate.ring_geometry import count_lonlat_crossings


KML_NS = {"kml": "http://www.opengis.net/kml/2.2"}


def _pairs_from_text(text):
    pairs = []
    for line in str(text or "").split():
        parts = line.split(",")
        if len(parts) < 2:
            continue
        try:
            pairs.append((float(parts[0]), float(parts[1])))
        except ValueError:
            continue
    if (
        len(pairs) >= 2
        and pairs[0][0] == pairs[-1][0]
        and pairs[0][1] == pairs[-1][1]
    ):
        pairs = pairs[:-1]
    return pairs


def scan_kml_file(path):
    tree = ET.parse(path)
    root = tree.getroot()
    rings = []
    for coordinates in root.findall(".//kml:coordinates", KML_NS):
        pairs = _pairs_from_text(coordinates.text)
        rings.append(
            {
                "vertex_count": len(pairs),
                "crossings": count_lonlat_crossings(pairs) if pairs else 0,
            }
        )
    return {
        "kml_path": str(path),
        "ring_count": len(rings),
        "empty_rings": sum(1 for ring in rings if ring["vertex_count"] < 3),
        "crossed_rings": sum(1 for ring in rings if ring["crossings"]),
        "rings": rings,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Scan a KML file or folder for empty/crossed rings."
    )
    parser.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    target = args.path
    files = (
        sorted(target.glob("*.kml"))
        if target.is_dir()
        else [target]
    )
    summaries = [scan_kml_file(path) for path in files]
    print(
        json.dumps(
            {
                "file_count": len(summaries),
                "crossed_rings": sum(
                    item["crossed_rings"] for item in summaries
                ),
                "empty_rings": sum(
                    item["empty_rings"] for item in summaries
                ),
                "files": summaries,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
