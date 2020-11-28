import math
import unittest
from datetime import date, time, timedelta

import boto3  # This is required to fix an issue with VCR
import webtest
from django.core.exceptions import ValidationError
from django.forms.models import model_to_dict
from django.urls import reverse
from model_mommy import mommy

from ..models import (
    NUM_BAGELS_REGULAR,
    NUM_BAGELS_SUPPLEMENT,
    Campsite,
    Section,
    Trip,
    TripTemplate,
    TripType,
    validate_triptemplate_name,
)

from fyt.applications.models import Volunteer
from fyt.applications.tests import make_application
from fyt.core.forward import forward
from fyt.incoming.models import (
    IncomingStudent,
    Registration,
    RegistrationSectionChoice,
    RegistrationTripTypeChoice,
)
from fyt.test import FytTestCase, vcr
from fyt.timetable.models import Timetable
from fyt.transport.models import Route
from fyt.utils.choices import AVAILABLE, PREFER


class TripTestCase(FytTestCase):

    csrf_checks = False

    def setUp(self):
        self.init_trips_year()

    def test_unique_validation_in_create_view(self):
        """
        See the comment in DatabaseMixin.form_valid
        """
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__trips_year=self.trips_year,
            section__trips_year=self.trips_year,
        )
        trip.save()

        # Posting will raise an IntegrityError if validation is not handled
        url = Trip.create_url(self.trips_year)
        params = {'template': trip.template.pk, 'section': trip.section.pk}
        response = self.app.post(url, params=params, user=self.make_director())

        # should have unique constraint error
        self.assertIn('unique constraint', str(response.content).lower())
        # should not create the trip
        scheduled_trips = Trip.objects.all()
        self.assertEqual(len(scheduled_trips), 1)
        self.assertEqual(scheduled_trips[0], trip)

    def test_num_queries_in_scheduled_trip_matrix(self):
        trips_year = self.trips_year
        template1 = mommy.make(TripTemplate, trips_year=trips_year)
        section1 = mommy.make(Section, trips_year=trips_year)
        template2 = mommy.make(TripTemplate, trips_year=trips_year)
        section2 = mommy.make(Section, trips_year=trips_year)
        mommy.make(Trip, section=section1, template=template1, trips_year=trips_year)
        mommy.make(Trip, section=section1, template=template2, trips_year=trips_year)
        mommy.make(Trip, section=section2, template=template2, trips_year=trips_year)
        user = self.make_director()
        with self.assertNumQueries(17):
            self.app.get(
                reverse('core:trip:index', kwargs={'trips_year': self.trips_year}),
                user=user,
            )


class TripModelTestCase(FytTestCase):
    def test_gets_half_foodbox(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip, trips_year=trips_year, template__triptype__half_kickin=3
        )
        make_application(trips_year=trips_year, trip_assignment=trip)
        mommy.make(IncomingStudent, trips_year=trips_year, trip_assignment=trip)
        mommy.make(IncomingStudent, trips_year=trips_year, trip_assignment=trip)
        self.assertTrue(trip.half_foodbox)

    def test_does_not_get_half_foodbox(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip, trips_year=trips_year, template__triptype__half_kickin=3
        )
        make_application(trips_year=trips_year, trip_assignment=trip)
        mommy.make(IncomingStudent, trips_year=trips_year, trip_assignment=trip)
        self.assertFalse(trip.half_foodbox)

    def test_gets_supplemental_foodbox(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip, trips_year=trips_year, template__triptype__gets_supplemental=True
        )
        self.assertTrue(trip.supp_foodbox)

    def test_does_not_get_supplemental_foodbox(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip, trips_year=trips_year, template__triptype__gets_supplemental=False
        )
        self.assertFalse(trip.supp_foodbox)

    def test_bagels_not_supplement(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip, trips_year=trips_year, template__triptype__gets_supplemental=False
        )
        mommy.make(IncomingStudent, 2, trips_year=trips_year, trip_assignment=trip)
        self.assertEqual(trip.bagels, math.ceil(2 * NUM_BAGELS_REGULAR))

    def test_bagels_supplemental(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip, trips_year=trips_year, template__triptype__gets_supplemental=True
        )
        mommy.make(IncomingStudent, 2, trips_year=trips_year, trip_assignment=trip)
        self.assertEqual(trip.bagels, math.ceil(2 * NUM_BAGELS_SUPPLEMENT))

    def test_section_and_template_cannot_be_changed(self):
        trip = mommy.make(Trip)

        trip.section = mommy.make(Section)
        with self.assertRaises(ValidationError):
            trip.full_clean()

        trip.refresh_from_db()

        trip.template = mommy.make(TripTemplate)
        with self.assertRaises(ValidationError):
            trip.full_clean()


