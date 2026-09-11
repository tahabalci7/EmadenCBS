"""Small ring helpers for self-intersecting (kelebek / bow-tie) polygons.

Repair policy
-------------
``repair_self_intersecting_rings`` keeps simple and concave rings unchanged.

1. Collapse consecutive duplicate vertices.
2. Iteratively uncross: reverse the vertex run between the first remaining
   proper intersection (the original single bow-tie repair). Stop on a simple
   ring, a repeated vertex sequence (cycle), or an iteration cap.
3. If crossings remain, split at each remaining proper intersection into
   simple closed parts. Distinct polygon groups are never merged; one ring
   may become several simple parts.

``repair_self_intersecting_ring`` is the single-ring helper used by tests:
it returns the iteratively uncrossed ring when that ring is simple, otherwise
the original vertices (it does not split). PolygonBuilder uses the plural API.
"""


MAX_UNCROSS_ITERATIONS = 64
MAX_SPLIT_DEPTH = 64
_AREA_EPSILON = 1e-6


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


def count_ring_crossings(points, tolerance=0.01):
    return len(
        find_all_bowtie_edge_pairs(
            collapse_consecutive_duplicates(points, tolerance)
        )
    )


def find_bowtie_edge_pair(points):
    """
    Return (i, j) for the first pair of non-adjacent edges
    that properly intersect. Adjacent edges that only share
    a vertex are ignored.
    """

    pairs = find_all_bowtie_edge_pairs(points)
    if not pairs:
        return None
    return pairs[0]


def find_all_bowtie_edge_pairs(points):
    """All non-adjacent proper intersections as (i, j) with i < j."""

    count = len(points)
    pairs = []

    if count < 4:
        return pairs

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
                pairs.append((i, j))

    return pairs


def repair_self_intersecting_ring(points, tolerance=0.01):
    """
    Uncross by reversing vertex runs between crossing edges.
    Simple rings are unchanged. Multi-cross rings that stay
    intersecting after iteration are left as-is; use
    ``repair_self_intersecting_rings`` to split them.
    """

    was_closed = _ring_was_closed(points, tolerance)
    working = collapse_consecutive_duplicates(
        points,
        tolerance,
    )

    if len(working) < 4:
        return list(points)

    crossing = find_bowtie_edge_pair(working)

    if crossing is None:
        return list(points)

    working = _uncross_until_simple(
        working,
        tolerance,
    )

    if find_bowtie_edge_pair(working) is not None:
        return list(points)

    return _restore_closed(working, was_closed)


def repair_self_intersecting_rings(points, tolerance=0.01):
    """
    Return one or more simple rings.

    Prefer iterative uncross (keeps a single polygon when vertex
    order was merely twisted). If crossings remain, split into
    simple parts rather than emitting a kelebek ring.
    """

    if not points:
        return []

    was_closed = _ring_was_closed(points, tolerance)
    working = collapse_consecutive_duplicates(
        points,
        tolerance,
    )

    if len(working) < 3:
        return []

    if find_bowtie_edge_pair(working) is None:
        return [_restore_closed(working, was_closed)]

    uncrossed = _uncross_until_simple(
        working,
        tolerance,
    )

    if find_bowtie_edge_pair(uncrossed) is None:
        return [_restore_closed(uncrossed, was_closed)]

    simple_parts = []
    for part in _split_into_simple_rings(uncrossed, 0):
        cleaned = collapse_consecutive_duplicates(
            part,
            tolerance,
        )
        if len(cleaned) < 3:
            continue
        if find_bowtie_edge_pair(cleaned) is not None:
            continue
        if _ring_area(cleaned) <= _AREA_EPSILON:
            continue
        simple_parts.append(
            _restore_closed(cleaned, was_closed)
        )

    return simple_parts


def _uncross_until_simple(points, tolerance):
    working = list(points)
    seen_states = set()

    for _ in range(MAX_UNCROSS_ITERATIONS):
        state = _ring_state_key(working, tolerance)
        if state in seen_states:
            break
        seen_states.add(state)

        crossing = find_bowtie_edge_pair(working)
        if crossing is None:
            break

        working = _uncross_once(working, crossing)

    return working


