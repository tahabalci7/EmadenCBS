import fitz
import subprocess

from pathlib import Path

from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.table_detector import TableDetector


PDF_PATH = Path(
    "downloads/ADANA/EK-1/"
    "27166_Son_Sekli_Verilen_Rapor.pdf"
)

OUTPUT_DIR = Path(
    "reports/page_ocr_test"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

TESSERACT_EXE = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

# PDF içindeki gerçek sayfa numaraları.
# PDF 79 = raporda basılı sayfa 78.
START_PAGE = 79
END_PAGE = 83


all_coordinates = []
total_tables = 0
combined_text = ""


doc = fitz.open(
    PDF_PATH
)


for page_number in range(
    START_PAGE,
    END_PAGE + 1,
):
    print()
    print("=" * 70)
    print(
        f"PDF SAYFA {page_number} OCR EDİLİYOR"
    )
    print("=" * 70)

    page = doc[
        page_number - 1
    ]

    pix = page.get_pixmap(
        dpi=300,
        alpha=False,
    )

    image_path = (
        OUTPUT_DIR
        / f"page_{page_number}.png"
    )

    pix.save(
        image_path
    )

    output_base = (
        OUTPUT_DIR
        / f"page_{page_number}_ocr"
    )

    subprocess.run(
        [
            TESSERACT_EXE,
            str(image_path),
            str(output_base),
            "-l",
            "tur+eng",
            "--psm",
            "4",
        ],
        check=True,
    )

    text_path = Path(
        str(output_base) + ".txt"
    )

    text = text_path.read_text(
        encoding="utf-8",
        errors="ignore",
    )
    combined_text += (
    f"\n--- OCR PDF SAYFA {page_number} ---\n"
    f"{text}\n"
)

    tables = TableDetector.find_tables(
        text
    )

    coordinates = (
        CoordinateEngine.extract_coordinates(
            text
        )
    )

    total_tables += len(
        tables
    )

    print(
        f"Tablo       : {len(tables)}"
    )

    print(
        f"Koordinat   : {len(coordinates)}"
    )

    for item in coordinates:
        all_coordinates.append(
            {
                "page": page_number,
                **item,
            }
        )


doc.close()
combined_tables = TableDetector.find_tables(
    combined_text
)

combined_coordinates = (
    CoordinateEngine.extract_coordinates(
        combined_text
    )
)

print()
print("=" * 70)
print("BİRLEŞİK 5 SAYFA TESTİ")
print("=" * 70)

print(
    f"Birleşik tablo     : "
    f"{len(combined_tables)}"
)

print(
    f"Birleşik koordinat : "
    f"{len(combined_coordinates)}"
)
print()
print("TABLO BAZINDA DAĞILIM")
print("-" * 70)

table_summary = {}

for item in combined_coordinates:
    key = (
        item["table_index"],
        item["section"],
        item["table_type"],
    )

    if key not in table_summary:
        table_summary[key] = 0

    table_summary[key] += 1

for key, count in table_summary.items():

    table_index, section, table_type = key

    print()
    print(
        f"Tablo {table_index} | "
        f"{table_type} | "
        f"{section} | "
        f"{count} koordinat"
    )

    for item in combined_coordinates:

        if item["table_index"] != table_index:
            continue

        print(
            f'    {item["name"]} | '
            f'Y={item["y"]} | '
            f'X={item["x"]} | '
            f'Lat={item["latitude"]} | '
            f'Lon={item["longitude"]}'
        )
# ---------------------------------------------------------
# AYNI KOORDİNATLARI TEMİZLE
# ---------------------------------------------------------

unique_coordinates = []
seen = set()


for item in all_coordinates:
    key = (
        item["y"],
        item["x"],
    )

    if key in seen:
        continue

    seen.add(
        key
    )

    unique_coordinates.append(
        item
    )


# ---------------------------------------------------------
# SONUÇ
# ---------------------------------------------------------

print()
print("=" * 70)
print("5 SAYFALIK OCR TEST SONUCU")
print("=" * 70)

print(
    f"Toplam bulunan tablo      : {total_tables}"
)

print(
    f"Toplam koordinat          : {len(all_coordinates)}"
)

print(
    f"Benzersiz koordinat       : {len(unique_coordinates)}"
)

print()
print("SAYFA BAZINDA KOORDİNATLAR")
print("-" * 70)


for item in unique_coordinates:
    print(
        f'Sayfa {item["page"]} | '
        f'{item["name"]} | '
        f'Y={item["y"]} | '
        f'X={item["x"]} | '
        f'Lat={item["latitude"]} | '
        f'Lon={item["longitude"]}'
    )