import re


LABEL_PATTERN = re.compile(
    r"^[A-ZÇĞİÖŞÜ0-9_.-]+$",
    re.IGNORECASE,
)

NUMERIC_LABEL_PATTERN = re.compile(
    r"^\d+$"
)


def is_number(value: str) -> bool:
    try:
        float(
            value
            .replace(",", ".")
            .strip()
        )
        return True

    except ValueError:
        return False


def to_float(value: str) -> float:
    return float(
        value
        .replace(",", ".")
        .strip()
    )


def is_label(
    value: str,
    allow_numeric_labels: bool,
) -> bool:
    value = value.strip()

    if not value:
        return False

    if (
        allow_numeric_labels
        and NUMERIC_LABEL_PATTERN.match(value)
    ):
        return True

    if not LABEL_PATTERN.match(value):
        return False

    # Sadece sıradan bir sayıysa ve sayısal
    # etiketlere izin verilmiyorsa etiket değildir.
    if is_number(value):
        return False

    return True


def is_valid_coordinate_block(
    utm_y,
    utm_x,
    latitude,
    longitude,
) -> bool:
    return (
        100000 <= utm_y <= 999999
        and 3000000 <= utm_x <= 5000000
        and 35 <= latitude <= 43
        and 25 <= longitude <= 46
    )


def _clean_numeric_token(token: str) -> str:
    return (
        token.strip()
        .replace(",", ".")
        .replace(" ", "")
    )

def _recover_missing_decimal(value: float):
    """
    OCR'ın ondalık noktayı tamamen düşürdüğü sayılar için
    alternatif değerler üretir.

    Örnek:
        7546493   -> 754649.3
        754229473 -> 754229.473

    Belirli bir etiket veya ÇED dosyasına bağlı değildir.
    """

    if value < 1000000:
        return []

    text = str(int(value))

    candidates = []

    for decimal_count in range(1, len(text) - 5):
        split_index = len(text) - decimal_count

        integer_part = text[:split_index]
        decimal_part = text[split_index:]

        if len(integer_part) != 6:
            continue

        try:
            recovered = float(
                f"{integer_part}.{decimal_part}"
            )
        except ValueError:
            continue

        if 100000 <= recovered <= 999999:
            candidates.append(recovered)

    return candidates

def _join_numeric_fragments(tokens, start_index, max_parts=3):
    """
    OCR'ın böldüğü sayısal parçaları genel olarak birleştirir.

    Örnekler:
        749 102.000   -> 749102.000
        750779 .000   -> 750779.000
        7545 13.639   -> 754513.639
        37.5805 1603  -> 37.58051603

    Aynı başlangıç noktasından birden fazla geçerli aday
    üretilebiliyorsa daha fazla OCR parçasını kullanan aday
    önce değerlendirilir.

    Dönen her aday:
        (end_index, value)
    """
    candidates = []

    for part_count in range(1, max_parts + 1):
        end_index = start_index + part_count

        if end_index > len(tokens):
            break

        raw_parts = tokens[start_index:end_index]

        if not all(
            re.fullmatch(
                r"[+-]?\d*(?:[.,]\d*)?",
                part,
            )
            for part in raw_parts
        ):
            break

        joined = "".join(
            _clean_numeric_token(part)
            for part in raw_parts
        )

        if not joined:
            continue

        try:
            value = float(joined)
        except ValueError:
            continue

        candidates.append(
            (
                end_index,
                value,
            )
        )

        recovered_values = _recover_missing_decimal(
            value
        )

        for recovered_value in recovered_values:
            candidates.append(
                (
                    end_index,
                    recovered_value,
                )
            )

    candidates.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return candidates