class TripRouteOverridesTestCase(FytTestCase):
    def test_override_routes_in_trip_update_form(self):
        trips_year = self.init_trips_year()
        template = mommy.make(TripTemplate, trips_year=trips_year)
        section = mommy.make(Section, trips_year=trips_year)
        trip = mommy.make(
            Trip, trips_year=trips_year, section=section, template=template
        )
        route = mommy.make(Route, trips_year=trips_year)
        res = self.app.get(trip.update_url(), user=self.make_director())
        form = res.form
        form['dropoff_route'] = route.pk
        form['pickup_route'] = route.pk
        form['return_route'] = route.pk
        res = form.submit()
        trip = Trip.objects.get(pk=trip.pk)
        self.assertEqual(trip.dropoff_route, route)
        self.assertEqual(trip.pickup_route, route)
        self.assertEqual(trip.return_route, route)

    def test_get_dropoff_route_method(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(
            Trip,
            trips_year=trips_year,
            template__dropoff_stop__route=mommy.make(Route, trips_year=trips_year),
        )
        self.assertEqual(trip.get_dropoff_route(), trip.template.dropoff_stop.route)
        # override default route
        trip.dropoff_route = mommy.make(Route, trips_year=trips_year)
        trip.save()
        self.assertEqual(trip.get_dropoff_route(), trip.dropoff_route)

    def test_get_pickup_route_method(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)

        self.assertEqual(trip.get_pickup_route(), trip.template.pickup_stop.route)
        # override default route
        trip.pickup_route = mommy.make(Route, trips_year=trips_year)
        trip.save()
        self.assertEqual(trip.get_pickup_route(), trip.pickup_route)

    def test_get_return_route_method(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        self.assertEqual(trip.get_return_route(), trip.template.return_route)
        # override default route
        trip.return_route = mommy.make(Route, trips_year=trips_year)
        trip.save()
        self.assertEqual(trip.get_return_route(), trip.return_route)

    def test_size_method_with_noone(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        self.assertEqual(trip.size, 0)

    def test_size_method_with_1_leader(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        make_application(trips_year=trips_year, trip_assignment=trip)
        self.assertEqual(trip.size, 1)

    def test_size_method_with_1_leader_and_2_trippees(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        make_application(trips_year=trips_year, trip_assignment=trip)
        mommy.make(IncomingStudent, trips_year=trips_year, trip_assignment=trip)
        mommy.make(IncomingStudent, trips_year=trips_year, trip_assignment=trip)
        self.assertEqual(trip.size, 3)


class QuickTestViews(FytTestCase):
    def test_index_views(self):
        trips_year = self.init_trips_year()
        director = self.make_director()

        names = [
            'core:trip:index',
            'core:triptemplate:index',
            'core:triptype:index',
            'core:campsite:index',
            'core:section:index',
            'core:leader_index',
        ]

        for name in names:
            res = self.app.get(
                reverse(name, kwargs={'trips_year': trips_year}), user=director
            )


class TripTypeManagerTestCase(FytTestCase):
    def test_visible(self):
        trips_year = self.init_trips_year()
        hidden = mommy.make(TripType, trips_year=trips_year, hidden=True)
        visible = mommy.make(TripType, trips_year=trips_year, hidden=False)
        self.assertQsEqual(TripType.objects.visible(trips_year), [visible])


class SectionManagerTestCase(FytTestCase):
    def test_local(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, is_local=True)
        section2 = mommy.make(Section, trips_year=trips_year, is_local=False)
        self.assertEqual([section1], list(Section.objects.local(trips_year)))

    def test_not_local(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, is_local=True)
        section2 = mommy.make(Section, trips_year=trips_year, is_local=False)
        self.assertEqual([section2], list(Section.objects.not_local(trips_year)))

    def test_international(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, is_international=True)
        section2 = mommy.make(Section, trips_year=trips_year, is_international=False)
        self.assertEqual([section1], list(Section.objects.international(trips_year)))

    def test_transfer(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, is_transfer=True)
        section2 = mommy.make(Section, trips_year=trips_year, is_transfer=False)
        self.assertEqual([section1], list(Section.objects.transfer(trips_year)))

    def test_native(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, is_native=True)
        section2 = mommy.make(Section, trips_year=trips_year, is_native=False)
        self.assertEqual([section1], list(Section.objects.native(trips_year)))

    def test_fysep(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, is_fysep=True)
        section2 = mommy.make(Section, trips_year=trips_year, is_fysep=False)
        self.assertEqual([section1], list(Section.objects.fysep(trips_year)))

    def test_exchange(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, is_exchange=True)
        section2 = mommy.make(Section, trips_year=trips_year, is_exchange=False)
        self.assertEqual([section1], list(Section.objects.exchange(trips_year)))

    def test_trips_dates_with_one_section(self):
        ty = self.init_trips_year()
        leaders_arrive = date(2015, 1, 1)
        section = mommy.make(Section, trips_year=ty, leaders_arrive=leaders_arrive)
        self.assertEqual(section.trip_dates, Section.dates.trip_dates(ty))

    def test_trips_dates_with_multiple_sections(self):
        ty = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=ty, leaders_arrive=date(2015, 1, 1))
        section2 = mommy.make(Section, trips_year=ty, leaders_arrive=date(2015, 1, 4))
        self.assertEqual(
            Section.dates.trip_dates(ty),
            sorted(list(set(section1.trip_dates + section2.trip_dates))),
        )

    def test_leader_dates(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(
            Section, trips_year=trips_year, leaders_arrive=date(2015, 1, 1)
        )
        section2 = mommy.make(
            Section, trips_year=trips_year, leaders_arrive=date(2015, 1, 4)
        )
        self.assertEqual(
            Section.dates.leader_dates(trips_year),
            sorted(list(set(section1.leader_dates + section2.leader_dates))),
        )

    def test_sophomore_leaders_ok(self):
        trips_year = self.init_trips_year()
        section1 = mommy.make(Section, trips_year=trips_year, sophomore_leaders_ok=True)
        section2 = mommy.make(
            Section, trips_year=trips_year, sophomore_leaders_ok=False
        )
        self.assertQsEqual(Section.objects.sophomore_leaders_ok(trips_year), [section1])


class SectionModelTestCase(FytTestCase):
    def test_model_trip_dates(self):
        ty = self.init_trips_year()
        section = mommy.make(Section, trips_year=ty, leaders_arrive=date(2015, 1, 1))
        self.assertEqual(
            section.trip_dates,
            [
                date(2015, 1, 2),
                date(2015, 1, 3),
                date(2015, 1, 4),
                date(2015, 1, 5),
                date(2015, 1, 6),
            ],
        )

    def test_leader_dates(self):
        trips_year = self.init_trips_year()
        section = mommy.make(
            Section, trips_year=trips_year, leaders_arrive=date(2015, 1, 1)
        )
        self.assertEqual(
            section.leader_dates,
            [
                date(2015, 1, 1),
                date(2015, 1, 2),
                date(2015, 1, 3),
                date(2015, 1, 4),
                date(2015, 1, 5),
                date(2015, 1, 6),
            ],
        )


class TripTemplateValidatorTest(unittest.TestCase):
    def test_validator(self):
        with self.assertRaises(ValidationError):
            validate_triptemplate_name(-1)
        with self.assertRaises(ValidationError):
            validate_triptemplate_name(1000)
        validate_triptemplate_name(0)
        validate_triptemplate_name(525)
        validate_triptemplate_name(999)


class AssignLeaderTestCase(FytTestCase):
    def test_trip_assignment_automatically_sets_LEADER_status(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        volunteer = make_application(trips_year=trips_year)
        volunteer.leader_supplement.set_section_preference(trip.section, AVAILABLE)
        volunteer.leader_supplement.set_triptype_preference(
            trip.template.triptype, AVAILABLE
        )
        url = reverse(
            'core:assign_leader',
            kwargs={'trips_year': trips_year.pk, 'trip_pk': trip.pk},
        )
        res = self.app.get(url, user=self.make_director())
        res = res.click(description="Assign to")
        res.form.submit()  # assign to trip - first (and only) form on page
        volunteer = Volunteer.objects.get(pk=volunteer.pk)  # refresh
        self.assertEqual(volunteer.trip_assignment, trip)
        self.assertEqual(volunteer.status, Volunteer.LEADER)

    def test_assign_trip_computes_section_and_type_preferences(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        volunteer = make_application(trips_year=trips_year)
        volunteer.leader_supplement.set_section_preference(trip.section, AVAILABLE)
        volunteer.leader_supplement.set_triptype_preference(
            trip.template.triptype, PREFER
        )
        url = reverse(
            'core:assign_leader',
            kwargs={'trips_year': trips_year.pk, 'trip_pk': trip.pk},
        )
        res = self.app.get(url, user=self.make_director())
        leader_list = list(res.context['leader_applications'])
        self.assertEqual(len(leader_list), 1)
        (leader, _, triptype_preference, section_preference) = leader_list[0]
        self.assertEqual(leader, volunteer)
        self.assertEqual(triptype_preference, PREFER)
        self.assertEqual(section_preference, AVAILABLE)


class AssignTrippeeTestCase(FytTestCase):
    def test_trip_assignment(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        registration = mommy.make(Registration, trips_year=trips_year)
        registration.set_section_preference(trip.section, PREFER)
        registration.set_triptype_preference(trip.template.triptype, PREFER)
        trippee = mommy.make(
            IncomingStudent, trips_year=trips_year, registration=registration
        )

        url = reverse(
            'core:assign_trippee',
            kwargs={'trips_year': trips_year.pk, 'trip_pk': trip.pk},
        )
        res = self.app.get(url, user=self.make_director())
        res = res.click(description="Assign to")
        res.form.submit()  # assign to trip - first (and only) form on page
        trippee = IncomingStudent.objects.get(pk=trippee.pk)
        self.assertEqual(trippee.trip_assignment, trip)


class TripManagerTestCase(FytTestCase):
    def test_manager_automatically_selects_section_and_template(self):
        trips_year = self.init_trips_year()
        mommy.make(Trip, trips_year=trips_year)
        with self.assertNumQueries(1):
            trip = Trip.objects.get()
            trip.section.name
            trip.template.name
        mommy.make(Trip, trips_year=trips_year)
        with self.assertNumQueries(1):
            str(Trip.objects.all())

    def test_simple_matrix(self):
        trips_year = self.init_trips_year()
        template = mommy.make(TripTemplate, trips_year=trips_year)
        section = mommy.make(Section, trips_year=trips_year)
        trip = mommy.make(
            Trip, section=section, template=template, trips_year=trips_year
        )
        target = {template: {section: trip}}
        self.assertEqual(Trip.objects.matrix(trips_year), target)

    def test_another_matrix(self):
        trips_year = self.init_trips_year()
        template1 = mommy.make(TripTemplate, trips_year=trips_year)
        section1 = mommy.make(Section, trips_year=trips_year)
        template2 = mommy.make(TripTemplate, trips_year=trips_year)
        section2 = mommy.make(Section, trips_year=trips_year)
        trip1 = mommy.make(
            Trip, section=section1, template=template1, trips_year=trips_year
        )
        trip2 = mommy.make(
            Trip, section=section1, template=template2, trips_year=trips_year
        )
        trip3 = mommy.make(
            Trip, section=section2, template=template2, trips_year=trips_year
        )
        target = {
            template1: {section1: trip1, section2: None},
            template2: {section1: trip2, section2: trip3},
        }
        self.assertEqual(Trip.objects.matrix(trips_year), target)

    def test_counts_are_equal(self):
        # tests that we are using Count(distinct=True)
        trips_year = self.init_trips_year()
        template = mommy.make(TripTemplate, trips_year=trips_year)
        section = mommy.make(Section, trips_year=trips_year)
        trip = mommy.make(
            Trip, section=section, template=template, trips_year=trips_year
        )
        mommy.make(IncomingStudent, trips_year=trips_year, trip_assignment=trip)
        mommy.make(Volunteer, trips_year=trips_year, trip_assignment=trip)
        mommy.make(Volunteer, trips_year=trips_year, trip_assignment=trip)
        matrix = Trip.objects.matrix(trips_year)
        self.assertEqual(matrix[template][section].num_trippees, 1)
        self.assertEqual(
            matrix[template][section].num_trippees,
            matrix[template][section].trippees.count(),
        )

    def test_dropoffs(self):
        trips_year = self.init_trips_year()
        route = mommy.make(Route, trips_year=trips_year)
        section = mommy.make(Section, trips_year=trips_year)
        dropoff = mommy.make(
            Trip,
            trips_year=trips_year,
            section=section,
            template__dropoff_stop__route=route,
        )
        overridden_dropoff = mommy.make(
            Trip, trips_year=trips_year, section=section, dropoff_route=route
        )
        other_route = mommy.make(Trip, trips_year=trips_year, section=section)
        other_date = mommy.make(
            Trip,
            trips_year=trips_year,
            template__dropoff_stop__route=route,
            section__leaders_arrive=section.leaders_arrive + timedelta(days=100),
        )

        qs = Trip.objects.dropoffs(route, section.at_campsite1, trips_year=trips_year)
        self.assertQsEqual(qs, [dropoff, overridden_dropoff])

    def test_pickups(self):
        trips_year = self.init_trips_year()
        route = mommy.make(Route, trips_year=trips_year)
        section = mommy.make(Section, trips_year=trips_year)
        pickup = mommy.make(
            Trip,
            trips_year=trips_year,
            section=section,
            template__pickup_stop__route=route,
        )
        overridden_pickup = mommy.make(
            Trip, trips_year=trips_year, section=section, pickup_route=route
        )
        other_route = mommy.make(Trip, trips_year=trips_year, section=section)
        other_date = mommy.make(
            Trip,
            trips_year=trips_year,
            template__pickup_stop__route=route,
            section__leaders_arrive=section.leaders_arrive + timedelta(days=100),
        )

        qs = Trip.objects.pickups(route, section.arrive_at_lodge, trips_year=trips_year)
        self.assertQsEqual(qs, [pickup, overridden_pickup])

    def test_returns(self):
        trips_year = self.init_trips_year()
        route = mommy.make(Route, trips_year=trips_year)
        section = mommy.make(Section, trips_year=trips_year)
        returning = mommy.make(
            Trip, trips_year=trips_year, section=section, template__return_route=route
        )
        overridden_return = mommy.make(
            Trip, trips_year=trips_year, section=section, return_route=route
        )
        other_route = mommy.make(Trip, trips_year=trips_year, section=section)
        other_date = mommy.make(
            Trip,
            trips_year=trips_year,
            template__return_route=route,
            section__leaders_arrive=section.leaders_arrive + timedelta(days=100),
        )
        qs = Trip.objects.returns(
            route, section.return_to_campus, trips_year=trips_year
        )
        self.assertQsEqual(qs, [returning, overridden_return])

    def test_with_counts(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        mommy.make(IncomingStudent, trips_year=trips_year, trip_assignment=trip)
        trip = Trip.objects.with_counts(trips_year)[0]

        with self.assertNumQueries(0):
            self.assertEqual(trip.size, 1)
        self.assertEqual(trip.num_trippees, 1)
        self.assertEqual(trip.num_leaders, 0)


class CampsiteManagerTestCase(FytTestCase):
    def test_campsite_matrix(self):
        trips_year = self.init_trips_year()
        sxn = mommy.make(Section, trips_year=trips_year)
        campsite_a = mommy.make(Campsite, trips_year=trips_year)
        campsite_b = mommy.make(Campsite, trips_year=trips_year)
        campsite_c = mommy.make(Campsite, trips_year=trips_year)
        trip1 = mommy.make(
            Trip,
            trips_year=trips_year,
            section=sxn,
            template__campsite1=campsite_a,
            template__campsite2=campsite_b,
        )
        trip2 = mommy.make(
            Trip,
            trips_year=trips_year,
            section=sxn,
            template__campsite1=campsite_b,
            template__campsite2=campsite_c,
        )
        target = {
            campsite_a: {sxn.at_campsite1: [trip1], sxn.at_campsite2: []},
            campsite_b: {sxn.at_campsite1: [trip2], sxn.at_campsite2: [trip1]},
            campsite_c: {sxn.at_campsite1: [], sxn.at_campsite2: [trip2]},
        }
        actual = Campsite.objects.matrix(trips_year)
        self.assertEqual(target, actual)


class ViewsTestCase(FytTestCase):

    csrf_checks = False

    def test_create_scheduled_trip_from_matrix(self):
        trips_year = self.init_trips_year()
        section = mommy.make(Section, trips_year=trips_year)
        template = mommy.make(TripTemplate, trips_year=trips_year)
        url = reverse('core:trip:index', kwargs={'trips_year': trips_year})
        # get matrix
        resp = self.app.get(url, user=self.make_director())
        # click add -> CreateView
        resp = resp.click(description='<i class="fa fa-plus"></i>')
        # submit create form
        resp.form.submit()
        Trip.objects.get(section=section, template=template)

    def test_packet_shows_leader_med_info(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        trippee = mommy.make(
            Volunteer,
            trips_year=trips_year,
            trip_assignment=trip,
            medical_conditions='magic',
            food_allergies='mangoes',
            dietary_restrictions='gluten free',
            needs='dinosaurs',
            epipen=True,
        )
        url = reverse(
            'core:packets:trip', kwargs={'trips_year': trips_year, 'pk': trip.pk}
        )
        resp = self.app.get(url, user=self.make_director())
        self.assertContains(resp, 'magic')
        self.assertContains(resp, 'mangoes')
        self.assertContains(resp, 'gluten free')
        self.assertContains(resp, 'dinosaurs')
        self.assertContains(resp, 'Carries an EpiPen')

    def test_packet_can_hide_trippee_med_info(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        trippee = mommy.make(
            IncomingStudent,
            trips_year=trips_year,
            trip_assignment=trip,
            med_info='sparkles',
            hide_med_info=True,
            registration=mommy.make(
                Registration,
                trips_year=trips_year,
                medical_conditions='magic',
                needs='dinosaurs',
            ),
        )
        url = reverse(
            'core:packets:trip', kwargs={'trips_year': trips_year, 'pk': trip.pk}
        )
        resp = self.app.get(url, user=self.make_director())
        self.assertNotContains(resp, 'magic')
        self.assertNotContains(resp, 'dinosaurs')
        self.assertContains(resp, 'sparkles')

    def test_packet_shows_trippee_med_info_by_default(self):
        trips_year = self.init_trips_year()
        trip = mommy.make(Trip, trips_year=trips_year)
        trippee = mommy.make(
            IncomingStudent,
            trips_year=trips_year,
            trip_assignment=trip,
            hide_med_info=False,
            med_info='sparkles',
            registration=mommy.make(
                Registration,
                trips_year=trips_year,
                medical_conditions='magic',
                food_allergies='mangoes',
                dietary_restrictions='gluten free',
                needs='dinosaurs',
                epipen=True,
            ),
        )
        url = reverse(
            'core:packets:trip', kwargs={'trips_year': trips_year, 'pk': trip.pk}
        )
        resp = self.app.get(url, user=self.make_director())
        self.assertContains(resp, 'magic')
        self.assertContains(resp, 'mangoes')
        self.assertContains(resp, 'gluten free')
        self.assertContains(resp, 'dinosaurs')
        self.assertContains(resp, 'sparkles')
        self.assertContains(resp, 'Carries an EpiPen')


def s3_map_matcher(r1, r2):
    """Match on the S3 url, excluding auto-generated parts of the filename."""
    fragment = 'uploads/map'
    return fragment in r1.uri and fragment in r2.uri and r1.method == r2.method


vcr.register_matcher('s3_map.txt', s3_map_matcher)


@unittest.skip("need to fix VCR data/remove entirely")
class TripTemplateDocumentUploadTestCase(FytTestCase):
    @vcr.use_cassette(match_on=['s3_map.txt'])
    def test_uploaded_document_is_attached_to_TripTemplate(self):
        trips_year = self.init_trips_year()
        tt = mommy.make(TripTemplate, trips_year=trips_year)
        resp = self.app.get(tt.file_upload_url(), user=self.make_director())
        resp.form['name'] = 'Map'
        resp.form['file'] = webtest.Upload('map.txt', b'test data')
        resp.form.submit()

        tt.refresh_from_db()
        files = tt.documents.all()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, 'Map')

    @vcr.use_cassette(match_on=['s3_map.txt'])
    def test_triptemplate_documents_are_migrated(self):
        trips_year = self.init_trips_year()
        mommy.make(Timetable)
        tt = mommy.make(TripTemplate, trips_year=trips_year)
        resp = self.app.get(tt.file_upload_url(), user=self.make_director())
        resp.form['name'] = 'Map'
        resp.form['file'] = webtest.Upload('map.txt', b'test data')
        resp.form.submit()

        forward()
        tt = TripTemplate.objects.get(trips_year=trips_year.year + 1)
        files = tt.documents.all()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].name, 'Map')
