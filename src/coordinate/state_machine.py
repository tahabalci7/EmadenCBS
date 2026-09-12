import re

from src.coordinate.table_classifier import TableClassifier


LABEL_PATTERN = re.compile(
    r"^[A-ZÇĞİÖŞÜ0-9_.-]+$",
    re.IGNORECASE,
)

NUMERIC_LABEL_PATTERN = re.compile(
    r"^\d+$"
)

COMBINED_NUMBER_PATTERN = (
    r"(?<![A-Za-zÇĞİÖŞÜçğıöşü])"
    r"([+-]?(?:"
    r"\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?|"
    r"\d{1,3}(?:\.\d{3})+,\d+|"
    r"\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?|"
    r"\d{1,3}(?:,\d{3})+\.\d+|"
    r"\d{1,3}(?:\s\d{3})+(?:[.,]\d+)?|"
    r"\d+(?:[.,]\d+)?"
    r"))"
)

COMBINED_GEOGRAPHIC_PATTERN = re.compile(
    r"^"
    + COMBINED_NUMBER_PATTERN
    + r"\s*:\s*"
    + COMBINED_NUMBER_PATTERN
    + r"$"
)

NUMBER_TOKEN_PATTERN = re.compile(
    COMBINED_NUMBER_PATTERN
)


def is_ignorable_table_context_line(line) -> bool:
    """Page markers, running headers, and CRS metadata are not headings."""
    return TableClassifier._looks_like_context_noise_line(
        line
    )


def is_number(value: str) -> bool:
    try:
        parse_localized_number(value)
        return True

    except (TypeError, ValueError):
        return False


def to_float(value: str) -> float:
    return parse_localized_number(value)


def parse_localized_number(value: str) -> float:
    text = str(value).strip().strip(":").strip()
    if not text:
        raise ValueError("empty numeric token")

    if re.fullmatch(
        r"[+-]?\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?",
        text,
    ) or re.fullmatch(
        r"[+-]?\d{1,3}(?:\.\d{3})+,\d+",
        text,
    ):
        return float(
            text.replace(".", "").replace(",", ".")
        )

    if re.fullmatch(
        r"[+-]?\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?",
        text,
    ) or re.fullmatch(
        r"[+-]?\d{1,3}(?:,\d{3})+\.\d+",
        text,
    ):
        return float(
            text.replace(",", "")
        )

    if re.fullmatch(
        r"[+-]?\d{1,3}(?:\s\d{3})+(?:[.,]\d+)?",
        text,
    ):
        compact = text.replace(" ", "")
        if compact.count(",") == 1 and "." not in compact:
            return float(
                compact.replace(",", ".")
            )
        return float(
            compact.replace(",", "")
        )

    return float(
        text.replace(",", ".")
    )