def _find_coordinate_sequence(tokens):
    """
    Satır içinden genel yapısal kurala göre:

        [etiket] [UTM-Y] [UTM-X] ... [LAT] [LON]

    dizisini arar.

    Etiket adına, ÇED türüne veya tablo adına bağlı değildir.
    """

    token_count = len(tokens)

    # Geçerli koordinatlar zaten bağımsız tokenlar
    # halindeyse, kısa sayısal etiketleri ilk UTM
    # değeriyle birleştiren fragment adaylarından önce
    # doğrudan bu diziyi kullan.
    direct_values = []

    for token in tokens:
        if not re.fullmatch(
            r"[+-]?\d*(?:[.,]\d*)?",
            token,
        ):
            direct_values.append(None)
            continue

        try:
            direct_values.append(
                float(
                    _clean_numeric_token(token)
                )
            )
        except ValueError:
            direct_values.append(None)

    for y_start, utm_y in enumerate(
        direct_values
    ):
        if (
            utm_y is None
            or not 100000 <= utm_y <= 999999
        ):
            continue

        for x_start in range(
            y_start + 1,
            min(y_start + 4, token_count),
        ):
            utm_x = direct_values[x_start]

            if (
                utm_x is None
                or not 3000000 <= utm_x <= 5000000
            ):
                continue

            for lat_start in range(
                x_start + 1,
                token_count,
            ):
                latitude = direct_values[
                    lat_start
                ]

                if (
                    latitude is None
                    or not 35 <= latitude <= 43
                ):
                    continue

                for lon_start in range(
                    lat_start + 1,
                    token_count,
                ):
                    longitude = direct_values[
                        lon_start
                    ]

                    if (
                        longitude is None
                        or not 25 <= longitude <= 46
                    ):
                        continue

                    return {
                        "label_end": y_start,
                        "utm_y": utm_y,
                        "utm_x": utm_x,
                        "latitude": latitude,
                        "longitude": longitude,
                    }

    for y_start in range(token_count):
        for y_end, utm_y in _join_numeric_fragments(
            tokens,
            y_start,
            max_parts=3,
        ):
            if not (
                100000
                <= utm_y
                <= 999999
            ):
                continue

            for x_start in range(
                y_end,
                min(y_end + 3, token_count)
            ):
                for x_end, utm_x in _join_numeric_fragments(
                    tokens,
                    x_start,
                    max_parts=3,
                ):
                    if not (
                        3000000
                        <= utm_x
                        <= 5000000
                    ):
                        continue

                    lat_start_min = x_end

                    for lat_start in range(
                        lat_start_min,
                        token_count
                    ):
                        for lat_end, latitude in _join_numeric_fragments(
                            tokens,
                            lat_start,
                            max_parts=3,
                        ):
                            if not (
                                35
                                <= latitude
                                <= 43
                            ):
                                continue

                            for lon_start in range(
                                lat_end,
                                token_count
                            ):
                                for lon_end, longitude in _join_numeric_fragments(
                                    tokens,
                                    lon_start,
                                    max_parts=3,
                                ):
                                    if not (
                                        25
                                        <= longitude
                                        <= 46
                                    ):
                                        continue

                                    return {
                                        "label_end": y_start,
                                        "utm_y": utm_y,
                                        "utm_x": utm_x,
                                        "latitude": latitude,
                                        "longitude": longitude,
                                    }

    return None


