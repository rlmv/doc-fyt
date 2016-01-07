import unittest
from unittest.mock import MagicMock

from django.template import Context, Template
from model_mommy import mommy

from fyt.test.testcases import TripsTestCase
from fyt.trips.models import Section
from fyt.db.templatetags.links import pass_null
from fyt.db.urlhelpers import reverse_detail_url

class NullPassThroughDecorator(unittest.TestCase):

    def test_decorator(self):
        @pass_null
        def add_one(x):
            return x + 1
        self.assertEqual(add_one(5), 6)
        self.assertEqual(add_one(False), False)


class LinkTagTestCase(TripsTestCase):

    def test_detail_link(self):
        trips_year = self.init_trips_year()
        # for example
        obj = mommy.make(Section, trips_year=trips_year)
        obj.__str__ = lambda self: 'B'
        out = Template(
            "{% load links %}"
            "{{ obj|detail_link }}"
        ).render(Context({
            'obj': obj
        }))

    def test_detail_link_null_input(self):
        out = Template(
            "{% load links %}"
            "{{ obj|detail_link|default:'*' }}"
        ).render(Context({
            'obj': None
        }))
        self.assertEqual(out, '*')

    def test_detail_link_with_unary_iterable(self):
        trips_year = self.init_trips_year()
        # for example
        obj = mommy.make(Section, trips_year=trips_year)
        out = Template(
            "{% load links %}"
            "{{ obj_list|detail_link }}"
        ).render(Context({
            'obj_list': [obj]
        }))
        target = '<a href="%s">%s</a>' % (reverse_detail_url(obj), str(obj))
        self.assertEqual(out, target)

    def test_detail_link_with_iterable(self):
        trips_year = self.init_trips_year()
        obj1 = mommy.make(Section, trips_year=trips_year)
        obj2 = mommy.make(Section, trips_year=trips_year)
        out = Template(
            "{% load links %}"
            "{{ obj_list|detail_link }}"
        ).render(Context({
            'obj_list': [obj1, obj2]
        }))
        target = '<a href="{}">{}</a>, <a href="{}">{}</a>'.format(
            reverse_detail_url(obj1), str(obj1),
            reverse_detail_url(obj2), str(obj2)
        )
        self.assertEqual(out, target)