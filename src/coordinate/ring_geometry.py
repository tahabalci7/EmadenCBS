"""Small ring helpers for self-intersecting (kelebek / bow-tie) polygons."""


def collapse_consecutive_duplicates(points, tolerance=0.01):
    """Drop consecutive vertices that are the same location."""

    if not points:
        return []

    cleaned = [points[0]]
    tolerance_squared = tolerance ** 2

    for point in points[1:]:
        previous = cleaned[-1]
        if _distance_squared(previous, point) <= tolerance_squared:
            continue
        cleaned.append(point)

    if (
        len(cleaned) >= 2
        and _distance_squared(cleaned[0], cleaned[-1]) <= tolerance_squared
    ):
        cleaned.pop()

    return cleaned


def ring_is_simple(points, tolerance=0.01):
    return not find_bowtie_edge_pair(
        collapse_consecutive_duplicates(points, tolerance)
    )


def find_bowtie_edge_pair(points):
    """
    Return (i, j) for the first pair of non-adjacent edges
    that properly intersect. Adjacent edges that only share
    a vertex are ignored.
    """

    count = len(points)

    if count < 4:
        return None

    for i in range(count):
        a1 = points[i]
        a2 = points[(i + 1) % count]

        if _is_zero_length(a1, a2):
            continue

        for offset in range(2, count - 1):
            j = (i + offset) % count

            if j <= i:
                continue

            # Closed-ring first/last edges are adjacent.
            if i == 0 and j == count - 1:
                continue

            b1 = points[j]
            b2 = points[(j + 1) % count]

            if _is_zero_length(b1, b2):
                continue

            if _segments_properly_intersect(a1, a2, b1, b2):
                return (i, j)

    return None


def repair_self_intersecting_ring(points, tolerance=0.01):
    """
    Uncross a single bow-tie by reversing the vertex run
    between the two crossing edges. Simple rings are unchanged.
    """

    working = collapse_consecutive_duplicates(
        points,
        tolerance,
    )

    if len(working) < 4:
        return list(points)

    crossing = find_bowtie_edge_pair(working)

    if crossing is None:
        return list(points)

    start, end = crossing
    repaired = working[:start + 1] + list(
        reversed(working[start + 1:end + 1])
    ) + working[end + 1:]

    if find_bowtie_edge_pair(repaired) is not None:
        return list(points)

    if _ring_was_closed(points, tolerance):
        repaired = list(repaired)
        repaired.append(
            {
                **repaired[0],
            }
        )

    return repaired


def _ring_was_closed(points, tolerance):
    if len(points) < 2:
        return False

    return _distance_squared(points[0], points[-1]) <= tolerance ** 2


def _xy(point):
    return (
        float(point["y"]),
        float(point["x"]),
    )


def _distance_squared(point_a, point_b):
    y_a, x_a = _xy(point_a)
    y_b, x_b = _xy(point_b)
    return (y_a - y_b) ** 2 + (x_a - x_b) ** 2


def _is_zero_length(point_a, point_b, tolerance=1e-9):
    return _distance_squared(point_a, point_b) <= tolerance ** 2


def _segments_properly_intersect(a1, a2, b1, b2):
    """True only for an interior crossing, not a shared endpoint."""

    p1 = _xy(a1)
    p2 = _xy(a2)
    p3 = _xy(b1)
    p4 = _xy(b2)

    if p1 == p3 or p1 == p4 or p2 == p3 or p2 == p4:
        return False

    orientation_1 = _orientation(p1, p2, p3)
    orientation_2 = _orientation(p1, p2, p4)
    orientation_3 = _orientation(p3, p4, p1)
    orientation_4 = _orientation(p3, p4, p2)

    if (
        orientation_1 == 0
        or orientation_2 == 0
        or orientation_3 == 0
        or orientation_4 == 0
    ):
        return False

    return (
        orientation_1 != orientation_2
        and orientation_3 != orientation_4
    )


def _orientation(p, q, r):
    value = (
        (q[1] - p[1]) * (r[0] - q[0])
        - (q[0] - p[0]) * (r[1] - q[1])
    )

    if abs(value) <= 1e-9:
        return 0

    return 1 if value > 0 else 2