def recover_row_coordinate_from_values(
    line: str,
):
    """
    OCR etiketi bozmuş olsa bile satırdaki koordinat
    değerlerinden kaydı kurtarmaya çalışır.

    Örnek:

    M 2 CED-1 750801 4165090 M 2 CED-1 37.59 35.84

    veya etiketi kısmen bozulmuş satırlar.
    """

    tokens = [
        token.strip()
        for token in line.split()
        if token.strip()
    ]

    if len(tokens) < 4:
        return None

    # ---------------------------------------------
    # SATIRDAKİ TÜM SAYISAL DEĞERLERİ TOPLA
    # ---------------------------------------------

    numeric_items = []

    for index, token in enumerate(tokens):
        if not is_number(token):
            continue

        try:
            value = to_float(token)
        except ValueError:
            continue

        numeric_items.append(
            (
                index,
                token,
                value,
            )
        )

    if len(numeric_items) < 4:
        return None

    # ---------------------------------------------
    # UTM Y ADAYLARI
    # ---------------------------------------------

    y_candidates = []

    for index, token, value in numeric_items:

        if 100000 <= value <= 999999:
            y_candidates.append(
                (
                    index,
                    value,
                )
            )

    # OCR Y'yi iki parçaya ayırmış olabilir:
    #
    # 749 102.000
    # ↓
    # 749102.000

    for i in range(
        len(numeric_items) - 1
    ):
        index1, token1, value1 = numeric_items[i]
        index2, token2, value2 = numeric_items[i + 1]

        if index2 != index1 + 1:
            continue

        joined = token1 + token2

        try:
            joined_value = to_float(
                joined
            )
        except ValueError:
            continue

        if 100000 <= joined_value <= 999999:
            y_candidates.append(
                (
                    index1,
                    joined_value,
                )
            )

    # ---------------------------------------------
    # UTM X ADAYLARI
    # ---------------------------------------------

    x_candidates = []

    for index, token, value in numeric_items:

        if 3000000 <= value <= 5000000:
            x_candidates.append(
                (
                    index,
                    value,
                )
            )

    # X de bölünmüş olabilir.

    for i in range(
        len(numeric_items) - 1
    ):
        index1, token1, value1 = numeric_items[i]
        index2, token2, value2 = numeric_items[i + 1]

        if index2 != index1 + 1:
            continue

        joined = token1 + token2

        try:
            joined_value = to_float(
                joined
            )
        except ValueError:
            continue

        if 3000000 <= joined_value <= 5000000:
            x_candidates.append(
                (
                    index1,
                    joined_value,
                )
            )

    # ---------------------------------------------
    # ENLEM / BOYLAM ADAYLARI
    # ---------------------------------------------

    latitude_candidates = [
        (
            index,
            value,
        )
        for index, token, value in numeric_items
        if 35 <= value <= 43
    ]

    longitude_candidates = [
        (
            index,
            value,
        )
        for index, token, value in numeric_items
        if 25 <= value <= 46
    ]

    # ---------------------------------------------
    # DOĞRU SIRAYI ARA
    #
    # Y → X → LAT → LON
    # ---------------------------------------------

    for y_index, utm_y in y_candidates:

        for x_index, utm_x in x_candidates:

            if x_index <= y_index:
                continue

            for lat_index, latitude in latitude_candidates:

                if lat_index <= x_index:
                    continue

                for lon_index, longitude in longitude_candidates:

                    if lon_index <= lat_index:
                        continue

                    if not is_valid_coordinate_block(
                        utm_y,
                        utm_x,
                        latitude,
                        longitude,
                    ):
                        continue

                    # Etiket bozuksa ilk UTM değerinden
                    # önceki kısmı etiket olarak sakla.

                    label_tokens = tokens[:y_index]

                    label = " ".join(
                        label_tokens
                    ).strip()

                    if not label:
                        label = "OCR_POINT"

                    return {
                        "label": label,
                        "utm_y": utm_y,
                        "utm_x": utm_x,
                        "latitude": latitude,
                        "longitude": longitude,
                    }

    return None
def normalize_ocr_label(label: str) -> str:
    """
    OCR tarafından parçalanmış koordinat etiketlerini
    genel kurallarla standart biçime getirir.

    Bu fonksiyon belirli bir ÇED dosyasındaki etiketleri
    hard-code etmez; yalnızca yaygın OCR bozulmalarını düzeltir.
    """
    label = label.strip().upper()

    # Fazla boşlukları temizle.
    label = re.sub(r"\s+", " ", label)

    # Ayraçlardan sonra/önce OCR'ın I/İ okuduğu sıra numarasını düzelt.
    label = re.sub(
        r"(?<=[\-_])(?:I|İ)(?=$|[\-_])",
        "1",
        label,
    )

    # GALERİ kelimesindeki yaygın OCR son-harf bozulmaları.
    # Örn. GALERL-4 -> GALERI-4
    label = re.sub(
        r"\bGALER[LİI1]\b",
        "GALERI",
        label,
    )

    parts = label.split()

    if len(parts) == 1:
        return parts[0]

    # "M 2 CED-1" gibi harf + sayı + devam yapıları.
    if (
        len(parts) >= 3
        and re.fullmatch(r"[A-ZÇĞİÖŞÜ]+", parts[0])
        and parts[1].isdigit()
    ):
        return (
            parts[0]
            + parts[1]
            + "_"
            + "_".join(parts[2:])
        )

    # "4 GALERI-1" gibi sayı + ad yapıları.
    if (
        len(parts) >= 2
        and parts[0].isdigit()
    ):
        return (
            parts[0]
            + "_"
            + "_".join(parts[1:])
        )

    return "_".join(parts)


