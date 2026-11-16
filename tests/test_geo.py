"""Tests for the CRS-aware measurement helpers.

These pin the distinction the module exists for: a measurement in a geographic
CRS has to be converted, one in a metric CRS must not be — and getting either
wrong produces a number that looks plausible and is not.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from task_runtime_base.geo import (
    METRIC_SRID,
    area_m2,
    area_m2_auto,
    buffer_m_auto,
    length_m_auto,
    buffer_m,
    distance_m,
    is_metric,
    length_m,
    to_metric,
)


class ClassificationTests(unittest.TestCase):
    def test_utm_zones_are_metric(self):
        for srid in (25828, 25829, 32628):
            self.assertTrue(is_metric(srid), srid)

    def test_geographic_crs_are_not_metric(self):
        for srid in (4326, 4258, 4081):
            self.assertFalse(is_metric(srid), srid)

    def test_web_mercator_is_not_treated_as_metric(self):
        """3857 has metre units but distorts by latitude — x1.318 in the Canaries.

        Treating it as metric is exactly the bug that once made a task report a
        problem that did not exist.
        """
        self.assertFalse(is_metric(3857))


class AreaTests(unittest.TestCase):
    def test_geographic_is_converted(self):
        sql = area_m2("geom", srid=4326)
        self.assertIn("::geography", sql)

    def test_metric_is_measured_directly(self):
        """Converting an already-metric geometry would only add cost and error."""
        self.assertEqual(area_m2("geom", srid=25828), "ST_Area(geom)")

    def test_web_mercator_is_converted(self):
        self.assertIn("::geography", area_m2("geom", srid=3857))

    def test_defaults_to_converting(self):
        """The default has to be the safe one: 4326 is the project's storage CRS."""
        self.assertIn("::geography", area_m2("geom"))


class LengthAndDistanceTests(unittest.TestCase):
    def test_length_converts_geographic(self):
        self.assertIn("::geography", length_m("geom", srid=4326))

    def test_length_leaves_metric_alone(self):
        self.assertEqual(length_m("geom", srid=32628), "ST_Length(geom)")

    def test_distance_converts_both_sides(self):
        sql = distance_m("a.geom", "b.geom", srid=4326)
        self.assertEqual(sql.count("::geography"), 2)


class ProjectionTests(unittest.TestCase):
    """`::geography` measures; it does not project. Buffering needs a projection."""

    def test_to_metric_reprojects_geographic(self):
        self.assertIn("ST_Transform(geom, {0})".format(METRIC_SRID), to_metric("geom", srid=4326))

    def test_to_metric_is_a_no_op_when_already_there(self):
        self.assertEqual(to_metric("geom", srid=METRIC_SRID), "geom")

    def test_buffer_projects_and_comes_back(self):
        """A buffer must return to the original CRS, or it cannot be stored."""
        sql = buffer_m("geom", 10, srid=4326)
        self.assertIn("ST_Buffer(ST_Transform(geom, {0}), 10)".format(METRIC_SRID), sql)
        self.assertTrue(sql.startswith("ST_Transform("))
        self.assertIn(", 4326)", sql)

    def test_buffer_on_metric_geometry_is_direct(self):
        self.assertEqual(buffer_m("geom", 10, srid=25828), "ST_Buffer(geom, 10)")

    def test_buffer_in_degrees_is_what_this_prevents(self):
        """Ten degrees is ~1100 km — the mistake the helper exists to stop."""
        self.assertNotEqual(buffer_m("geom", 10, srid=4326), "ST_Buffer(geom, 10)")


class AutoDetectTests(unittest.TestCase):
    """The variants that read ST_SRID from the row.

    These exist because a hand-declared SRID is only correct while the schema
    keeps that CRS. citydb went from 3857 to 4326 on 2026-09-11; every call that
    had been told "this is 3857" started returning wrong numbers that day, and
    nothing failed. Reading the SRID from the data removes that class of bug.
    """

    def test_area_auto_branches_on_actual_srid(self):
        sql = area_m2_auto("geom")
        self.assertIn("ST_SRID(geom)", sql)
        self.assertIn("ST_Area(geom)", sql)        # metric branch
        self.assertIn("::geography", sql)          # geographic branch

    def test_area_auto_lists_the_metric_srids(self):
        sql = area_m2_auto("geom")
        self.assertIn("25828", sql)
        self.assertIn("32628", sql)

    def test_area_auto_does_not_treat_3857_as_metric(self):
        """3857 has metre units but distorts — it must take the convert branch."""
        self.assertNotIn("3857", area_m2_auto("geom"))

    def test_length_auto_branches_too(self):
        sql = length_m_auto("geom")
        self.assertIn("ST_SRID(geom)", sql)
        self.assertIn("::geography", sql)

    def test_buffer_auto_returns_to_the_original_srid(self):
        """Storing the result back needs the column's own CRS, whatever it is."""
        sql = buffer_m_auto("geom", 10)
        self.assertIn("ST_Transform(ST_Buffer(ST_Transform(geom", sql)
        self.assertIn("ST_SRID(geom))", sql)

    def test_auto_variants_are_valid_sql_shape(self):
        for sql in (area_m2_auto("g"), length_m_auto("g"), buffer_m_auto("g", 5)):
            self.assertTrue(sql.startswith("CASE WHEN "))
            self.assertTrue(sql.endswith(" END"))


if __name__ == "__main__":
    unittest.main()
