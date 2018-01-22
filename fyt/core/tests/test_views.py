from model_mommy import mommy

from fyt.test import FytTestCase
from fyt.trips.models import Section


class DetailViewTestCase(FytTestCase):

    def test_urls_in_context(self):
        trips_year = self.init_trips_year()
        # test Section detail, for example
        section = mommy.make(Section, trips_year=trips_year)
        resp = self.app.get(section.detail_url(), user=self.make_director())
        self.assertEqual(resp.context['update_url'], section.update_url())
        self.assertEqual(resp.context['delete_url'], section.delete_url())