def parse_row_coordinate(
    line: str,
    allow_numeric_labels: bool,
):
    """
    OCR bozulmalarına dayanıklı genel satır ayrıştırıcı.

    Etiket adına bağlı değildir.
    Koordinatların beklenen yapısal sırasını kullanır:
        [ETİKET] [UTM-Y] [UTM-X] [opsiyonel tekrar etiket] [LAT] [LON]
    """

    tokens = [
        token.strip()
        for token in line.split()
        if token.strip()
    ]

    if len(tokens) < 4:
        return None

    sequence = _find_coordinate_sequence(
        tokens
    )

    if sequence is None:
        return None

    label_tokens = tokens[
        :sequence["label_end"]
    ]

    if not label_tokens:
        return None

    label = normalize_ocr_label(
        " ".join(label_tokens)
    )

    if not label:
        return None

    if is_number(label):
        if not allow_numeric_labels:
            return None

    utm_y = sequence["utm_y"]
    utm_x = sequence["utm_x"]
    latitude = sequence["latitude"]
    longitude = sequence["longitude"]

    if not is_valid_coordinate_block(
        utm_y,
        utm_x,
        latitude,
        longitude,
    ):
        return None

    return {
        "label": label,
        "utm_y": utm_y,
        "utm_x": utm_x,
        "latitude": latitude,
        "longitude": longitude,
    }


