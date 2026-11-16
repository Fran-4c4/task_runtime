"""CRS-aware helpers for measurements that must come out in metres.

The trap this module exists to close
------------------------------------
`ST_Area(geom)` and `ST_Length(geom)` return values **in the units of the
geometry's CRS**, and PostGIS will not warn you when those units are not metres:

    EPSG:4326   degrees      ST_Area gives degrees squared — a meaningless number
    EPSG:3857   metres, but distorted by latitude: x1.318 in the Canaries
    EPSG:25828  metres, true at this latitude — safe to measure directly

The source geometry decides which conversion is valid; there is no safe
project-wide default. Under 3857, area is distorted by latitude. Under 4326,
the result is expressed in degrees squared rather than square metres.

Use these helpers rather than writing the cast by hand. They keep the choice
visible at the call site instead of buried in a subquery.

    from task_runtime_base.geo import area_m2_auto, area_m2, METRIC_SRID

    sql = "SELECT {0} FROM buildings".format(area_m2_auto("geom"))

Which variant to use
--------------------
`*_auto` reads `ST_SRID(geom)` from the row and converts accordingly. Use it by
default, **including where the CRS happens to be right today**: a data source
that is metric now may not be later, and the failure is silent.

The fixed-`srid` variants stay for the case where the SRID genuinely cannot vary,
such as a geometry the same query has just constructed with a literal CRS.
"""

from __future__ import annotations

# ETRS89 / UTM 28N. The projected CRS that is true-to-metre for the Canaries,
# which is the project's area of work. Elsewhere this would be the wrong zone.
METRIC_SRID = 25828

# CRSs whose units are already metres. Measuring directly in these is fine;
# anything else has to be converted.
METRIC_CRS = frozenset({25828, 25829, 25830, 25831, 32628, 32629, 32630})

# Geographic CRSs — degrees. ST_Area/ST_Length on these are meaningless as
# measurements, however plausible the number looks.
GEOGRAPHIC_CRS = frozenset({4326, 4258, 4081, 4083})


def is_metric(srid: int) -> bool:
    """True when a geometry in this CRS can be measured directly."""
    return int(srid) in METRIC_CRS


def area_m2_auto(geometry: str) -> str:
    """Area in m², converting based on the geometry's **actual** SRID at runtime.

    Prefer this over `area_m2(..., srid=...)` wherever the CRS could change.

    Passing the SRID by hand means the call is correct only while that
    assumption holds. `staging.*` is EPSG:32628 today, so measuring it directly
    is right — but if that schema is ever migrated to 4326, as `citydb` was on
    2026-09-11, every such call starts returning degrees squared and nothing
    fails. The number just becomes wrong.

    `ST_SRID(geom)` is read from the row, so the conversion follows the data
    instead of a comment. The CASE costs nothing measurable next to the
    measurement itself.
    """
    return (
        "CASE WHEN ST_SRID({0}) IN ({1}) THEN ST_Area({0}) "
        "ELSE ST_Area(ST_Transform({0}, 4326)::geography) END"
    ).format(geometry, _metric_list())


def length_m_auto(geometry: str) -> str:
    """Length in metres, converting based on the geometry's actual SRID."""
    return (
        "CASE WHEN ST_SRID({0}) IN ({1}) THEN ST_Length({0}) "
        "ELSE ST_Length(ST_Transform({0}, 4326)::geography) END"
    ).format(geometry, _metric_list())


def buffer_m_auto(geometry: str, metres: float, target: int = METRIC_SRID) -> str:
    """Buffer by `metres`, projecting only when the geometry is not already metric.

    Returns the result in the geometry's original CRS either way, so it can be
    stored back into the same column.
    """
    return (
        "CASE WHEN ST_SRID({0}) IN ({1}) THEN ST_Buffer({0}, {2}) "
        "ELSE ST_Transform(ST_Buffer(ST_Transform({0}, {3}), {2}), ST_SRID({0})) END"
    ).format(geometry, _metric_list(), metres, target)


def _metric_list() -> str:
    """The metric SRIDs as a SQL IN list."""
    return ", ".join(str(s) for s in sorted(METRIC_CRS))


def area_m2(geometry: str, srid: int = 4326) -> str:
    """SQL for the area of `geometry` in square metres.

    Uses `::geography`, which measures on the ellipsoid and is correct anywhere,
    rather than reprojecting to a UTM zone that is only right for one region.
    Slightly slower, and worth it: a wrong zone is a wrong answer with no
    warning.

    A geometry already in a metric CRS is measured directly.
    """
    if is_metric(srid):
        return "ST_Area({0})".format(geometry)
    return "ST_Area(ST_Transform({0}, 4326)::geography)".format(geometry)


def length_m(geometry: str, srid: int = 4326) -> str:
    """SQL for the length of `geometry` in metres. Same reasoning as area_m2."""
    if is_metric(srid):
        return "ST_Length({0})".format(geometry)
    return "ST_Length(ST_Transform({0}, 4326)::geography)".format(geometry)


def distance_m(left: str, right: str, srid: int = 4326) -> str:
    """SQL for the distance between two geometries, in metres."""
    if is_metric(srid):
        return "ST_Distance({0}, {1})".format(left, right)
    return (
        "ST_Distance(ST_Transform({0}, 4326)::geography, "
        "ST_Transform({1}, 4326)::geography)".format(left, right)
    )


def to_metric(geometry: str, srid: int = 4326, target: int = METRIC_SRID) -> str:
    """SQL reprojecting `geometry` into a metric CRS.

    For operations that need a *projected* geometry rather than a measurement —
    `ST_Buffer` with a distance in metres, erosion, offsets. `::geography` does
    not help there: those return geometries, and geography arithmetic is not
    what buffering expects.

    The result is in `target` (default ETRS89/UTM 28N, correct for the Canaries).
    **Reproject back before storing** if the column has a different SRID.
    """
    if int(srid) == int(target):
        return geometry
    return "ST_Transform({0}, {1})".format(geometry, target)


def buffer_m(geometry: str, metres: float, srid: int = 4326, target: int = METRIC_SRID) -> str:
    """SQL buffering `geometry` by `metres`, returned in the original CRS.

    ST_Buffer works in the geometry's own units, so buffering a 4326 geometry by
    "10" would ask for ten *degrees* — roughly 1100 km. This projects, buffers,
    and projects back.
    """
    if is_metric(srid):
        return "ST_Buffer({0}, {1})".format(geometry, metres)
    return "ST_Transform(ST_Buffer(ST_Transform({0}, {1}), {2}), {3})".format(
        geometry, target, metres, srid
    )