def _uncross_once(points, crossing):
    start, end = crossing
    return (
        points[:start + 1]
        + list(reversed(points[start + 1:end + 1]))
        + points[end + 1:]
    )


def _split_into_simple_rings(points, depth):
    working = list(points)

    if depth > MAX_SPLIT_DEPTH:
        if find_bowtie_edge_pair(working) is None and len(working) >= 3:
            return [working]
        return []

    if len(working) < 4:
        if len(working) >= 3 and find_bowtie_edge_pair(working) is None:
            return [working]
        return []

    crossing = find_bowtie_edge_pair(working)
    if crossing is None:
        return [working]

    parts = _split_once(working, crossing)
    if parts is None:
        return []

    result = []
    for part in parts:
        result.extend(
            _split_into_simple_rings(part, depth + 1)
        )
    return result


def _split_once(points, crossing):
    start, end = crossing
    a1 = points[start]
    a2 = points[(start + 1) % len(points)]
    b1 = points[end]
    b2 = points[(end + 1) % len(points)]

    cross = _segment_intersection_point(a1, a2, b1, b2)
    if cross is None:
        return None

    ring_a = points[:start + 1] + [cross] + points[end + 1:]
    ring_b = [cross] + points[start + 1:end + 1]

    parts = []
    for ring in (ring_a, ring_b):
        cleaned = collapse_consecutive_duplicates(ring)
        if len(cleaned) >= 3:
            parts.append(cleaned)

    if len(parts) < 2:
        return None

    return parts


def _restore_closed(points, was_closed):
    restored = list(points)
    if was_closed and restored:
        restored.append(
            {
                **restored[0],
            }
        )
    return restored


def _ring_was_closed(points, tolerance):
    if len(points) < 2:
        return False

    return _distance_squared(points[0], points[-1]) <= tolerance ** 2


def _ring_state_key(points, tolerance):
    quantize = max(tolerance, 0.01)
    return tuple(
        (
            round(float(point["y"]) / quantize),
            round(float(point["x"]) / quantize),
        )
        for point in points
    )


def _ring_area(points):
    if len(points) < 3:
        return 0.0

    area = 0.0
    count = len(points)
    for index in range(count):
        y1, x1 = _xy(points[index])
        y2, x2 = _xy(points[(index + 1) % count])
        area += y1 * x2
        area -= y2 * x1

    return abs(area) / 2.0


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


def _segment_intersection_point(a1, a2, b1, b2):
    p1 = _xy(a1)
    p2 = _xy(a2)
    p3 = _xy(b1)
    p4 = _xy(b2)

    denominator = (
        (p1[0] - p2[0]) * (p3[1] - p4[1])
        - (p1[1] - p2[1]) * (p3[0] - p4[0])
    )

    if abs(denominator) <= 1e-18:
        return None

    t = (
        (p1[0] - p3[0]) * (p3[1] - p4[1])
        - (p1[1] - p3[1]) * (p3[0] - p4[0])
    ) / denominator

    if t <= 1e-9 or t >= 1 - 1e-9:
        return None

    easting = p1[0] + t * (p2[0] - p1[0])
    northing = p1[1] + t * (p2[1] - p1[1])

    point = dict(a1)
    point["y"] = easting
    point["x"] = northing
    point["name"] = "X"
    point["latitude"] = _interpolate_numeric(
        a1,
        a2,
        t,
        "latitude",
    )
    point["longitude"] = _interpolate_numeric(
        a1,
        a2,
        t,
        "longitude",
    )
    point["transformed_latitude"] = _interpolate_numeric(
        a1,
        a2,
        t,
        "transformed_latitude",
    )
    point["transformed_longitude"] = _interpolate_numeric(
        a1,
        a2,
        t,
        "transformed_longitude",
    )
    return point


def _interpolate_numeric(point_a, point_b, t, field):
    value_a = point_a.get(field)
    value_b = point_b.get(field)

    if value_a in (None, "") or value_b in (None, ""):
        return None

    try:
        start = float(value_a)
        end = float(value_b)
    except (TypeError, ValueError):
        return None

    return start + t * (end - start)