def parse_coordinate_blocks(
    text: str,
    line_sources=None,
):
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    results = []
    seen = set()

    def get_line_source(line_index):
        if (
            line_sources is None
            or line_index < 0
            or line_index >= len(line_sources)
        ):
            return None, None

        line_source = line_sources[
            line_index
        ]

        if not isinstance(
            line_source,
            dict,
        ):
            return None, None

        source_page = line_source.get(
            "source_page"
        )
        source_method = line_source.get(
            "source_method"
        )

        if source_method not in {
            "text_layer",
            "ocr",
        }:
            return None, None

        if (
            not isinstance(source_page, int)
            or isinstance(source_page, bool)
            or source_page < 1
        ):
            return None, None

        return source_page, source_method

    upper_text = text.upper()

    allow_numeric_labels = (
        "KOORDİNAT" in upper_text
        or "KOORDINAT" in upper_text
    )

    # =========================================================
    # POLİGON BAŞLIĞINDAN GRUP TESPİTİ
    # =========================================================

    def detect_polygon_group(line):
        normalized = (
            line.upper()
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        patterns = [
            r"^\s*(\d+)\s+NOLU\s+POLIGON\b",
            r"^\s*(\d+)\s+NO(?:LU)?\s+POLIGON\b",
            r"\b(\d+)\s*[.)\-:]?\s*POLIGON\b",
            r"^\s*POLIGON\s*[-.:]?\s*(\d+)\b",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                normalized,
            )

            if match:
                number = match.group(1)

                return (
                    f"POLIGON_{number}",
                    line.strip(),
                )

        return None

    # =========================================================
    # NOKTA ADINDAN FALLBACK GRUP TESPİTİ
    # =========================================================

    def detect_group_from_label(label):
        if not label:
            return None

        value = normalize_ocr_label(
            str(label)
        ).upper()

        value = (
            value
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        # İR-1-1 / IR-2-4
        match = re.match(
            r"^([A-Z]+)-(\d+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(1)}_"
                f"{match.group(2)}"
            )

        # 1-CED-1 / 2-CED-7
        match = re.match(
            r"^(\d+)-([A-Z]+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(2)}_"
                f"{match.group(1)}"
            )

        # M_CED-1 / M2_CED-4 / M3_CED-7
        match = re.match(
            r"^([A-Z]+\d*_[A-Z]+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(1)}"
            )

        # 1_GALERI-1 / 4_GALERI-2
        match = re.match(
            r"^(\d+)_([A-Z]+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(2)}_"
                f"{match.group(1)}"
            )

        return None

    # =========================================================
    # 1. YÖNTEM
    # TEK SATIRLIK KOORDİNATLAR
    # =========================================================

    current_polygon_group = "DEFAULT"
    current_polygon_heading = ""
    current_area_type = None

    for line_index, line in enumerate(lines):
        detected_area_type = detect_area_type(
            line
        )

        if detected_area_type is not None:
            current_area_type = (
                detected_area_type
            )

            current_polygon_group = "DEFAULT"
            current_polygon_heading = ""

        detected_group = detect_polygon_group(
            line
        )

        if detected_group is not None:
            (
                current_polygon_group,
                current_polygon_heading,
            ) = detected_group

            continue

        point = parse_row_coordinate(
            line,
            allow_numeric_labels,
        )

        if point is None:
            point = recover_row_coordinate_from_values(
                line
            )

        if point is None:
            continue

        point["label"] = normalize_ocr_label(
            point["label"]
        )

        if is_number(point["label"]):
            if not allow_numeric_labels:
                continue

        label_group = detect_group_from_label(
            point["label"]
        )

        if current_polygon_group != "DEFAULT":
            point["polygon_group"] = (
                current_polygon_group
            )

            point["polygon_heading"] = (
                current_polygon_heading
            )

        elif label_group:
            point["polygon_group"] = (
                label_group
            )

            point["polygon_heading"] = (
                label_group
            )

        else:
            point["polygon_group"] = "DEFAULT"
            point["polygon_heading"] = ""

        # Satır bazlı tespit edilen alan türünü
        # her nokta için table_type_override olarak sakla.
        point["table_type_override"] = current_area_type

        (
            point["source_page"],
            point["source_method"],
        ) = get_line_source(
            line_index
        )

        key = (
            point["polygon_group"],
            point["label"],
            point["utm_y"],
            point["utm_x"],
        )

        if key in seen:
            continue

        seen.add(
            key
        )

        results.append(
            point
        )

    # =========================================================
    # 2. YÖNTEM
    # ESKİ 5 SATIRLIK BLOK YAPISI
    # =========================================================

    i = 0

    current_polygon_group = "DEFAULT"
    current_polygon_heading = ""

    while i < len(lines):
        line = lines[i]

        # Satırlar ilerlerken alan türünü güncelle (ikinci yöntem için).
        detected_area_type = detect_area_type(
            line
        )

        if detected_area_type is not None:
            current_area_type = (
                detected_area_type
            )

            current_polygon_group = "DEFAULT"
            current_polygon_heading = ""

        detected_group = detect_polygon_group(
            line
        )

        if detected_group is not None:
            (
                current_polygon_group,
                current_polygon_heading,
            ) = detected_group

            i += 1
            continue

        if not is_label(
            line,
            allow_numeric_labels,
        ):
            i += 1
            continue

        block = lines[
            i:i + 5
        ]

        if len(block) != 5:
            i += 1
            continue

        if not all(
            is_number(value)
            for value in block[1:]
        ):
            i += 1
            continue

        utm_y = to_float(
            block[1]
        )

        utm_x = to_float(
            block[2]
        )

        latitude = to_float(
            block[3]
        )

        longitude = to_float(
            block[4]
        )

        if not is_valid_coordinate_block(
            utm_y,
            utm_x,
            latitude,
            longitude,
        ):
            i += 1
            continue

        normalized_label = normalize_ocr_label(
            block[0]
        )

        label_group = detect_group_from_label(
            normalized_label
        )

        if current_polygon_group != "DEFAULT":
            polygon_group = (
                current_polygon_group
            )

            polygon_heading = (
                current_polygon_heading
            )

        elif label_group:
            polygon_group = (
                label_group
            )

            polygon_heading = (
                label_group
            )

        else:
            polygon_group = "DEFAULT"
            polygon_heading = ""

        (
            source_page,
            source_method,
        ) = get_line_source(
            i + 1
        )

        point = {
            "label": normalized_label,
            "utm_y": utm_y,
            "utm_x": utm_x,
            "latitude": latitude,
            "longitude": longitude,
            "polygon_group": polygon_group,
            "polygon_heading": polygon_heading,
            "table_type_override": current_area_type,
            "source_page": source_page,
            "source_method": source_method,
        }

        key = (
            point["polygon_group"],
            point["label"],
            point["utm_y"],
            point["utm_x"],
        )

        if key not in seen:
            seen.add(
                key
            )

            results.append(
                point
            )

        i += 5

    return results
def detect_area_type(line):
        normalized = (
            str(line).upper()
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        if "RUHSAT ALANI" in normalized:
            return "RUHSAT_ALANI"

        if (
            "RUHSAT SINIR" in normalized
            and "KOORDINAT" in normalized
        ):
            return "RUHSAT_ALANI"

        if (
            "PROJE ALANI" in normalized
            or "PROJE ALANLARI" in normalized
            or "PROJEYE KONU ALAN" in normalized
        ):
            return "PROJE_ALANI"

        if (
            "CED ALANI" in normalized
            or "CED IZIN ALANI" in normalized
        ):
            return "CED_ALANI"

        if (
            "BITKISEL TOPRAK" in normalized
            and (
                "STOK" in normalized
                or "DEPO" in normalized
                or "ALAN" in normalized
            )
        ):
            return "BITKISEL_TOPRAK_ALANI"

        if (
            "PASA" in normalized
            and (
                "STOK" in normalized
                or "DEPO" in normalized
                or "ALAN" in normalized
            )
        ):
            return "STOK_ALANI"

        if (
            "URUN STOK" in normalized
            or "CEVHER STOK" in normalized
            or "TUVENAN" in normalized
        ):
            return "STOK_ALANI"

        if "SANTIYE ALANI" in normalized:
            return "SANTIYE_ALANI"

        if (
            "KIRMA" in normalized
            and "ELEME" in normalized
        ):
            return "KIRMA_ELEME_ALANI"

        if (
            "ATIK" in normalized
            and "ALAN" in normalized
        ):
            return "ATIK_ALANI"

        return None
def detect_group_from_label(label):
        """
        Poligon başlığı tablo metninde kaybolmuşsa,
        nokta adındaki açık grup yapısını kullanır.

        Örnekler:
        İR-1-1      -> LABEL_IR_1
        İR-2-1      -> LABEL_IR_2
        1-CED-1     -> LABEL_CED_1
        2-CED-1     -> LABEL_CED_2
        M2_CED-1    -> LABEL_M2_CED
        1_GALERI-1  -> LABEL_GALERI_1

        Basit R.1, SA-1 veya yalnız 1,2,3 gibi
        noktalarda grup üretmez.
        """

        if not label:
            return None

        value = normalize_ocr_label(
            str(label)
        ).upper()

        value = (
            value
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        # İR-1-1 / IR-2-4
        match = re.match(
            r"^([A-Z]+)-(\d+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(1)}_"
                f"{match.group(2)}"
            )

        # 1-CED-1 / 2-CED-7
        match = re.match(
            r"^(\d+)-([A-Z]+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(2)}_"
                f"{match.group(1)}"
            )

        # M_CED-1 / M2_CED-4 / M3_CED-7
        match = re.match(
            r"^([A-Z]+\d*_[A-Z]+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(1)}"
            )

        # 1_GALERI-1 / 4_GALERI-2
        match = re.match(
            r"^(\d+)_([A-Z]+)-\d+$",
            value,
        )

        if match:
            return (
                f"LABEL_{match.group(2)}_"
                f"{match.group(1)}"
            )

        return None
        return results
