import unittest

from model_mommy import mommy
from django.core.exceptions import ValidationError
from django.template import Context, Template
from django.test import TestCase

from fyt.utils.matrix import OrderedMatrix
from fyt.utils.fmt import section_range
from fyt.trips.models import Section
from fyt.test.testcases import TripsYearTestCase
from fyt.utils.lat_lng import parse_lat_lng, validate_lat_lng


class OrderedMatrixTestCase(unittest.TestCase):

    def test_truncate_matrix(self):
        rows = [0, 1]
        cols = [0, 1]
        m = OrderedMatrix(rows, cols)
        m[0][0] = True
        self.assertEqual(m.truncate(), {0: {0: True, 1: None}})

    def test_map(self):
        rows = [0, 1]
        cols = [0, 1]
        m = OrderedMatrix(rows, cols, default=0)
        n = m.map(lambda x: x + 1)
        self.assertTrue(n[0][0]==n[0][1]==n[1][0]==n[1][1]==1)

    def test_map_creates_new_instance(self):
        rows = [0, 1]
        cols = [0, 1]
        m = OrderedMatrix(rows, cols, default=0)
        n = m.map(lambda x: x + 1)
        self.assertEqual(m[0][0], 0)


class FmtUtilsTest(TripsYearTestCase):

    def test_section_range(self):
        mommy.make(Section, name="A")
        mommy.make(Section, name="B")
        mommy.make(Section, name="C")
        self.assertEqual(section_range(Section.objects.all()), "A - C")

    def test_section_range_not_contiguous(self):
        mommy.make(Section, name="A")
        mommy.make(Section, name="C")
        with self.assertRaises(AssertionError):
            section_range(Section.objects.all())


class LatLngRegex(unittest.TestCase):

    def test_lat_lng(self):
        tests = [
            ('13.0,153.5', '13.0,153.5'),
            ('23.0, 153.5', '23.0,153.5'),
            ('33.0,153.5', '33.0,153.5'),
            ('-43.0, -153.5', '-43.0,-153.5'),
            ("""44° 2'39.67"N 71°47'31.72"W""", None),  # no match
            ('63.0,       153.5', '63.0,153.5'),
            ('73.0 153.5', '73.0,153.5'),
            # ...
        ]
        for string, target in tests:
            self.assertEqual(target, parse_lat_lng(string))

    def test_validate_lat_lng(self):
        validate_lat_lng('13.0,153.5')
        validate_lat_lng(' 13.0,153.5 ')
        with self.assertRaises(ValidationError):
            validate_lat_lng('g 13.0,153.5 ')
        with self.assertRaises(ValidationError):
            validate_lat_lng('13.0,153.5  13.0,153.5 ')


class UrlencodeTagTestCase(TestCase):

    def test_tag(self):
        out = Template(
            """
            {% load urlencode %}
            {% urlencode param1=value1 param2="test this" %}
            """
        ).render(Context({
            'value1': 1
        }))
        self.assertIn(out.strip(), [
            'param1=1&param2=test+this', 'param2=test+this&param1=1'
        ])