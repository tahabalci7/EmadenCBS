from pathlib import Path

from src.ocr.ocr_engine import OCREngine
from src.coordinate.table_detector import TableDetector
from src.coordinate.state_machine import parse_coordinate_blocks


PDF_PATH = Path(
    "downloads/ADANA/EK-1/"
    "15420_Son_Sekli_Verilen_Rapor.pdf"
)


ocr_result = OCREngine.extract_text(
    str(PDF_PATH),
    max_pages=None,
)

raw_text = ocr_result["text"]

tables = TableDetector.find_tables(
    raw_text
)

print(
    f"Bulunan tablo sayısı: {len(tables)}"
)

print()

for index, table in enumerate(
    tables,
    start=1,
):
    print(
        "=" * 80
    )

    print(
        f"TABLO {index}"
    )

    print(
        "=" * 80
    )

    print(
        table[:6000]
    )

    points = parse_coordinate_blocks(
        table
    )

    print()
    print(
        f"PARSER SONUCU: {len(points)} koordinat"
    )

    print()