def parse_combined_geographic(value: str):
    match = COMBINED_GEOGRAPHIC_PATTERN.fullmatch(
        value.strip()
    )

    if match is None:
        return None

    return (
        to_float(match.group(1)),
        to_float(match.group(2)),
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
        number = to_float(value)
        if is_utm_easting(number) or is_utm_northing(number):
            return False
        return True

    if not LABEL_PATTERN.match(value):
        return False

    if is_number(value):
        number = to_float(value)
        if is_utm_easting(number) or is_utm_northing(number):
            return False
        if 25 <= number <= 46:
            return False
        if allow_numeric_labels and number < 1000:
            return True
        return False

    return True


def is_utm_easting(value) -> bool:
    return 100000 <= value <= 999999


def is_utm_northing(value) -> bool:
    return 3000000 <= value <= 5000000


def is_valid_utm_pair(utm_y, utm_x) -> bool:
    return is_utm_easting(utm_y) and is_utm_northing(utm_x)


def _merge_space_grouped_thousands(tokens):
    """
    Rejoin European space-grouped UTM tokens after whitespace split.

    ``463 000`` and ``4 014 000`` are one easting/northing each.
    A leading point number such as ``1 463 000`` is not absorbed
    because ``1463000`` is not a valid UTM easting or northing.
    """

    merged = []
    index = 0

    while index < len(tokens):
        token = tokens[index]
        grouped = None
        grouped_end = index

        if re.fullmatch(r"[+-]?\d{1,3}", token):
            for extra in range(3, 0, -1):
                end = index + 1 + extra
                if end > len(tokens):
                    continue
                parts = tokens[index:end]
                if not all(
                    re.fullmatch(r"\d{3}", part)
                    for part in parts[1:]
                ):
                    continue
                compact = "".join(parts).replace("+", "")
                try:
                    value = float(compact)
                except ValueError:
                    continue
                if (
                    is_utm_easting(value)
                    or is_utm_northing(value)
                ):
                    grouped = " ".join(parts)
                    grouped_end = end
                    break

        if grouped is not None:
            merged.append(grouped)
            index = grouped_end
            continue

        merged.append(token)
        index += 1

    return merged


def is_valid_coordinate_block(
    utm_y,
    utm_x,
    latitude,
    longitude,
) -> bool:
    return (
        is_valid_utm_pair(utm_y, utm_x)
        and 35 <= latitude <= 43
        and 25 <= longitude <= 46
    )


def order_utm(first, second):
    if is_utm_easting(first) and is_utm_northing(second):
        return first, second

    if is_utm_northing(first) and is_utm_easting(second):
        return second, first

    return None


def _numeric_line_value(line: str):
    text = (
        str(line)
        .strip()
        .strip(":")
        .strip()
    )
    if not text or not is_number(text):
        return None
    return to_float(text)


def parse_utm_pair(lines, start):
    if start >= len(lines):
        return None

    combined = parse_combined_geographic(lines[start])
    if combined is not None:
        ordered = order_utm(combined[0], combined[1])
        if ordered is not None:
            return ordered[0], ordered[1], start + 1

    first = _numeric_line_value(lines[start])
    if first is None:
        return None

    pos = start + 1
    if pos < len(lines) and lines[pos].strip() == ":":
        pos += 1
    if pos >= len(lines):
        return None

    second = _numeric_line_value(lines[pos])
    if second is None:
        return None

    ordered = order_utm(first, second)
    if ordered is None:
        return None

    return ordered[0], ordered[1], pos + 1


def parse_geographic_pair(lines, start, utm_y, utm_x):
    if start >= len(lines):
        return None

    combined = parse_combined_geographic(lines[start])
    if combined is not None:
        latitude, longitude = order_geographic(
            utm_y,
            utm_x,
            combined[0],
            combined[1],
        )
        if is_valid_coordinate_block(
            utm_y,
            utm_x,
            latitude,
            longitude,
        ):
            return latitude, longitude, start + 1

    first = _numeric_line_value(lines[start])
    if first is None:
        return None

    pos = start + 1
    if pos < len(lines) and lines[pos].strip() == ":":
        pos += 1
    if pos >= len(lines):
        return None

    second = _numeric_line_value(lines[pos])
    if second is None:
        return None

    latitude, longitude = order_geographic(
        utm_y,
        utm_x,
        first,
        second,
    )
    if not is_valid_coordinate_block(
        utm_y,
        utm_x,
        latitude,
        longitude,
    ):
        return None

    return latitude, longitude, pos + 1


def parse_unlabeled_utm_geo_runs(lines, start):
    if start < len(lines) and is_label(lines[start], False):
        return None

    utm_pairs = []
    pos = start

    while pos < len(lines):
        if is_label(lines[pos], False):
            break

        parsed = parse_utm_pair(lines, pos)
        if parsed is None:
            break

        utm_y, utm_x, next_pos = parsed
        utm_pairs.append((utm_y, utm_x))
        pos = next_pos

    if len(utm_pairs) < 3:
        return None

    geo_pairs = []
    geo_pos = pos
    while geo_pos < len(lines):
        combined = parse_combined_geographic(lines[geo_pos])
        if combined is not None:
            if order_utm(combined[0], combined[1]) is not None:
                break
            geo_pairs.append(combined)
            geo_pos += 1
            continue

        geographic = parse_geographic_pair(
            lines,
            geo_pos,
            utm_pairs[0][0],
            utm_pairs[0][1],
        )
        if geographic is None:
            break

        latitude, longitude, next_pos = geographic
        geo_pairs.append((latitude, longitude))
        geo_pos = next_pos

    points = []
    if len(geo_pairs) == len(utm_pairs):
        for utm_pair, geo_pair in zip(utm_pairs, geo_pairs):
            latitude, longitude = order_geographic(
                utm_pair[0],
                utm_pair[1],
                geo_pair[0],
                geo_pair[1],
            )
            if not is_valid_coordinate_block(
                utm_pair[0],
                utm_pair[1],
                latitude,
                longitude,
            ):
                geo_pairs = []
                points = []
                break
            points.append(
                (
                    utm_pair[0],
                    utm_pair[1],
                    latitude,
                    longitude,
                )
            )

    if not points:
        for utm_y, utm_x in utm_pairs:
            points.append(
                (
                    utm_y,
                    utm_x,
                    None,
                    None,
                )
            )
        geo_pos = pos

    return {
        "points": points,
        "consumed": geo_pos - start,
    }


def parse_point_at(lines, start, allow_numeric_labels):
    if start >= len(lines):
        return None

    label = None
    pos = start
    if is_label(lines[start], allow_numeric_labels):
        label = lines[start].strip()
        pos = start + 1

    utm_pair = parse_utm_pair(lines, pos)
    if utm_pair is None:
        return None

    utm_y, utm_x, pos = utm_pair
    if (
        pos < len(lines)
        and is_label(lines[pos], True)
        and parse_geographic_pair(
            lines,
            pos + 1,
            utm_y,
            utm_x,
        )
        is not None
    ):
        if label is None:
            label = lines[pos].strip()
        pos += 1

    geographic = parse_geographic_pair(
        lines,
        pos,
        utm_y,
        utm_x,
    )
    if geographic is None:
        if _looks_like_invalid_geographic_attempt(lines, pos, utm_y, utm_x):
            return None

        if label is None:
            label = ""

        return {
            "label": label,
            "utm_y": utm_y,
            "utm_x": utm_x,
            "latitude": None,
            "longitude": None,
            "consumed": pos - start,
        }

    latitude, longitude, end = geographic
    if label is None:
        label = ""

    return {
        "label": label,
        "utm_y": utm_y,
        "utm_x": utm_x,
        "latitude": latitude,
        "longitude": longitude,
        "consumed": end - start,
    }


def _looks_like_column_header(line):
    normalized = TableClassifier._normalize(line)

    if normalized in {
        "Y",
        "X",
        "Z",
        "E",
        "N",
        "ENLEM",
        "BOYLAM",
        "SAGA",
        "YUKARI",
        "NOKTA",
        "NOKTA NO",
        "NOKTA NO.",
        "SR",
        "SIRA",
        "SIRA NO",
        "SIRA N",
        "UTM",
        "DATUM",
    }:
        return True

    return normalized.startswith("NOKTA")


def parse_column_major_coordinates(
    lines,
    allow_numeric_labels,
):
    """
    PDF text-layer dumps of coordinate tables sometimes emit
    whole columns instead of rows: labels, then all Y, then all X,
    optionally all latitudes and longitudes.
    """

    labels = []
    kinds = []

    for line in lines:
        if is_ignorable_table_context_line(line):
            continue

        combined = parse_combined_geographic(line)
        if combined is not None:
            if order_utm(combined[0], combined[1]) is not None:
                return None

            kinds.append(("LAT", combined[0]))
            kinds.append(("LON", combined[1]))
            continue

        number = _numeric_line_value(line)
        if number is not None:
            if is_utm_easting(number):
                kinds.append(("Y", number))
            elif is_utm_northing(number):
                kinds.append(("X", number))
            elif 35 <= number <= 43:
                kinds.append(("LAT", number))
            elif 25 <= number <= 46:
                kinds.append(("LON", number))
            continue

        stripped = line.strip()
        if _looks_like_column_header(stripped):
            continue

        if is_label(stripped, allow_numeric_labels):
            labels.append(stripped)

    if len(kinds) < 6:
        return None

    kind_seq = [kind for kind, _ in kinds]
    values = [value for _, value in kinds]
    max_n = len(kinds) // 2

    for n in range(max_n, 2, -1):
        yx = ["Y"] * n + ["X"] * n
        xy = ["X"] * n + ["Y"] * n
        geo_orders = (
            [],
            ["LAT"] * n + ["LON"] * n,
            ["LON"] * n + ["LAT"] * n,
        )

        for start in range(0, len(kind_seq) - 2 * n + 1):
            prefix = kind_seq[start:start + 2 * n]
            if prefix not in (yx, xy):
                continue

            for geo in geo_orders:
                end = start + 2 * n + len(geo)
                if kind_seq[start:end] != prefix + geo:
                    continue
                if geo and end < len(kind_seq) and kind_seq[end] in geo[:1]:
                    continue

                window = list(
                    zip(
                        kind_seq[start:end],
                        values[start:end],
                    )
                )
                y_vals = [value for kind, value in window if kind == "Y"]
                x_vals = [value for kind, value in window if kind == "X"]
                lat_vals = [
                    value for kind, value in window if kind == "LAT"
                ]
                lon_vals = [
                    value for kind, value in window if kind == "LON"
                ]
                has_geo = len(lat_vals) == n and len(lon_vals) == n
                point_labels = (
                    labels[-n:]
                    if len(labels) >= n
                    else []
                )

                points = []
                for index in range(n):
                    latitude = None
                    longitude = None
                    if has_geo:
                        latitude, longitude = order_geographic(
                            y_vals[index],
                            x_vals[index],
                            lat_vals[index],
                            lon_vals[index],
                        )

                    if index < len(point_labels):
                        label = point_labels[index]
                    else:
                        label = f"P{index + 1}"

                    points.append(
                        {
                            "label": label,
                            "utm_y": y_vals[index],
                            "utm_x": x_vals[index],
                            "latitude": latitude,
                            "longitude": longitude,
                        }
                    )

                return points

    return None


def order_geographic(utm_y, utm_x, first, second):
    if is_valid_coordinate_block(
        utm_y,
        utm_x,
        first,
        second,
    ):
        return first, second

    if is_valid_coordinate_block(
        utm_y,
        utm_x,
        second,
        first,
    ):
        return second, first

    return first, second


def _looks_like_invalid_geographic_attempt(lines, start, utm_y, utm_x):
    """True when a numeric pair is present but is not valid lat/lon or UTM."""

    if start >= len(lines):
        return False

    combined = parse_combined_geographic(lines[start])
    if combined is not None:
        if order_utm(combined[0], combined[1]) is not None:
            return False
        latitude, longitude = order_geographic(
            utm_y,
            utm_x,
            combined[0],
            combined[1],
        )
        return not is_valid_coordinate_block(
            utm_y,
            utm_x,
            latitude,
            longitude,
        )

    first = _numeric_line_value(lines[start])
    if first is None:
        return False

    pos = start + 1
    if pos < len(lines) and lines[pos].strip() == ":":
        pos += 1
    if pos >= len(lines):
        return False

    second = _numeric_line_value(lines[pos])
    if second is None:
        return False

    if order_utm(first, second) is not None:
        return False

    latitude, longitude = order_geographic(
        utm_y,
        utm_x,
        first,
        second,
    )
    return not is_valid_coordinate_block(
        utm_y,
        utm_x,
        latitude,
        longitude,
    )


def _clean_numeric_token(token: str) -> str:
    text = (
        token.strip()
        .strip(":")
        .replace(" ", "")
    )

    if (
        re.fullmatch(
            r"[+-]?\d{1,3}(?:\.\d{3}){2,}(?:,\d+)?",
            text,
        )
        or re.fullmatch(
            r"[+-]?\d{1,3}(?:\.\d{3})+,\d+",
            text,
        )
        or re.fullmatch(
            r"[+-]?\d{1,3}(?:,\d{3}){2,}(?:\.\d+)?",
            text,
        )
        or re.fullmatch(
            r"[+-]?\d{1,3}(?:,\d{3})+\.\d+",
            text,
        )
    ):
        return format(
            parse_localized_number(text),
            "f",
        )

    return text.replace(",", ".")

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
        if not is_number(token):
            direct_values.append(None)
            continue

        try:
            direct_values.append(
                parse_localized_number(token)
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

    for x_start, utm_x in enumerate(
        direct_values
    ):
        if (
            utm_x is None
            or not 3000000 <= utm_x <= 5000000
        ):
            continue

        for y_start in range(
            x_start + 1,
            min(x_start + 4, token_count),
        ):
            utm_y = direct_values[y_start]

            if (
                utm_y is None
                or not 100000 <= utm_y <= 999999
            ):
                continue

            after_utm = y_start + 1

            for lat_start in range(
                after_utm,
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
                        "label_end": x_start,
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

            return {
                "label_end": y_start,
                "utm_y": utm_y,
                "utm_x": utm_x,
                "latitude": None,
                "longitude": None,
            }

    for x_start, utm_x in enumerate(
        direct_values
    ):
        if (
            utm_x is None
            or not 3000000 <= utm_x <= 5000000
        ):
            continue

        for y_start in range(
            x_start + 1,
            min(x_start + 4, token_count),
        ):
            utm_y = direct_values[y_start]

            if (
                utm_y is None
                or not 100000 <= utm_y <= 999999
            ):
                continue

            return {
                "label_end": x_start,
                "utm_y": utm_y,
                "utm_x": utm_x,
                "latitude": None,
                "longitude": None,
            }

    for y_start in range(token_count):
        for y_end, utm_y in _join_numeric_fragments(
            tokens,
            y_start,
            max_parts=3,
        ):
            if not 100000 <= utm_y <= 999999:
                continue

            for x_start in range(
                y_end,
                min(y_end + 3, token_count),
            ):
                for x_end, utm_x in _join_numeric_fragments(
                    tokens,
                    x_start,
                    max_parts=3,
                ):
                    if not 3000000 <= utm_x <= 5000000:
                        continue

                    return {
                        "label_end": y_start,
                        "utm_y": utm_y,
                        "utm_x": utm_x,
                        "latitude": None,
                        "longitude": None,
                    }

    for x_start in range(token_count):
        for x_end, utm_x in _join_numeric_fragments(
            tokens,
            x_start,
            max_parts=3,
        ):
            if not 3000000 <= utm_x <= 5000000:
                continue

            for y_start in range(
                x_end,
                min(x_end + 3, token_count),
            ):
                for _y_end, utm_y in _join_numeric_fragments(
                    tokens,
                    y_start,
                    max_parts=3,
                ):
                    if not 100000 <= utm_y <= 999999:
                        continue

                    return {
                        "label_end": x_start,
                        "utm_y": utm_y,
                        "utm_x": utm_x,
                        "latitude": None,
                        "longitude": None,
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

    tokens = _merge_space_grouped_thousands(
        [
            token.strip()
            for token in line.split()
            if token.strip()
        ]
    )

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


def _expand_combined_tokens(tokens):
    expanded = []

    for token in tokens:
        combined = parse_combined_geographic(token)
        if combined is not None:
            expanded.append(str(combined[0]))
            expanded.append(str(combined[1]))
        else:
            expanded.append(token)

    return expanded


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

    tokens = _expand_combined_tokens(
        _merge_space_grouped_thousands(
            [
                token.strip()
                for token in line.split()
                if token.strip()
            ]
        )
    )

    if len(tokens) < 3:
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

    if latitude is None or longitude is None:
        if not is_valid_utm_pair(utm_y, utm_x):
            return None
    elif not is_valid_coordinate_block(
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
        or "UTM" in upper_text
        or "SAĞA" in upper_text
        or "SAGA" in upper_text
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
            r"^\s*(\d+)\s+NO\.?\s*LU\s+(.+)$",
            r"^\s*(\d+)\s+NOLU\s+(.+)$",
            r"^\s*POLIGON\s*[-.:]?\s*(\d+)\b(.*)$",
        ]

        for pattern in patterns:
            match = re.search(
                pattern,
                normalized,
            )

            if match:
                rest_raw = match.group(2).strip()
                rest_tokens = [
                    token
                    for token in re.sub(
                        r"[^A-Z0-9]+",
                        " ",
                        rest_raw,
                    ).split()
                    if token
                ]
                has_vertex_rest = any(
                    token in {"KOSE", "SINIR", "VERTEX"}
                    or token.startswith("NOKTA")
                    for token in rest_tokens
                )
                has_area_rest = any(
                    token in {
                        "POLIGON",
                        "POLIGONU",
                        "ALAN",
                        "ALANI",
                        "SAHA",
                        "SAHASI",
                        "TESIS",
                        "TESISI",
                        "OCAK",
                        "PASA",
                        "STOK",
                        "DEPO",
                        "HAVUZ",
                        "GALERI",
                        "BAND",
                        "BANDI",
                        "BACALARI",
                        "RUHSAT",
                        "CED",
                        "PROJE",
                    }
                    or token.startswith("POLIGON")
                    or token.startswith("ALAN")
                    for token in rest_tokens
                )
                # "1 NOLU NOKTA" is a vertex label, not a polygon heading.
                # Treating it as POLIGON_n splits a 6-point ring into six
                # 1-vertex groups and export becomes poly=0.
                if has_vertex_rest and not has_area_rest:
                    return None

                number = match.group(1)
                rest = re.sub(
                    r"[^A-Z0-9]+",
                    "_",
                    rest_raw,
                ).strip("_")[:32]

                group_name = f"POLIGON_{number}"
                if rest:
                    group_name = f"{group_name}_{rest}"

                return (
                    group_name,
                    line.strip(),
                )

        return None

    def detect_generic_area_heading(line):
        value = str(line).strip()

        if len(value) < 8 or len(value) > 90:
            return None

        normalized = (
            value.upper()
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        if not re.search(
            r"\b(ALANI|SAHASI|BANDI|TESISI|BACALARI|POLIGONU)\b",
            normalized,
        ):
            return None

        if re.search(
            r"\b(SEKIL|TABLO|CIZELGE|KOORDINAT SIRASI|RAPORU)\b",
            normalized,
        ):
            return None

        has_measure = re.search(
            r"\(\s*[\d.,]+\s*(?:HA|M2|M)\)",
            normalized,
        )
        has_nolu = re.search(
            r"\b\d+\s+NO",
            normalized,
        )

        if not has_measure and not has_nolu:
            return None

        slug = re.sub(
            r"[^A-Z0-9]+",
            "_",
            normalized,
        ).strip("_")[:48]

        if not slug:
            return None

        return (
            f"HEADING_{slug}",
            value,
        )

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
    segment_start_index = 0
    segment_has_polygon_heading = False
    pending_area_heading_lines = []

    def is_pending_area_heading_line(
        line,
        point,
    ):
        if point is not None:
            return False

        value = str(line).strip()

        if not value or len(value) > 80:
            return False

        return bool(
            re.search(
                r"[A-Za-zÇĞİÖŞÜçğıöşü]",
                value,
            )
        )

    def detect_pending_area_type(line):
        value = str(line).strip()
        detected = detect_area_type(value)

        if detected is not None:
            return detected

        normalized = (
            value.upper()
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        if not any(
            boundary in normalized
            for boundary in (
                "ALAN",
                "SAHA",
                "DEPO",
                "KOORDINAT",
                "SINIR",
            )
        ):
            return None

        for count in range(
            1,
            len(pending_area_heading_lines) + 1,
        ):
            candidate = " ".join(
                pending_area_heading_lines[-count:]
                + [value]
            )
            detected = detect_area_type(
                candidate
            )

            if detected is not None:
                return detected

        return None

    for line_index, line in enumerate(lines):
        if is_ignorable_table_context_line(line):
            pending_area_heading_lines.clear()
            continue

        point = parse_row_coordinate(
            line,
            allow_numeric_labels,
        )

        if point is None:
            point = recover_row_coordinate_from_values(
                line
            )

        detected_group = detect_polygon_group(
            line
        )

        if detected_group is None:
            detected_group = detect_generic_area_heading(
                line
            )

        if detected_group is not None:
            pending_area_heading_lines.clear()

        detected_area_type = (
            detect_pending_area_type(line)
        )

        if detected_area_type is not None:
            pending_area_heading_lines.clear()
            current_area_type = (
                detected_area_type
            )

            segment_has_points = (
                len(results)
                > segment_start_index
            )

            if point is not None and segment_has_points:
                for previous_point in results[
                    segment_start_index:
                ]:
                    previous_point[
                        "table_type_override"
                    ] = detected_area_type

            preserve_explicit_empty_segment = (
                point is None
                and segment_has_polygon_heading
                and not segment_has_points
            )

            if (
                not preserve_explicit_empty_segment
                and (
                    point is None
                    or not (
                        segment_has_points
                        or segment_has_polygon_heading
                    )
                )
            ):
                current_polygon_group = "DEFAULT"
                current_polygon_heading = ""

            if point is None:
                segment_start_index = len(
                    results
                )

                if not preserve_explicit_empty_segment:
                    segment_has_polygon_heading = False

        if detected_group is not None:
            (
                current_polygon_group,
                current_polygon_heading,
            ) = detected_group

            segment_start_index = len(
                results
            )
            segment_has_polygon_heading = True

            continue

        if point is None:
            if detected_area_type is not None:
                continue

            if is_pending_area_heading_line(
                line,
                point,
            ):
                pending_area_heading_lines.append(
                    line
                )
                del pending_area_heading_lines[:-3]
            else:
                pending_area_heading_lines.clear()

            continue

        pending_area_heading_lines.clear()

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
            if detected_area_type is not None:
                segment_start_index = len(
                    results
                )
                segment_has_polygon_heading = False

            continue

        seen.add(
            key
        )

        results.append(
            point
        )

        if detected_area_type is not None:
            segment_start_index = len(
                results
            )
            segment_has_polygon_heading = False

    # =========================================================
    # 2. YÖNTEM
    # ESKİ 5 SATIRLIK BLOK YAPISI
    # =========================================================

    i = 0

    current_polygon_group = "DEFAULT"
    current_polygon_heading = ""
    current_area_type = None
    unnamed_point_serial = 0
    pending_area_heading_lines = []

    def detect_method2_area_type(line):
        detected = detect_area_type(line)

        if detected is not None:
            return detected

        value = str(line).strip()
        normalized = (
            value.upper()
            .replace("İ", "I")
            .replace("Ş", "S")
            .replace("Ğ", "G")
            .replace("Ü", "U")
            .replace("Ö", "O")
            .replace("Ç", "C")
        )

        if not any(
            boundary in normalized
            for boundary in (
                "ALAN",
                "SAHA",
                "DEPO",
                "KOORDINAT",
                "SINIR",
            )
        ):
            return None

        for count in range(
            1,
            len(pending_area_heading_lines) + 1,
        ):
            candidate = " ".join(
                pending_area_heading_lines[-count:]
                + [value]
            )
            detected = detect_area_type(
                candidate
            )

            if detected is not None:
                return detected

        return None

    while i < len(lines):
        line = lines[i]

        if is_ignorable_table_context_line(line):
            pending_area_heading_lines.clear()
            i += 1
            continue

        # Satırlar ilerlerken alan türünü güncelle (ikinci yöntem için).
        detected_area_type = detect_method2_area_type(
            line
        )

        if detected_area_type is not None:
            pending_area_heading_lines.clear()
            current_area_type = (
                detected_area_type
            )

            current_polygon_group = "DEFAULT"
            current_polygon_heading = ""

        detected_group = detect_polygon_group(
            line
        )

        if detected_group is None:
            detected_group = detect_generic_area_heading(
                line
            )

        if detected_group is not None:
            (
                current_polygon_group,
                current_polygon_heading,
            ) = detected_group

            i += 1
            continue

        unlabeled_run = parse_unlabeled_utm_geo_runs(
            lines,
            i,
        )
        parsed_points = []
        consumed = 0
        if unlabeled_run is not None:
            consumed = unlabeled_run["consumed"]
            for utm_y, utm_x, latitude, longitude in unlabeled_run["points"]:
                unnamed_point_serial += 1
                parsed_points.append(
                    {
                        "label": f"P{unnamed_point_serial}",
                        "utm_y": utm_y,
                        "utm_x": utm_x,
                        "latitude": latitude,
                        "longitude": longitude,
                    }
                )
        else:
            parsed = parse_point_at(
                lines,
                i,
                allow_numeric_labels,
            )
            if parsed is not None:
                consumed = parsed["consumed"]
                label = parsed["label"]
                if not label:
                    unnamed_point_serial += 1
                    label = f"P{unnamed_point_serial}"
                parsed_points.append(
                    {
                        "label": label,
                        "utm_y": parsed["utm_y"],
                        "utm_x": parsed["utm_x"],
                        "latitude": parsed["latitude"],
                        "longitude": parsed["longitude"],
                    }
                )

        if not parsed_points:
            value = str(line).strip()

            if (
                detected_area_type is None
                and value
                and len(value) <= 80
                and re.search(
                    r"[A-Za-zÇĞİÖŞÜçğıöşü]",
                    value,
                )
            ):
                pending_area_heading_lines.append(
                    line
                )
                del pending_area_heading_lines[:-3]
            elif detected_area_type is None:
                pending_area_heading_lines.clear()

            i += 1
            continue

        pending_area_heading_lines.clear()

        for parsed in parsed_points:
            normalized_label = normalize_ocr_label(
                parsed["label"]
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
                "utm_y": parsed["utm_y"],
                "utm_x": parsed["utm_x"],
                "latitude": parsed["latitude"],
                "longitude": parsed["longitude"],
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

        i += consumed

    if not results:
        column_points = parse_column_major_coordinates(
            lines,
            allow_numeric_labels,
        ) or []

        current_polygon_group = "DEFAULT"
        current_polygon_heading = ""
        current_area_type = None

        for line in lines:
            if is_ignorable_table_context_line(line):
                continue
            detected_area_type = detect_area_type(line)
            if detected_area_type is not None:
                current_area_type = detected_area_type
            detected_group = detect_polygon_group(line)
            if detected_group is None:
                detected_group = detect_generic_area_heading(line)
            if detected_group is not None:
                (
                    current_polygon_group,
                    current_polygon_heading,
                ) = detected_group

        for parsed in column_points:
            normalized_label = normalize_ocr_label(
                parsed["label"]
            )
            label_group = detect_group_from_label(
                normalized_label
            )

            if current_polygon_group != "DEFAULT":
                polygon_group = current_polygon_group
                polygon_heading = current_polygon_heading
            elif label_group:
                polygon_group = label_group
                polygon_heading = label_group
            else:
                polygon_group = "DEFAULT"
                polygon_heading = ""

            point = {
                "label": normalized_label,
                "utm_y": parsed["utm_y"],
                "utm_x": parsed["utm_x"],
                "latitude": parsed["latitude"],
                "longitude": parsed["longitude"],
                "polygon_group": polygon_group,
                "polygon_heading": polygon_heading,
                "table_type_override": current_area_type,
                "source_page": None,
                "source_method": None,
            }

            key = (
                point["polygon_group"],
                point["label"],
                point["utm_y"],
                point["utm_x"],
            )

            if key in seen:
                continue

            seen.add(key)
            results.append(point)

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

        stripped = normalized.strip()

        if stripped.startswith("SEKIL"):
            return None

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
            "CED" in normalized
            and any(
                token in normalized
                for token in (
                    "ALAN",
                    "SAHA",
                    "SINIR",
                    "POLIGON",
                    "KOORDINAT",
                    "IZIN",
                )
            )
        ):
            if re.search(r"\bMEVCUT\b", normalized):
                return "MEVCUT_CED_ALANI"

            if (
                re.search(r"\bYENI\b", normalized)
                or "TALEP EDILEN" in normalized
                or "PROJEYE KONU" in normalized
                or "PLANLANAN" in normalized
                or "ONGORULEN" in normalized
            ):
                return "YENI_CED_ALANI"

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
            "TOPRAK" in normalized
            and "DEPO" in normalized
        ):
            return "DEPOLAMA_ALANI"

        if (
            "PASA" in normalized
            and "DOKUM" in normalized
        ):
            return "PASA_ALANI"

        if (
            "PASA" in normalized
            and (
                "DEPO" in normalized
                or "ALAN" in normalized
            )
        ):
            return "PASA_ALANI"

        if (
            "URUN STOK" in normalized
            or "CEVHER STOK" in normalized
            or "TUVENAN" in normalized
            or "STOK ALANI" in normalized
            or "STOK SAHASI" in normalized
        ):
            return "STOK_ALANI"

        if "SANTIYE ALANI" in normalized:
            return "SANTIYE_ALANI"

        if "OCAK ALANI" in normalized or "OCAK SAHASI" in normalized:
            return "OCAK_ALANI"

        if "GALERI" in normalized and (
            "ALAN" in normalized
            or "AGZI" in normalized
            or "GIRIS" in normalized
        ):
            return "GALERI_ALANI"

        if "TESIS ALANI" in normalized:
            return "TESIS_ALANI"

        if (
            "DOLGU" in normalized
            and "TESIS" in normalized
        ):
            return "TESIS_ALANI"

        if (
            "SAGLIK" in normalized
            and "KORUMA" in normalized
        ):
            return "CALISILMAYACAK_ALAN"

        if (
            "KIRMA" in normalized
            and "ELEME" in normalized
            and "ALAN" in normalized
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
