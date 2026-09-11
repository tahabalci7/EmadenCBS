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
4. KML lon/lat repair must not export leftover multi-cross rings on compact
   degree-scale polygons (span ≪ 0.01°). Still-crossing remainders are
   force-split or replaced by a simple hull. A still-crossing original
   ring is never the KML output.

``repair_self_intersecting_ring`` is the single-ring helper used by tests:
it returns the iteratively uncrossed ring when that ring is simple, otherwise
the original vertices (it does not split). PolygonBuilder uses the plural API.
"""


MAX_UNCROSS_ITERATIONS = 64
MAX_SPLIT_DEPTH = 64
_AREA_EPSILON = 1e-6
METRE_COLLAPSE_TOLERANCE = 0.01
DEGREE_COLLAPSE_TOLERANCE = 1e-12
GEOGRAPHIC_ABS_LIMIT = 180.0


def inferred_ring_tolerance(points):
    """Collapse tolerance from coordinate magnitude, not from a caller guess.

    UTM easting/northing uses ~0.01 m. Lon/lat rings are degree-scale; a
    metre-style 0.01 collapse is 0.01° and smashes small ÇED polygons.
    """

    if not points:
        return METRE_COLLAPSE_TOLERANCE

    max_abs = 0.0
    for point in points:
        max_abs = max(
            max_abs,
            abs(float(point["y"])),
            abs(float(point["x"])),
        )

    if max_abs <= GEOGRAPHIC_ABS_LIMIT:
        return DEGREE_COLLAPSE_TOLERANCE
    return METRE_COLLAPSE_TOLERANCE


def _resolved_tolerance(points, tolerance):
    if tolerance is None:
        return inferred_ring_tolerance(points)
    return tolerance


def _geometry_epsilon(tolerance):
    """Orientation / zero-length epsilon matching the ring's units.

    Metre rings keep 1e-9 m. Degree rings must not use 1e-9° (~0.11 m);
    that treats shallow compact ÇED crossings as collinear and leaves
    leftover kelebek rings in KML.
    """

    if tolerance is None or tolerance >= 0.001:
        return 1e-9
    return 1e-18


def collapse_consecutive_duplicates(points, tolerance=None):
    """Drop consecutive vertices that are the same location."""

    tolerance = _resolved_tolerance(points, tolerance)

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


def ring_is_simple(points, tolerance=None):
    tolerance = _resolved_tolerance(points, tolerance)
    return not find_bowtie_edge_pair(
        collapse_consecutive_duplicates(points, tolerance),
        tolerance,
    )


def count_ring_crossings(points, tolerance=None):
    tolerance = _resolved_tolerance(points, tolerance)
    return len(
        find_all_bowtie_edge_pairs(
            collapse_consecutive_duplicates(points, tolerance),
            tolerance,
        )
    )


def find_bowtie_edge_pair(points, tolerance=None):
    """
    Return (i, j) for the first pair of non-adjacent edges
    that properly intersect. Adjacent edges that only share
    a vertex are ignored.
    """

    pairs = find_all_bowtie_edge_pairs(points, tolerance)
    if not pairs:
        return None
    return pairs[0]


def find_all_bowtie_edge_pairs(points, tolerance=None):
    """All non-adjacent proper intersections as (i, j) with i < j."""

    count = len(points)
    pairs = []

    if count < 4:
        return pairs

    tolerance = _resolved_tolerance(points, tolerance)
    epsilon = _geometry_epsilon(tolerance)

    for i in range(count):
        a1 = points[i]
        a2 = points[(i + 1) % count]

        if _is_zero_length(a1, a2, epsilon):
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

            if _is_zero_length(b1, b2, epsilon):
                continue

            if _segments_properly_intersect(
                a1, a2, b1, b2, epsilon
            ):
                pairs.append((i, j))

    return pairs


def repair_self_intersecting_ring(points, tolerance=None):
    """
    Uncross by reversing vertex runs between crossing edges.
    Simple rings are unchanged. Multi-cross rings that stay
    intersecting after iteration are left as-is; use
    ``repair_self_intersecting_rings`` to split them.
    """

    tolerance = _resolved_tolerance(points, tolerance)
    was_closed = _ring_was_closed(points, tolerance)
    working = collapse_consecutive_duplicates(
        points,
        tolerance,
    )

    if len(working) < 4:
        return list(points)

    crossing = find_bowtie_edge_pair(working, tolerance)

    if crossing is None:
        return list(points)

    working = _uncross_until_simple(
        working,
        tolerance,
    )

    if find_bowtie_edge_pair(working, tolerance) is not None:
        return list(points)

    return _restore_closed(working, was_closed)


def repair_self_intersecting_rings(points, tolerance=None):
    """
    Return one or more simple rings.

    Prefer iterative uncross (keeps a single polygon when vertex
    order was merely twisted). If crossings remain, split into
    simple parts rather than emitting a kelebek ring.
    """

    if not points:
        return []

    tolerance = _resolved_tolerance(points, tolerance)
    was_closed = _ring_was_closed(points, tolerance)
    working = collapse_consecutive_duplicates(
        points,
        tolerance,
    )

    if len(working) < 3:
        return []

    if find_bowtie_edge_pair(working, tolerance) is None:
        return [_restore_closed(working, was_closed)]

    uncrossed = _uncross_until_simple(
        working,
        tolerance,
    )

    if find_bowtie_edge_pair(uncrossed, tolerance) is None:
        return [_restore_closed(uncrossed, was_closed)]

    simple_parts = _collect_simple_parts(
        uncrossed,
        was_closed,
        tolerance,
    )

    if not simple_parts:
        simple_parts = _collect_simple_parts(
            working,
            was_closed,
            tolerance,
        )

    if simple_parts:
        return simple_parts

    # Never drop a ring because split failed; KML-space
    # repair can still uncross lon/lat independently.
    return [_restore_closed(uncrossed, was_closed)]


def repair_lonlat_rings(pairs, tolerance=1e-12):
    """
    Repair a KML lon/lat ring independently of UTM y/x.

    Vertex order that is simple in projected metres can still
    self-intersect in WGS84. KML scanners see lon/lat, so this
    pass uses those coordinates. Degree tolerance is tiny so
    distinct vertices are not collapsed.

    Compact multi-cross leftovers (span ≪ 0.01°) are split
    again rather than exported as kelebek rings. A still-crossing
    remainder is forced split or replaced by a simple hull; a
    crossing ring is never the KML output.
    """

    if len(pairs) < 3:
        return [list(pairs)] if pairs else []

    pending = [list(pairs)]
    repaired = []
    seen = set()

    for _ in range(MAX_SPLIT_DEPTH):
        if not pending:
            break

        current = pending.pop(0)
        state = tuple(current)
        if state in seen:
            _resolve_lonlat_leftover(
                current,
                repaired,
                pending,
                seen,
                tolerance,
            )
            continue
        seen.add(state)

        if count_lonlat_crossings(current, tolerance) == 0:
            repaired.append(current)
            continue

        points = [
            {
                "name": f"P{index}",
                "y": longitude,
                "x": latitude,
            }
            for index, (longitude, latitude) in enumerate(current)
        ]

        rings = repair_self_intersecting_rings(
            points,
            tolerance,
        )

        if not rings:
            _resolve_lonlat_leftover(
                current,
                repaired,
                pending,
                seen,
                tolerance,
            )
            continue

        converted = [
            [
                (point["y"], point["x"])
                for point in ring
            ]
            for ring in rings
        ]

        progressed = False
        for pairs_out in converted:
            if count_lonlat_crossings(pairs_out, tolerance) == 0:
                repaired.append(pairs_out)
                progressed = True
                continue
            if tuple(pairs_out) == state:
                continue
            pending.append(pairs_out)
            progressed = True

        if not progressed:
            _resolve_lonlat_leftover(
                current,
                repaired,
                pending,
                seen,
                tolerance,
            )

    for current in pending:
        _resolve_lonlat_leftover(
            current,
            repaired,
            None,
            seen,
            tolerance,
        )

    simple = [
        ring
        for ring in repaired
        if count_lonlat_crossings(ring, tolerance) == 0
    ]
    if simple:
        return simple

    hull = _convex_hull_pairs(pairs)
    if hull and count_lonlat_crossings(hull, tolerance) == 0:
        return [hull]
    return []


def count_lonlat_crossings(pairs, tolerance=1e-12):
    points = [
        {
            "name": f"P{index}",
            "y": longitude,
            "x": latitude,
        }
        for index, (longitude, latitude) in enumerate(pairs)
    ]
    return count_ring_crossings(points, tolerance)


def _resolve_lonlat_leftover(
    current,
    repaired,
    pending,
    seen,
    tolerance,
    depth=0,
):
    """Finish a leftover ring: simple parts or a simple hull, never kelebek.

    Still-crossing split parts are resolved recursively instead of being
    parked on a throwaway queue. That queue used to be discarded at the
    end of ``repair_lonlat_rings``, which re-exported the original compact
    ring (~95 vertices, a handful of leftover crossings) in KML.
    """

    if count_lonlat_crossings(current, tolerance) == 0:
        repaired.append(current)
        return

    state = tuple(current)
    if depth > 0:
        if state in seen:
            _append_simple_hull(current, repaired, tolerance)
            return
        seen.add(state)

    if depth >= MAX_SPLIT_DEPTH:
        _append_simple_hull(current, repaired, tolerance)
        return

    parts = _force_split_lonlat_pairs(current, tolerance)
    if parts:
        progressed = False
        for part in parts:
            if tuple(part) == state:
                continue
            progressed = True
            _resolve_lonlat_leftover(
                part,
                repaired,
                pending,
                seen,
                tolerance,
                depth + 1,
            )
        if progressed:
            return

    _append_simple_hull(current, repaired, tolerance)


def _append_simple_hull(current, repaired, tolerance):
    hull = _convex_hull_pairs(current)
    if hull and count_lonlat_crossings(hull, tolerance) == 0:
        repaired.append(hull)


def _force_split_lonlat_pairs(pairs, tolerance):
    points = [
        {
            "name": f"P{index}",
            "y": longitude,
            "x": latitude,
        }
        for index, (longitude, latitude) in enumerate(pairs)
    ]
    crossings = find_all_bowtie_edge_pairs(points, tolerance)
    for crossing in crossings:
        parts = _split_once(points, crossing, tolerance)
        if parts is None or len(parts) < 2:
            continue
        return [
            [
                (point["y"], point["x"])
                for point in part
            ]
            for part in parts
        ]
    return None


def _convex_hull_pairs(pairs):
    """Last-resort simple envelope for a leftover multi-cross ring."""

    unique = []
    seen = set()
    for pair in pairs:
        if pair in seen:
            continue
        seen.add(pair)
        unique.append(pair)

    if len(unique) < 3:
        return None

    def cross(origin, a, b):
        return (
            (a[0] - origin[0]) * (b[1] - origin[1])
            - (a[1] - origin[1]) * (b[0] - origin[0])
        )

    ordered = sorted(unique)
    lower = []
    for point in ordered:
        while (
            len(lower) >= 2
            and cross(lower[-2], lower[-1], point) <= 0
        ):
            lower.pop()
        lower.append(point)

    upper = []
    for point in reversed(ordered):
        while (
            len(upper) >= 2
            and cross(upper[-2], upper[-1], point) <= 0
        ):
            upper.pop()
        upper.append(point)

    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return None
    return hull


def _collect_simple_parts(points, was_closed, tolerance):
    simple_parts = []
    area_epsilon = _area_epsilon(tolerance)

    for part in _split_into_simple_rings(points, 0, tolerance):
        cleaned = collapse_consecutive_duplicates(
            part,
            tolerance,
        )
        if len(cleaned) < 3:
            continue
        if find_bowtie_edge_pair(cleaned, tolerance) is not None:
            continue
        if _ring_area(cleaned) <= area_epsilon:
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

        crossing = find_bowtie_edge_pair(working, tolerance)
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


def _split_into_simple_rings(points, depth, tolerance):
    working = list(points)

    if depth > MAX_SPLIT_DEPTH:
        if find_bowtie_edge_pair(working, tolerance) is None and len(working) >= 3:
            return [working]
        return []

    if len(working) < 4:
        if len(working) >= 3 and find_bowtie_edge_pair(working, tolerance) is None:
            return [working]
        return []

    crossings = find_all_bowtie_edge_pairs(working, tolerance)
    if not crossings:
        return [working]

    for crossing in crossings:
        parts = _split_once(working, crossing, tolerance)
        if parts is None:
            continue

        result = []
        for part in parts:
            result.extend(
                _split_into_simple_rings(part, depth + 1, tolerance)
            )
        if result:
            return result

    return []


def _split_once(points, crossing, tolerance):
    start, end = crossing
    a1 = points[start]
    a2 = points[(start + 1) % len(points)]
    b1 = points[end]
    b2 = points[(end + 1) % len(points)]

    cross = _segment_intersection_point(a1, a2, b1, b2, tolerance)
    if cross is None:
        return None

    ring_a = points[:start + 1] + [cross] + points[end + 1:]
    ring_b = [cross] + points[start + 1:end + 1]

    parts = []
    for ring in (ring_a, ring_b):
        cleaned = collapse_consecutive_duplicates(ring, tolerance)
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
    quantize = tolerance if tolerance > 0 else 0.01
    return tuple(
        (
            round(float(point["y"]) / quantize),
            round(float(point["x"]) / quantize),
        )
        for point in points
    )


def _area_epsilon(tolerance):
    if tolerance >= 0.001:
        return _AREA_EPSILON
    return 0.0


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


def _segments_properly_intersect(a1, a2, b1, b2, epsilon=1e-9):
    """True for an interior X-crossing or a T-junction on an edge."""

    p1 = _xy(a1)
    p2 = _xy(a2)
    p3 = _xy(b1)
    p4 = _xy(b2)

    if p1 == p3 or p1 == p4 or p2 == p3 or p2 == p4:
        return False

    orientation_1 = _orientation(p1, p2, p3, epsilon)
    orientation_2 = _orientation(p1, p2, p4, epsilon)
    orientation_3 = _orientation(p3, p4, p1, epsilon)
    orientation_4 = _orientation(p3, p4, p2, epsilon)

    if (
        orientation_1 != 0
        and orientation_2 != 0
        and orientation_3 != 0
        and orientation_4 != 0
    ):
        return (
            orientation_1 != orientation_2
            and orientation_3 != orientation_4
        )

    if orientation_1 == 0 and _strictly_between(p3, p1, p2):
        return True
    if orientation_2 == 0 and _strictly_between(p4, p1, p2):
        return True
    if orientation_3 == 0 and _strictly_between(p1, p3, p4):
        return True
    if orientation_4 == 0 and _strictly_between(p2, p3, p4):
        return True

    return False


def _orientation(p, q, r, epsilon=1e-9):
    value = (
        (q[1] - p[1]) * (r[0] - q[0])
        - (q[0] - p[0]) * (r[1] - q[1])
    )

    if abs(value) <= epsilon:
        return 0

    return 1 if value > 0 else 2


def _segment_intersection_point(a1, a2, b1, b2, tolerance=None):
    epsilon = _geometry_epsilon(tolerance)
    p1 = _xy(a1)
    p2 = _xy(a2)
    p3 = _xy(b1)
    p4 = _xy(b2)

    denominator = (
        (p1[0] - p2[0]) * (p3[1] - p4[1])
        - (p1[1] - p2[1]) * (p3[0] - p4[0])
    )

    if abs(denominator) > 1e-18:
        t = (
            (p1[0] - p3[0]) * (p3[1] - p4[1])
            - (p1[1] - p3[1]) * (p3[0] - p4[0])
        ) / denominator

        if -1e-9 <= t <= 1 + 1e-9:
            easting = p1[0] + t * (p2[0] - p1[0])
            northing = p1[1] + t * (p2[1] - p1[1])
            return _split_vertex(
                a1,
                a2,
                t,
                easting,
                northing,
            )

    for vertex, start, end in (
        (b1, a1, a2),
        (b2, a1, a2),
        (a1, b1, b2),
        (a2, b1, b2),
    ):
        if _point_on_segment(vertex, start, end, epsilon):
            return dict(vertex)

    return None


def _split_vertex(a1, a2, t, easting, northing):
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


def _point_on_segment(point, start, end, epsilon):
    location = _xy(point)
    p1 = _xy(start)
    p2 = _xy(end)
    if location == p1 or location == p2:
        return False
    if _orientation(p1, p2, location, epsilon) != 0:
        return False
    return _strictly_between(location, p1, p2)


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


def _strictly_between(point, start, end, epsilon=1e-12):
    if point == start or point == end:
        return False

    min_y = min(start[0], end[0])
    max_y = max(start[0], end[0])
    min_x = min(start[1], end[1])
    max_x = max(start[1], end[1])

    if not (
        min_y - epsilon <= point[0] <= max_y + epsilon
        and min_x - epsilon <= point[1] <= max_x + epsilon
    ):
        return False

    return (
        point[0] > min_y + epsilon
        or point[0] < max_y - epsilon
        or point[1] > min_x + epsilon
        or point[1] < max_x - epsilon
    )
