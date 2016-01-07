import io
import csv
import tempfile
import unittest
from datetime import date

from django.core.urlresolvers import reverse
from model_mommy import mommy

from fyt.test.testcases import WebTestCase, TripsTestCase
from fyt.applications.tests import ApplicationTestMixin
from fyt.applications.models import GeneralApplication
from fyt.incoming.models import Registration, IncomingStudent, Settings
from fyt.trips.models import Trip
from fyt.utils.choices import S, M, L, XL
from fyt.reports.views import leader_tshirts, croo_tshirts, trippee_tshirts


def save_and_open_csv(resp):
    """
    Save the file content return by response and
    open a CSV reader object over the saved file.
    """
    f = tempfile.NamedTemporaryFile()
    f.write(resp.content)
    f = open(f.name)  # open in non-binary mode
    return csv.DictReader(f)


class ReportViewsTestCase(WebTestCase, ApplicationTestMixin):

    def assertStopsIteration(self, iter):
        with self.assertRaises(StopIteration):
            next(iter)

    def assertViewReturns(self, urlpattern, target):
        """
        Test a view by visiting it with director priveleges and
        comparing returned csv to ``target``.

        ``urlpattern`` is a reversable pattern,
        ``target`` is a list of ``dicts``
        """
        url = reverse(urlpattern, kwargs={'trips_year': self.trips_year})
        rows = list(save_and_open_csv(self.app.get(url, user=self.mock_director())))
        self.assertEqual(rows, target)

    def test_volunteer_csv(self):
        trips_year = self.init_current_trips_year()
        application = self.make_application(trips_year=trips_year)
        non_applicant = self.make_application(trips_year=trips_year)
        non_applicant.croo_supplement.document = ''
        non_applicant.croo_supplement.save()
        non_applicant.leader_supplement.document = ''
        non_applicant.leader_supplement.save()
        res = self.app.get(reverse('db:reports:all_apps',
                                   kwargs={'trips_year': trips_year}),
                           user=self.mock_director())
        self.assertTrue(res['Content-Disposition'].startswith('attachment; filename="'))
        rows = list(save_and_open_csv(res))
        row = rows[0]
        self.assertEqual(row['name'], application.applicant.name)
        self.assertEqual(row['netid'], application.applicant.netid)
        self.assertEqual(len(rows), 1)

    def test_trip_leader_csv(self):
        trips_year = self.init_trips_year()
        leader = self.make_application(
            trips_year=trips_year,
            status=GeneralApplication.LEADER
        )
        not_leader = self.make_application(trips_year=trips_year)

        url = reverse('db:reports:leaders', kwargs={'trips_year': trips_year})
        rows = list(save_and_open_csv(self.app.get(url, user=self.mock_director())))
        target = [{
            'name': leader.name,
            'netid': leader.applicant.netid.upper()
        }]

        self.assertEqual(rows, target)

    def test_croo_members_csv(self):
        trips_year = self.init_trips_year()
        croo = self.make_application(
            trips_year=trips_year,
            status=GeneralApplication.CROO
        )
        not_croo = self.make_application(trips_year=trips_year)

        url = reverse('db:reports:croo_members', kwargs={'trips_year': trips_year})
        rows = list(save_and_open_csv(self.app.get(url, user=self.mock_director())))
        target = [{
            'name': croo.name,
            'netid': croo.applicant.netid.upper()
        }]
        self.assertEqual(rows, target)

    def test_trippees_csv(self):
        trips_year = self.init_trips_year()
        trippee = mommy.make(
            IncomingStudent,
            trips_year=trips_year,
            trip_assignment=mommy.make(Trip)
        )
        not_trippee = mommy.make(
            IncomingStudent,
            trips_year=trips_year,
            trip_assignment=None
        )
        target = [{
            'name': trippee.name,
            'netid': trippee.netid.upper()
        }]
        self.assertViewReturns('db:reports:trippees', target)

    def test_charges_report(self):
        trips_year = self.init_trips_year()
        mommy.make(Settings, trips_year=trips_year, doc_membership_cost=91, trips_cost=250)
        # incoming student to be charged:
        incoming1 = mommy.make(
            IncomingStudent,
            name='1',
            trips_year=trips_year,
            trip_assignment__trips_year=trips_year,  # force trip to exist
            bus_assignment_round_trip__cost_round_trip=100,
            financial_aid=10,
            registration__doc_membership=True,
            registration__green_fund_donation=20
        )
        # another, without a registration
        incoming2 = mommy.make(
            IncomingStudent,
            name='2',
            trips_year=trips_year,
            trip_assignment__trips_year=trips_year,  # ditto
            financial_aid=0
        )
        # another with no trip but with doc membership
        incoming3 = mommy.make(
            IncomingStudent,
            name='3',
            trips_year=trips_year,
            trip_assignment=None,
            financial_aid=0,
            registration__doc_membership=True
        )
        # another with no trip, no membership, but green fund donation
        incoming4 = mommy.make(
            IncomingStudent,
            name='4',
            trips_year=trips_year,
            trip_assignment=None,
            financial_aid=0,
            registration__doc_membership=False,
            registration__green_fund_donation=12
        )
        # last-minute cancellation
        incoming5 = mommy.make(
            IncomingStudent,
            name='5',
            trips_year=trips_year,
            trip_assignment=None,
            cancelled=True,
            financial_aid=0,
            registration__doc_membership=False,
        )

        # not charged because no trip assignment AND no DOC membership
        mommy.make(IncomingStudent, trips_year=trips_year)

        url = reverse('db:reports:charges', kwargs={'trips_year': trips_year})
        resp = self.app.get(url, user=self.mock_director())

        rows = list(save_and_open_csv(resp))
        target = [{
            'name': incoming1.name,
            'netid': incoming1.netid,
            'total charge': str(incoming1.compute_cost()),
            'aid award (percentage)': '10',
            'trip': '225.00',
            'bus': '90.00',
            'doc membership': '81.90',
            'green fund': '20.00',
            'cancellation': ''
        }, {
            'name': incoming2.name,
            'netid': incoming2.netid,
            'total charge': str(incoming2.compute_cost()),
            'aid award (percentage)': '',
            'trip': '250.00',
            'bus': '',
            'doc membership': '',
            'green fund': '',
            'cancellation': ''
        }, {
            'name': incoming3.name,
            'netid': incoming3.netid,
            'total charge': '91.00',
            'aid award (percentage)': '',
            'trip': '',
            'bus': '',
            'doc membership': '91.00',
            'green fund': '',
            'cancellation': ''
        }, {
            'name': incoming4.name,
            'netid': incoming4.netid,
            'total charge': '12.00',
            'aid award (percentage)': '',
            'trip': '',
            'bus': '',
            'doc membership': '',
            'green fund': '12.00',
            'cancellation': ''
        }, {
            'name': incoming5.name,
            'netid': incoming5.netid,
            'total charge': '250.00',
            'aid award (percentage)': '',
            'trip': '',
            'bus': '',
            'doc membership': '',
            'green fund': '',
            'cancellation': '250.00'
        }]
        self.assertEqual(rows, target)

    def test_housing_report(self):
        trips_year = self.init_trips_year()
        t1 = mommy.make(
            IncomingStudent,
            name='1',
            trips_year=trips_year,
            trip_assignment__trips_year=trips_year,
            trip_assignment__section__leaders_arrive=date(2015, 1, 1),
            registration__is_fysep=True,
            registration__is_native=True,
            registration__is_international=False
        )
        t2 = mommy.make(
            IncomingStudent,
            name='2',
            trips_year=trips_year,
            trip_assignment=None
        )
        url = reverse('db:reports:housing', kwargs={'trips_year': trips_year})
        resp = self.app.get(url, user=self.mock_director())

        rows = list(save_and_open_csv(resp))
        target = [{
            'name': t1.name,
            'netid': t1.netid,
            'trip': str(t1.trip_assignment),
            'section': str(t1.trip_assignment.section.name),
            'start date': '01/02',
            'end date': '01/06',
            'native': 'yes',
            'fysep': 'yes',
            'international': ''
        }, {
            'name': t2.name,
            'netid': t2.netid,
            'trip': '',
            'section': '',
            'start date': '',
            'end date': '',
            'native': '',
            'fysep': '',
            'international': '',
        }]
        self.assertEqual(rows, target)


    def test_dietary_restrictions(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip,
            trips_year=trips_year
        )
        reg = mommy.make(
            Registration,
            trips_year=trips_year,
            food_allergies='peaches',
            dietary_restrictions='gluten free',
            epipen=True,
        )
        inc = mommy.make(
            IncomingStudent,
            trips_year=trips_year,
            trip_assignment=trip,
            registration=reg,
        )
        url = reverse('db:reports:dietary', kwargs={'trips_year': trips_year})
        resp  = self.app.get(url, user=self.mock_director())

        rows = list(save_and_open_csv(resp))
        target = [{
            'name': reg.name,
            'netid': reg.user.netid,
            'section': trip.section.name,
            'trip': str(trip),
            'food allergies': 'peaches',
            'dietary restrictions': 'gluten free',
            'epipen': 'Yes',
        }]
        self.assertEqual(rows, target)

    def test_medical_info(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip,
            trips_year=trips_year
        )
        reg = mommy.make(
            Registration,
            trips_year=trips_year,
            food_allergies='peaches',
            dietary_restrictions='gluten free',
            medical_conditions='none',
            epipen=True,
            needs='many',
        )
        inc = mommy.make(
            IncomingStudent,
            trips_year=trips_year,
            trip_assignment=trip,
            registration=reg,
        )
        url = reverse('db:reports:medical', kwargs={'trips_year': trips_year})
        resp = self.app.get(url, user=self.mock_director())

        rows = list(save_and_open_csv(resp))
        target = [{
            'name': reg.name,
            'netid': reg.user.netid,
            'section': trip.section.name,
            'trip': str(trip),
            'medical conditions': 'none',
            'needs': 'many',
            'food allergies': 'peaches',
            'dietary restrictions': 'gluten free',
            'epipen': 'Yes',
        }]
        self.assertEqual(rows, target)

    def test_doc_memberships(self):
        trips_year = self.init_trips_year()
        reg = mommy.make(
            Registration,
            trips_year=trips_year,
            doc_membership=True
        )
        other_reg = mommy.make(
            Registration,
            trips_year=trips_year,
            doc_membership=False
        )
        url = reverse('db:reports:doc_members', kwargs={'trips_year': trips_year})
        resp = self.app.get(url, user=self.mock_director())

        target = [{
            'name': reg.user.name,
            'netid': reg.user.netid,
            'email': reg.user.email
        }]
        self.assertEqual(list(save_and_open_csv(resp)), target)


    def test_volunteer_dietary_restrictions(self):
        trips_year = self.init_trips_year()

        leader = mommy.make(
            GeneralApplication, trips_year=trips_year,
            status=GeneralApplication.LEADER,
            assigned_trip=mommy.make(Trip, trips_year=trips_year),
            food_allergies='peaches',
            dietary_restrictions='gluten free',
            epipen=True,
        )
        croo = mommy.make(
            GeneralApplication, trips_year=trips_year,
            status=GeneralApplication.CROO,
            food_allergies='peaches',
            dietary_restrictions='gluten free',
            epipen=False
        )
        neither = mommy.make(
            GeneralApplication, trips_year=trips_year,
            status=GeneralApplication.PENDING
        )
        url = reverse('db:reports:volunteer_dietary', kwargs={'trips_year': trips_year})
        resp = self.app.get(url, user=self.mock_director())
        rows = list(save_and_open_csv(resp))
        target = [{
            'name': croo.applicant.name,
            'netid': croo.applicant.netid,
            'role': GeneralApplication.CROO,
            'trip': '',
            'food allergies': croo.food_allergies,
            'dietary restrictions': croo.dietary_restrictions,
            'epipen': 'No'
        }, {
            'name': leader.applicant.name,
            'netid': leader.applicant.netid,
            'role': GeneralApplication.LEADER,
            'trip': str(leader.assigned_trip),
            'food allergies': leader.food_allergies,
            'dietary restrictions': leader.dietary_restrictions,
            'epipen': 'Yes'
        }]
        self.assertEqual(rows, target)


    def test_foodboxes(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip,
            trips_year=trips_year,
        )
        mommy.make(
            IncomingStudent, 3,
            trips_year=trips_year
        )
        url = reverse('db:reports:foodboxes', kwargs={'trips_year': trips_year})
        resp = self.app.get(url, user=self.mock_director())

        rows = list(save_and_open_csv(resp))
        target = [{
            'trip': str(trip),
            'section': trip.section.name,
            'size': str(trip.size()),
            'full box': '1',
            'half box': '1' if trip.half_foodbox else '',
            'supplement': '1' if trip.supp_foodbox else '',
            'bagels': str(trip.bagels),
        }]
        self.assertEqual(rows, target)


class TShirtCountTestCase(TripsTestCase):

    def test_tshirt_count_leaders(self):
        trips_year = self.init_trips_year()
        mommy.make(
            GeneralApplication,
            trips_year=trips_year,
            status=GeneralApplication.LEADER,
            assigned_trip__trips_year=trips_year,
            tshirt_size=S
        )
        target = {
            S: 1, M: 0, L: 0, XL: 0
        }
        self.assertEqual(target, leader_tshirts(trips_year))

    def test_tshirt_count_croos(self):
        trips_year = self.init_trips_year()
        mommy.make(
            GeneralApplication,
            trips_year=trips_year,
            status=GeneralApplication.CROO,
            tshirt_size=M
        )
        target = {
            S: 0, M: 1, L: 0, XL: 0
        }
        self.assertEqual(target, croo_tshirts(trips_year))

    def test_tshirt_count_trippees(self):
        trips_year = self.init_trips_year()
        mommy.make(
            Registration,
            trips_year=trips_year,
            tshirt_size=L
        )
        target = {
            S: 0, M: 0, L: 1, XL: 0
        }
        self.assertEqual(target, trippee_tshirts(trips_year))