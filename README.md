# eMadenCBS

PySide6 desktop app that extracts project metadata and coordinate tables
from Turkish ÇED/PTD PDFs and writes Google Earth KML.

## KML export gate

`KMLExporter.export` is fail-closed. A file is written only when every
compared polygon’s computed shoelace area matches the table/heading
declared area (ha or m²) and required layers exist.

- **Tolerance:** `abs(computed − declared) ≤ max(15% × declared, 0.10 ha)`.
  15% is the existing tuned default (vertex noise / shoelace vs geodesic
  on hectare-scale rings). The 0.10 ha floor covers tiny tesisi parcels.
- **CRS sanity:** rings larger than 5000 ha without a matching declared
  figure, or lon/lat outside Turkey / the project’s province, block the
  write (wrong zone or axis swap).
- **Layers:** Ruhsat Alanı plus at least one ÇED (`CED_ALANI` /
  `MEVCUT_CED_ALANI` / `YENI_CED_ALANI`). A combined “Ruhsat ve ÇED”
  heading may share one ring; silent copies do not.
- **On failure:** the intended `.kml` is not created or overwritten.
  A JSON reason (table title, declared ha, computed ha, ratio, codes)
  is stored under `_Duzeltme` next to the intended path.
- GUI CBS export, `CEDBatchProcessor` (optional `kml_root`), and
  `tools/sample_text_layer_kml.py` all use this gate. There is no
  production write path that skips it.

Adana re-export should run only through this gate: drop previous KML,
re-process from PDF, and keep a file only when the gate returns `ok`.
