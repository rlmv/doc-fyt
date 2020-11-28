import itertools
import unittest
from datetime import date, datetime, time, timedelta

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.urls import reverse
from model_mommy import mommy
from model_mommy.recipe import Recipe, foreign_key

from fyt.core.mommy_recipes import trips_year
from fyt.incoming.models import IncomingStudent
from fyt.test import FytTestCase, vcr
from fyt.transport import maps
from fyt.transport.models import (
    ExternalBus,
    Hanover,
    InternalBus,
    Lodge,
    Route,
    Stop,
    StopOrder,
    TransportConfig,
    sort_by_distance,
)
from fyt.transport.signals import resolve_dropoff, resolve_pickup
from fyt.transport.templatetags.maps import lat_lng_dms
from fyt.transport.views import (
    EXCEEDS_CAPACITY,
    NOT_SCHEDULED,
    Riders,
    TransportChecklist,
    get_internal_issues_matrix,
    get_internal_rider_matrix,
    get_internal_route_matrix,
    preload_transported_trips,
    trip_transport_matrix,
)
from fyt.trips.models import Section, Trip


"""
TODO: rewrite matrix tests to only test _rider_matrix
"""

stoporder_recipe = Recipe(
    StopOrder,
    trips_year=foreign_key(trips_year),
    stop_type=itertools.cycle([StopOrder.PICKUP, StopOrder.DROPOFF]),
)


class TransportTestCase(FytTestCase):
    def init_transport_config(self):
        hanover = mommy.make(
            Stop,
            trips_year=self.trips_year,
            lat_lng='43.7031377,-72.2898190',
            address='6 N Main St, Hanover, NH 03755',
        )

        lodge = mommy.make(
            Stop, trips_year=self.trips_year, lat_lng='43.977253,-71.8154831'
        )

        self.transport_config = mommy.make(
            TransportConfig, trips_year=self.trips_year, hanover=hanover, lodge=lodge
        )


class StopModelTestCase(FytTestCase):
    def test_stop_is_protected_on_route_fk_deletion(self):
        self.init_trips_year()
        route = mommy.make(Route, trips_year=self.trips_year)
        stop = mommy.make(Stop, route=route, trips_year=self.trips_year)
        with self.assertRaises(ProtectedError):
            route.delete()

    def test_category_handles_null_routes(self):
        stop = mommy.make(Stop, route=None)
        self.assertEqual(stop.category, None)

    def test_location_prioritizes_lat_lng_if_available(self):
        stop = mommy.make(Stop, lat_lng='43.7030,-72.2895', address='address')
        self.assertEqual(stop.location, '43.7030,-72.2895')

    def test_location_with_address(self):
        stop = mommy.make(Stop, lat_lng='', address='address')
        self.assertEqual(stop.location, 'address')

    def test_no_lat_lng_or_address_raises_validation_error(self):
        stop = mommy.prepare(Stop, lat_lng='', address='')
        with self.assertRaises(ValidationError):
            stop.full_clean()

    def test___str__(self):
        self.assertEqual(str(mommy.prepare(Stop, name='Boston')), 'Boston')

    def test_external_requires_round_trip_cost(self):
        with self.assertRaisesRegex(ValidationError, 'require round-trip cost'):
            mommy.make(
                Stop,
                address='stub',
                cost_round_trip=None,
                cost_one_way=5,
                route__category=Route.EXTERNAL,
            ).full_clean()

    def test_external_requires_one_way_cost(self):
        with self.assertRaisesRegex(ValidationError, 'require one-way cost'):
            mommy.make(
                Stop,
                address='stub',
                cost_one_way=None,
                cost_round_trip=3,
                route__category=Route.EXTERNAL,
            ).full_clean()

    def test_external_requires_pickup_time(self):
        with self.assertRaisesRegex(ValidationError, 'require pickup time'):
            mommy.make(
                Stop,
                address='stub',
                cost_one_way=2,
                cost_round_trip=3,
                pickup_time=None,
                dropoff_time=time(8, 34, 2),
                route__category=Route.EXTERNAL,
            ).full_clean()

    def test_external_requires_dropoff_time(self):
        with self.assertRaisesRegex(ValidationError, 'require dropoff time'):
            mommy.make(
                Stop,
                address='stub',
                cost_one_way=2,
                cost_round_trip=3,
                pickup_time=time(8, 34, 2),
                dropoff_time=None,
                route__category=Route.EXTERNAL,
            ).full_clean()

    def test_internal_cannot_set_round_trip_cost(self):
        with self.assertRaisesRegex(ValidationError, 'cannot have a cost'):
            mommy.make(
                Stop,
                address='stub',
                cost_one_way=None,
                cost_round_trip=3,
                route__category=Route.INTERNAL,
            ).full_clean()

    def test_internal_cannot_set_one_way_cost(self):
        with self.assertRaisesRegex(ValidationError, 'cannot have a cost'):
            mommy.make(
                Stop,
                address='stub',
                cost_one_way=15,
                cost_round_trip=None,
                route__category=Route.INTERNAL,
            ).full_clean()

    def test_sort_by_distance_reverse(self):
        stop1 = mommy.make(Stop, distance=13)
        stop2 = mommy.make(Stop, distance=2)
        self.assertEqual([stop1, stop2], sort_by_distance([stop2, stop1], reverse=True))


class StopManagerTestCase(FytTestCase):
    def setUp(self):
        self.init_trips_year()

    def test_external(self):
        external_stop = mommy.make(
            Stop, trips_year=self.trips_year, route__category=Route.EXTERNAL
        )
        internal_stop = mommy.make(
            Stop, trips_year=self.trips_year, route__category=Route.INTERNAL
        )
        self.assertQsEqual(Stop.objects.external(self.trips_year), [external_stop])


class RouteManagerTestCase(FytTestCase):
    def setUp(self):
        self.init_trips_year()

    def test_external(self):
        external_route = mommy.make(
            Route, category=Route.EXTERNAL, trips_year=self.trips_year
        )
        internal_route = mommy.make(
            Route, category=Route.INTERNAL, trips_year=self.trips_year
        )
        self.assertQsEqual(Route.objects.external(self.trips_year), [external_route])

    def test_internal(self):
        external_route = mommy.make(
            Route, category=Route.EXTERNAL, trips_year=self.trips_year
        )
        internal_route = mommy.make(
            Route, category=Route.INTERNAL, trips_year=self.trips_year
        )
        self.assertQsEqual(Route.objects.internal(self.trips_year), [internal_route])


class InternalBusManagerTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()

    def test_internal(self):
        external = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.EXTERNAL
        )
        internal = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.INTERNAL
        )
        self.assertQsEqual(InternalBus.objects.internal(self.trips_year), [internal])


class TestViews(FytTestCase):
    def test_index_views(self):
        trips_year = self.init_trips_year()
        director = self.make_director()
        names = ['core:stop:index', 'core:route:index', 'core:vehicle:index']
        for name in names:
            url = reverse(name, kwargs={'trips_year': trips_year})
            self.app.get(url, user=director)


class InternalBusMatrixTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()

    def test_internal_matrix(self):
        route = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)

        section = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1)
        )

        transport = mommy.make(
            InternalBus, trips_year=self.trips_year, route=route, date=date(2015, 1, 2)
        )

        target = {
            route: {
                date(2015, 1, 2): transport,
                date(2015, 1, 3): None,
                date(2015, 1, 4): None,
                date(2015, 1, 5): None,
                date(2015, 1, 6): None,
            }
        }
        matrix = get_internal_route_matrix(self.trips_year)
        self.assertEqual(target, matrix)

    def test_internal_matrix_again(self):
        route1 = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)

        route2 = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)

        mommy.make(Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1))

        mommy.make(Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 2))

        transport1 = mommy.make(
            InternalBus, trips_year=self.trips_year, route=route1, date=date(2015, 1, 2)
        )

        transport2 = mommy.make(
            InternalBus, trips_year=self.trips_year, route=route2, date=date(2015, 1, 4)
        )

        target = {
            route1: {
                date(2015, 1, 2): transport1,
                date(2015, 1, 3): None,
                date(2015, 1, 4): None,
                date(2015, 1, 5): None,
                date(2015, 1, 6): None,
                date(2015, 1, 7): None,
            },
            route2: {
                date(2015, 1, 2): None,
                date(2015, 1, 3): None,
                date(2015, 1, 4): transport2,
                date(2015, 1, 5): None,
                date(2015, 1, 6): None,
                date(2015, 1, 7): None,
            },
        }
        matrix = get_internal_route_matrix(self.trips_year)
        self.assertEqual(target, matrix)

    @unittest.expectedFailure
    def test_preload_trips(self):
        route = mommy.make(Route, trips_year=self.trips_year)
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            dropoff_route=route,
            pickup_route=route,
            return_route=route,
        )

        dropoff_bus = mommy.make(
            InternalBus, trips_year=self.trips_year, date=trip.dropoff_date, route=route
        )

        pickup_bus = mommy.make(
            InternalBus, trips_year=self.trips_year, date=trip.pickup_date, route=route
        )

        return_bus = mommy.make(
            InternalBus, trips_year=self.trips_year, date=trip.return_date, route=route
        )

        preload_transported_trips(
            [dropoff_bus, pickup_bus, return_bus], self.trips_year
        )
        with self.assertNumQueries(0):
            self.assertQsEqual(dropoff_bus.dropping_off(), [trip])
            self.assertQsEqual(pickup_bus.picking_up(), [trip])
            self.assertQsEqual(return_bus.returning(), [trip])

    def test_trip_dropoff_matrix(self):
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__trips_year=self.trips_year,
            section__trips_year=self.trips_year,
            section__leaders_arrive=date(2015, 1, 1),
        )

        dropoff_matrix, pickup_matrix, return_matrix = trip_transport_matrix(
            self.trips_year
        )

        self.assertEqual(
            dropoff_matrix,
            {
                trip.template: {
                    date(2015, 1, 2): None,
                    date(2015, 1, 3): trip,
                    date(2015, 1, 4): None,
                    date(2015, 1, 5): None,
                    date(2015, 1, 6): None,
                }
            },
        )
        self.assertEqual(
            pickup_matrix,
            {
                trip.template: {
                    date(2015, 1, 2): None,
                    date(2015, 1, 3): None,
                    date(2015, 1, 4): None,
                    date(2015, 1, 5): trip,
                    date(2015, 1, 6): None,
                }
            },
        )
        self.assertEqual(
            return_matrix,
            {
                trip.template: {
                    date(2015, 1, 2): None,
                    date(2015, 1, 3): None,
                    date(2015, 1, 4): None,
                    date(2015, 1, 5): None,
                    date(2015, 1, 6): trip,
                }
            },
        )


class RidersMatrixTestCase(FytTestCase):
    def setUp(self):
        self.init_trips_year()

    def test_basic_matrix(self):
        route = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)
        section = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1)
        )
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section=section,
            template__dropoff_stop__route=route,
            template__pickup_stop__route=route,
            template__return_route=route,
        )
        n = trip.size
        target = {
            route: {
                date(2015, 1, 2): Riders(),
                date(2015, 1, 3): Riders(dropping_off=[trip]),
                date(2015, 1, 4): Riders(),
                date(2015, 1, 5): Riders(picking_up=[trip]),
                date(2015, 1, 6): Riders(returning=[trip]),
            }
        }
        self.assertEqual(target, get_internal_rider_matrix(self.trips_year))

    def test_rider_matrix_with_multiple_trips_overlap(self):
        route1 = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)
        route2 = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)
        section1 = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1)
        )
        section2 = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 2)
        )
        trip1 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section=section1,
            template__dropoff_stop__route=route1,
            template__pickup_stop__route=route1,
            template__return_route=route1,
        )
        trip2 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section=section2,
            template__dropoff_stop__route=route2,
            template__pickup_stop__route=route1,
            template__return_route=route2,
        )
        n = trip1.size
        m = trip2.size
        target = {
            route1: {
                date(2015, 1, 2): Riders(),
                date(2015, 1, 3): Riders(dropping_off=[trip1]),
                date(2015, 1, 4): Riders(),
                date(2015, 1, 5): Riders(picking_up=[trip1]),
                date(2015, 1, 6): Riders(picking_up=[trip2], returning=[trip1]),
                date(2015, 1, 7): Riders(),
            },
            route2: {
                date(2015, 1, 2): Riders(),
                date(2015, 1, 3): Riders(),
                date(2015, 1, 4): Riders(dropping_off=[trip2]),
                date(2015, 1, 5): Riders(),
                date(2015, 1, 6): Riders(),
                date(2015, 1, 7): Riders(returning=[trip2]),
            },
        }
        self.assertEqual(target, get_internal_rider_matrix(self.trips_year))

    def test_internal_riders_matrix_with_overriden_routes(self):
        route = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)
        section = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1)
        )
        # route is set *directly* on scheduled trip
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section=section,
            dropoff_route=route,
            pickup_route=route,
            return_route=route,
        )
        n = trip.size
        target = {
            route: {
                date(2015, 1, 2): Riders(),
                date(2015, 1, 3): Riders(dropping_off=[trip]),
                date(2015, 1, 4): Riders(),
                date(2015, 1, 5): Riders(picking_up=[trip]),
                date(2015, 1, 6): Riders(returning=[trip]),
            }
        }
        self.assertEqual(target, get_internal_rider_matrix(self.trips_year))


class IssuesMatrixTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()

    def test_unscheduled(self):
        route = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)
        section = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1)
        )
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section=section,
            template__dropoff_stop__route=route,
            template__pickup_stop__route=route,
            template__return_route=route,
        )
        target = {
            route: {
                date(2015, 1, 2): None,
                date(2015, 1, 3): NOT_SCHEDULED,
                date(2015, 1, 4): None,
                date(2015, 1, 5): NOT_SCHEDULED,
                date(2015, 1, 6): NOT_SCHEDULED,
            }
        }
        matrix = get_internal_issues_matrix(
            get_internal_route_matrix(self.trips_year),
            get_internal_rider_matrix(self.trips_year),
        )
        self.assertEqual(target, matrix)

    def test_exceeds_capacity(self):
        route = mommy.make(Route, trips_year=self.trips_year, category=Route.INTERNAL)
        section = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1)
        )

        trip1 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section=section,
            template__dropoff_stop__route=route,
            template__pickup_stop__route=route,
            template__return_route=route,
        )
        mommy.make(
            IncomingStudent,
            route.vehicle.capacity,
            trips_year=self.trips_year,
            trip_assignment=trip1,
        )

        trip2 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section=section,
            template__dropoff_stop__route=route,
            template__pickup_stop__route=route,
            template__return_route=route,
        )
        mommy.make(IncomingStudent, trips_year=self.trips_year, trip_assignment=trip2)

        mommy.make(
            InternalBus, trips_year=self.trips_year, route=route, date=date(2015, 1, 3)
        )
        mommy.make(
            InternalBus, trips_year=self.trips_year, route=route, date=date(2015, 1, 5)
        )
        mommy.make(
            InternalBus, trips_year=self.trips_year, route=route, date=date(2015, 1, 6)
        )

        target = {
            route: {
                date(2015, 1, 2): None,
                date(2015, 1, 3): EXCEEDS_CAPACITY,
                date(2015, 1, 4): None,
                date(2015, 1, 5): EXCEEDS_CAPACITY,
                date(2015, 1, 6): EXCEEDS_CAPACITY,
            }
        }
        matrix = get_internal_issues_matrix(
            get_internal_route_matrix(self.trips_year),
            get_internal_rider_matrix(self.trips_year),
        )

        self.assertEqual(target, matrix)


class RidersTestCase(unittest.TestCase):
    def setUp(self):
        self.r1 = Riders(returning=['t1', 't2'])
        self.r2 = Riders(dropping_off=['t3'], picking_up=['t4'], returning=['t5'])
        self.r3 = Riders(picking_up=['t6'])
        self.r4 = Riders(dropping_off=['t7'])

    def test__add__(self):
        new = self.r1 + self.r2
        self.assertEqual(new.dropping_off, {'t3'})
        self.assertEqual(new.picking_up, {'t4'})
        self.assertEqual(new.returning, {'t1', 't2', 't5'})

    def test__bool__(self):
        self.assertTrue(self.r1)
        self.assertTrue(self.r2)
        self.assertTrue(self.r3)
        self.assertTrue(self.r4)
        self.assertFalse(Riders())

    def test__eq__(self):
        self.assertEqual(Riders(), Riders())
        self.assertNotEqual(self.r1, self.r2)


class TransportChecklistTest(FytTestCase):
    def test_get_date(self):
        view = TransportChecklist()
        d = date(2015, 1, 1)
        view.kwargs = {'date': str(d)}
        self.assertEqual(view.date, d)


class ExternalBusManager(FytTestCase):
    def setUp(self):
        self.init_trips_year()

    def test_schedule_matrix(self):
        sxn1 = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        sxn2 = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        not_local_sxn = mommy.make(Section, trips_year=self.trips_year, is_local=False)

        route1 = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)

        route2 = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)

        internal = mommy.make(
            Route, trips_year=self.trips_year, category=Route.INTERNAL
        )

        transp1 = mommy.make(
            ExternalBus, trips_year=self.trips_year, route=route1, section=sxn2
        )

        transp2 = mommy.make(
            ExternalBus, trips_year=self.trips_year, route=route2, section=sxn1
        )

        matrix = ExternalBus.objects.schedule_matrix(self.trips_year)
        target = {
            route1: {sxn1: None, sxn2: transp1},
            route2: {sxn1: transp2, sxn2: None},
        }
        self.assertEqual(matrix, target)

    def test_simple_passengers_matrix_to_hanover(self):
        sxn = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        rt = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)
        passenger = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_round_trip__route=rt,
            trip_assignment__section=sxn,
        )

        target = {rt: {sxn: 1}}
        actual = ExternalBus.passengers.matrix_to_hanover(self.trips_year)

        self.assertEqual(target, actual)

    def test_passengers_matrix_to_hanover_with_multiples(self):
        sxn1 = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        sxn2 = mommy.make(Section, trips_year=self.trips_year, is_local=True)

        rt1 = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)

        psgr1 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_round_trip__route=rt1,
            trip_assignment__section=sxn1,
        )

        psgr2 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_to_hanover__route=rt1,
            trip_assignment__section=sxn1,
        )

        psgr3 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_to_hanover__route=rt1,
            bus_assignment_from_hanover__route=rt1,
            trip_assignment__section=sxn2,
        )

        not_psgr1 = mommy.make(
            IncomingStudent, trips_year=self.trips_year, bus_assignment__route=rt1
        )

        not_psgr2 = mommy.make(
            IncomingStudent, trips_year=self.trips_year, trip_assignment__section=sxn2
        )

        not_psgr3 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment__section=sxn2,
            bus_assignment_from_hanover__route=rt1,
        )

        # Student on a non-local section
        not_psgr4 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment__section__is_local=False,
            bus_assignment_to_hanover__route=rt1,
        )

        target = {rt1: {sxn1: 2, sxn2: 1}}
        actual = ExternalBus.passengers.matrix_to_hanover(self.trips_year)
        self.assertEqual(target, actual)

    def test_passengers_matrix_from_hanover(self):
        sxn1 = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        sxn2 = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        rt1 = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)

        psgr1 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_round_trip__route=rt1,
            trip_assignment__section=sxn1,
        )

        psgr2 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_from_hanover__route=rt1,
            trip_assignment__section=sxn1,
        )

        psgr3 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_to_hanover__route=rt1,
            bus_assignment_from_hanover__route=rt1,
            trip_assignment__section=sxn2,
        )

        not_psgr1 = mommy.make(
            IncomingStudent, trips_year=self.trips_year, bus_assignment__route=rt1
        )

        not_psgr2 = mommy.make(
            IncomingStudent, trips_year=self.trips_year, trip_assignment__section=sxn2
        )

        not_psgr3 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment__section=sxn2,
            bus_assignment_to_hanover__route=rt1,
        )

        target = {rt1: {sxn1: 2, sxn2: 1}}
        actual = ExternalBus.passengers.matrix_from_hanover(self.trips_year)
        self.assertEqual(target, actual)

    def test_invalid_riders(self):
        route = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)

        valid = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment__section__is_local=True,  # Local trip assignment
            bus_assignment_round_trip__route=route,
        )

        no_trip_to_hanover = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment=None,
            bus_assignment_to_hanover__route=route,
        )

        no_trip_from_hanover = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment=None,
            bus_assignment_from_hanover__route=route,
        )

        no_trip_round_trip = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment=None,
            bus_assignment_round_trip__route=route,
        )

        non_local_section = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            trip_assignment__section__is_local=False,
            bus_assignment_round_trip__route=route,
        )

        actual = ExternalBus.passengers.invalid_riders(self.trips_year)
        answer = [
            no_trip_to_hanover,
            no_trip_from_hanover,
            no_trip_round_trip,
            non_local_section,
        ]

        self.assertQsEqual(actual, answer)


class TransportViewsTestCase(TransportTestCase):

    csrf_checks = False

    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()

    def test_create_external_bus_from_matrix(self):
        route = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)
        section = mommy.make(Section, trips_year=self.trips_year, is_local=True)

        # Visit matrix page
        url = reverse('core:externalbus:matrix', kwargs={'trips_year': self.trips_year})
        res = self.app.get(url, user=self.make_director())
        # click 'add' button for the single entry
        res = res.click(description='<i class="fa fa-plus"></i>')
        # which takes us to the create page, prepopulated w/ data
        res = res.form.submit()
        # and hopefully creates a new tranport
        ExternalBus.objects.get(route=route, section=section)

    def test_schedule_internal_bus_from_matrix(self):
        route = mommy.make(
            Route, trips_year=self.trips_year, category=Route.INTERNAL, pk=1
        )
        section = mommy.make(
            Section, trips_year=self.trips_year, leaders_arrive=date(2015, 1, 1)
        )
        # visit matrix
        url = reverse('core:internalbus:index', kwargs={'trips_year': self.trips_year})
        resp = self.app.get(url, user=self.make_director())
        # click add
        resp = resp.click(linkid="1-2-2015-create-1")
        resp.form.submit()
        InternalBus.objects.get(date=date(2015, 1, 2), route=route)


class InternalTransportModelTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()

    def test_INTERNAL_validation(self):
        transport = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.EXTERNAL
        )

        with self.assertRaises(ValidationError):
            transport.full_clean()

    def test_unique_validation(self):
        transport = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.INTERNAL
        )

        with self.assertRaises(IntegrityError):
            mommy.make(
                InternalBus,
                trips_year=self.trips_year,
                route=transport.route,
                date=transport.date,
            )

    def test_get_stops_with_intermediate(self):
        bus = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.INTERNAL
        )

        stop1 = mommy.make(
            Stop, trips_year=self.trips_year, route=bus.route, distance=100
        )

        trip1 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop=stop1,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )

        stop2 = mommy.make(
            Stop, trips_year=self.trips_year, route=bus.route, distance=1
        )

        trip2 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__pickup_stop=stop2,
            section__leaders_arrive=bus.date - timedelta(days=4),
        )

        self.assertEqual(
            bus.all_stops,
            [Hanover(self.trips_year), stop2, stop1, Lodge(self.trips_year)],
        )

    def test_trips_are_added_to_stops(self):
        bus = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.INTERNAL
        )

        stop = mommy.make(Stop, trips_year=self.trips_year, route=bus.route)

        trip1 = mommy.make(  # dropping off
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop=stop,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )

        trip2 = mommy.make(  # picking up
            Trip,
            trips_year=self.trips_year,
            template__pickup_stop=stop,
            section__leaders_arrive=bus.date - timedelta(days=4),
        )

        trip3 = mommy.make(  # returning
            Trip,
            trips_year=self.trips_year,
            template__return_route=bus.route,
            section__leaders_arrive=bus.date - timedelta(days=5),
        )

        # should compress the two StopOrders to a single stop
        (hanover, stop, lodge, hanover_again) = bus.all_stops
        #  should set these fields:
        self.assertEqual(hanover.trips_dropped_off, [])
        self.assertEqual(hanover.trips_picked_up, [trip1])
        self.assertEqual(stop.trips_dropped_off, [trip1])
        self.assertEqual(stop.trips_picked_up, [trip2])
        self.assertEqual(lodge.trips_dropped_off, [trip2])
        self.assertEqual(lodge.trips_picked_up, [trip3])
        self.assertEqual(hanover_again.trips_dropped_off, [trip3])
        self.assertEqual(hanover_again.trips_picked_up, [])

    def test_dont_go_to_lodge_if_no_pickups_or_returns(self):
        bus = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.INTERNAL
        )
        stop = mommy.make(Stop, trips_year=self.trips_year, route=bus.route)
        trip1 = mommy.make(  # dropping off
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop=stop,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )
        stops = bus.all_stops
        self.assertEqual(stops, [Hanover(self.trips_year), stop])

    def test_go_to_lodge_if_returns(self):
        bus = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.INTERNAL
        )
        trip1 = mommy.make(  # returning to campus
            Trip,
            trips_year=self.trips_year,
            template__return_route=bus.route,
            section__leaders_arrive=bus.date - timedelta(days=5),
        )
        self.assertEqual(
            bus.all_stops,
            [
                Hanover(self.trips_year),
                Lodge(self.trips_year),
                Hanover(self.trips_year),
            ],
        )
        stops = bus.all_stops
        self.assertQsEqual(bus.returning(), stops[1].trips_picked_up)
        self.assertQsEqual(bus.returning(), stops[2].trips_dropped_off)

    def test_capacity_still_has_space(self):
        bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            route__category=Route.INTERNAL,
            route__vehicle__capacity=2,
        )
        stop = mommy.make(Stop, trips_year=self.trips_year, route=bus.route)
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop=stop,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )
        mommy.make(IncomingStudent, 2, trips_year=self.trips_year, trip_assignment=trip)
        self.assertFalse(bus.over_capacity())

    def test_capacity_over(self):
        bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            route__category=Route.INTERNAL,
            route__vehicle__capacity=1,
        )
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=bus.route,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )
        mommy.make(IncomingStudent, 2, trips_year=self.trips_year, trip_assignment=trip)
        self.assertTrue(bus.over_capacity())

    def test_capacity_complex(self):
        bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            route__category=Route.INTERNAL,
            route__vehicle__capacity=2,
        )
        stop1 = mommy.make(
            Stop, trips_year=self.trips_year, route=bus.route, distance=1
        )
        stop2 = mommy.make(
            Stop, trips_year=self.trips_year, route=bus.route, distance=2
        )
        trip1 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop=stop2,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )
        trip2 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__pickup_stop=stop1,
            section__leaders_arrive=bus.date - timedelta(days=4),
        )
        mommy.make(
            IncomingStudent, 2, trips_year=self.trips_year, trip_assignment=trip1
        )
        mommy.make(
            IncomingStudent, 2, trips_year=self.trips_year, trip_assignment=trip2
        )

        # Route looks like this:
        # Hanover - pickup trip1
        # stop1 - pickup trip2
        # stop2 - dropoff trip1
        # Lodge - dropoff trip2
        # ...which, since both trips have 2 people, is over capacity.

        self.assertTrue(bus.over_capacity())


# TODO: move back to ^^
class RefactorTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()
        self.maxDiff = None

    def test_creating_bus_generates_ordering(self):
        bus_date = date(2015, 1, 1)
        route = mommy.make(Route, trips_year=self.trips_year)
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=route,
            section__leaders_arrive=bus_date - timedelta(days=2),
        )

        bus = InternalBus.objects.create(
            trips_year=self.trips_year, route=route, date=bus_date
        )

        self.assertQsContains(
            bus.get_stop_ordering(),
            [{'bus': bus, 'trip': trip, 'stop_type': StopOrder.DROPOFF}],
        )

        bus.delete()

        self.assertQsEqual(bus.get_stop_ordering(), [])

    def test_scheduling_trip_adds_to_ordering(self):
        bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date(2015, 1, 1),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        stop1 = mommy.make(
            Stop, trips_year=self.trips_year, route=bus.route, distance=1
        )

        trip1 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop=stop1,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )

        stop2 = mommy.make(
            Stop, trips_year=self.trips_year, route=bus.route, distance=2
        )

        trip2 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__pickup_stop=stop2,
            section__leaders_arrive=bus.date - timedelta(days=4),
        )

        self.assertQsContains(
            bus.get_stop_ordering(),
            [
                {'bus': bus, 'trip': trip1, 'stop_type': StopOrder.DROPOFF, 'order': 1},
                {'bus': bus, 'trip': trip2, 'stop_type': StopOrder.PICKUP, 'order': 2},
            ],
        )

        trip1.delete()
        trip2.delete()

        self.assertQsEqual(bus.get_stop_ordering(), [])

    def test_changing_trip_route_changes_ordering(self):
        bus1 = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date(2015, 1, 1),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        bus2 = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date(2015, 1, 1),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        trip1 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=bus1.route,
            template__dropoff_stop__distance=1,
            section__leaders_arrive=bus1.date - timedelta(days=2),
        )

        trip2 = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__pickup_stop__route=bus1.route,
            template__pickup_stop__distance=7,
            section__leaders_arrive=bus1.date - timedelta(days=4),
        )

        # Move trip1 to a different route
        trip1.dropoff_route = bus2.route
        trip1.save()

        self.assertQsContains(
            bus1.get_stop_ordering(),
            [{'bus': bus1, 'trip': trip2, 'stop_type': StopOrder.PICKUP}],
        )
        self.assertQsContains(
            bus2.get_stop_ordering(),
            [{'bus': bus2, 'trip': trip1, 'stop_type': StopOrder.DROPOFF, 'order': 1}],
        )

        # Then move trip2
        trip2.pickup_route = bus2.route
        trip2.save()

        self.assertQsContains(bus1.get_stop_ordering(), [])
        self.assertQsContains(
            bus2.get_stop_ordering(),
            [
                {'bus': bus2, 'trip': trip1, 'stop_type': StopOrder.DROPOFF},
                {'bus': bus2, 'trip': trip2, 'stop_type': StopOrder.PICKUP},
            ],
        )

        # Move both trips to an unscheduled route
        trip1.dropoff_route = mommy.make(Route, trips_year=self.trips_year)
        trip1.save()
        trip2.pickup_route = mommy.make(Route, trips_year=self.trips_year)
        trip2.save()

        self.assertQsEqual(bus1.get_stop_ordering(), [])
        self.assertQsEqual(bus2.get_stop_ordering(), [])

        # Now, move the trips back to a scheduled bus
        trip1.dropoff_route = bus1.route
        trip1.save()
        trip2.pickup_route = bus1.route
        trip2.save()

        self.assertQsContains(
            bus1.get_stop_ordering(),
            [
                {'bus': bus1, 'trip': trip1, 'stop_type': StopOrder.DROPOFF},
                {'bus': bus1, 'trip': trip2, 'stop_type': StopOrder.PICKUP},
            ],
        )
        self.assertQsEqual(bus2.get_stop_ordering(), [])

    def test_changing_stop_route_updates_ordering(self):
        date_leaders_arrive = date(2015, 1, 1)

        bus1 = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        bus2 = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=bus1.route,
            template__pickup_stop__route=bus2.route,
            section__leaders_arrive=date_leaders_arrive,
        )

        self.assertQsContains(
            bus1.get_stop_ordering(),
            [{'bus': bus1, 'trip': trip, 'stop_type': StopOrder.DROPOFF}],
        )
        self.assertQsContains(
            bus2.get_stop_ordering(),
            [{'bus': bus2, 'trip': trip, 'stop_type': StopOrder.PICKUP}],
        )

        # Change routes to a non-running bus
        trip.template.dropoff_stop.route = bus2.route
        trip.template.dropoff_stop.save()
        trip.template.pickup_stop.route = bus1.route
        trip.template.pickup_stop.save()

        self.assertQsContains(bus1.get_stop_ordering(), [])
        self.assertQsContains(bus2.get_stop_ordering(), [])

        # Revert the routes
        trip.template.dropoff_stop.route = bus1.route
        trip.template.dropoff_stop.save()
        trip.template.pickup_stop.route = bus2.route
        trip.template.pickup_stop.save()

        self.assertQsContains(
            bus1.get_stop_ordering(),
            [{'bus': bus1, 'trip': trip, 'stop_type': StopOrder.DROPOFF}],
        )
        self.assertQsContains(
            bus2.get_stop_ordering(),
            [{'bus': bus2, 'trip': trip, 'stop_type': StopOrder.PICKUP}],
        )

    def test_changing_template_stop_updates_ordering(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__pickup_stop__route=pickup_bus.route,
            section__leaders_arrive=date_leaders_arrive,
        )

        self.assertQsContains(
            dropoff_bus.get_stop_ordering(),
            [{'bus': dropoff_bus, 'trip': trip, 'stop_type': StopOrder.DROPOFF}],
        )
        self.assertQsContains(
            pickup_bus.get_stop_ordering(),
            [{'bus': pickup_bus, 'trip': trip, 'stop_type': StopOrder.PICKUP}],
        )

        # Switch to a new stop on same route
        new_dropoff_stop = mommy.make(
            Stop, trips_year=self.trips_year, route=dropoff_bus.route
        )
        trip.template.dropoff_stop = new_dropoff_stop
        trip.template.save()

        new_pickup_stop = mommy.make(
            Stop, trips_year=self.trips_year, route=pickup_bus.route
        )
        trip.template.pickup_stop = new_pickup_stop
        trip.template.save()

        self.assertQsContains(
            dropoff_bus.get_stop_ordering(),
            [
                {
                    'bus': dropoff_bus,
                    'trip': trip,
                    'stop': new_dropoff_stop,
                    'stop_type': StopOrder.DROPOFF,
                }
            ],
        )
        self.assertQsContains(
            pickup_bus.get_stop_ordering(),
            [
                {
                    'bus': pickup_bus,
                    'trip': trip,
                    'stop': new_pickup_stop,
                    'stop_type': StopOrder.PICKUP,
                }
            ],
        )

        # On a different route
        trip.template.dropoff_stop = mommy.make(Stop)
        trip.template.pickup_stop = mommy.make(Stop)
        trip.template.save()

        self.assertQsContains(dropoff_bus.get_stop_ordering(), [])
        self.assertQsContains(pickup_bus.get_stop_ordering(), [])

    def test_changing_section_dates_updates_ordering(self):
        date_leaders_arrive = date(2015, 1, 1)

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            section__leaders_arrive=date_leaders_arrive,
            dropoff_route__trips_year=self.trips_year,
            pickup_route__trips_year=self.trips_year,
        )

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route=trip.get_dropoff_route(),
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route=trip.get_pickup_route(),
        )

        new_dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=3),
            route=trip.get_dropoff_route(),
        )

        new_pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=5),
            route=trip.get_pickup_route(),
        )

        self.assertQsContains(
            dropoff_bus.get_stop_ordering(),
            [{'bus': dropoff_bus, 'trip': trip, 'stop_type': StopOrder.DROPOFF}],
        )
        self.assertQsContains(
            pickup_bus.get_stop_ordering(),
            [{'bus': pickup_bus, 'trip': trip, 'stop_type': StopOrder.PICKUP}],
        )

        trip.section.leaders_arrive = date(2015, 1, 2)
        trip.section.save()

        self.assertQsContains(dropoff_bus.get_stop_ordering(), [])
        self.assertQsContains(pickup_bus.get_stop_ordering(), [])

        self.assertQsContains(
            new_dropoff_bus.get_stop_ordering(),
            [{'bus': new_dropoff_bus, 'trip': trip, 'stop_type': StopOrder.DROPOFF}],
        )
        self.assertQsContains(
            new_pickup_bus.get_stop_ordering(),
            [{'bus': new_pickup_bus, 'trip': trip, 'stop_type': StopOrder.PICKUP}],
        )


class StopOrderTestCase(FytTestCase):
    def setUp(self):
        self.init_trips_year()

    def test_stop_property(self):
        stop = mommy.make(Stop)
        o = mommy.make(
            StopOrder, trip__template__dropoff_stop=stop, stop_type=StopOrder.DROPOFF
        )
        self.assertEqual(o.stop, stop)
        o = mommy.make(
            StopOrder, trip__template__pickup_stop=stop, stop_type=StopOrder.PICKUP
        )
        self.assertEqual(o.stop, stop)

    def test_stoporder_order_is_automatically_populated(self):
        order = StopOrder(
            trips_year=self.trips_year,
            bus=mommy.make(InternalBus, trips_year=self.trips_year),
            trip=mommy.make(
                Trip, trips_year=self.trips_year, template__dropoff_stop__distance=3
            ),
            stop_type=StopOrder.DROPOFF,
        )

        order.save()
        self.assertEqual(order.order, 3)

    def test_stoporder_view_creates_missing_objects(self):
        bus = mommy.make(InternalBus, trips_year=self.trips_year)
        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            dropoff_route=bus.route,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )

        url = reverse(
            'core:internalbus:order',
            kwargs={'trips_year': self.trips_year, 'bus_pk': bus.pk},
        )
        self.app.get(url, user=self.make_director())
        so = StopOrder.objects.get(
            bus=bus,
            trip=trip,
            stop_type=StopOrder.DROPOFF,
            order=trip.template.dropoff_stop.distance,
        )

    def test_default_manager_ordering(self):
        o1 = mommy.make(StopOrder, order=4)
        o2 = mommy.make(StopOrder, order=1)
        self.assertQsEqual(StopOrder.objects.all(), [o2, o1], ordered=True)

    def test_select_related_stop(self):
        mommy.make(StopOrder)
        with self.assertNumQueries(1):
            [so.stop for so in StopOrder.objects.all()]

    def test_is_pickup(self):
        pickup = mommy.make(StopOrder, stop_type=StopOrder.PICKUP)
        dropoff = mommy.make(StopOrder, stop_type=StopOrder.DROPOFF)
        self.assertTrue(pickup.is_pickup)
        self.assertFalse(dropoff.is_pickup)

    def test_is_dropoff(self):
        pickup = mommy.make(StopOrder, stop_type=StopOrder.PICKUP)
        dropoff = mommy.make(StopOrder, stop_type=StopOrder.DROPOFF)
        self.assertFalse(pickup.is_dropoff)
        self.assertTrue(dropoff.is_dropoff)


class ExternalBusModelTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()

    def test_EXTERNAL_validation(self):
        transport = mommy.make(ExternalBus, route__category=Route.INTERNAL)
        with self.assertRaises(ValidationError):
            transport.full_clean()

    def test_unique_validation(self):
        transport = mommy.make(
            ExternalBus, trips_year=self.trips_year, route__category=Route.EXTERNAL
        )
        with self.assertRaises(IntegrityError):
            mommy.make(
                ExternalBus,
                trips_year=self.trips_year,
                route=transport.route,
                section=transport.section,
            )

    def test_get_stops_to_hanover(self):
        sxn = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        rt = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)
        stop1 = mommy.make(Stop, trips_year=self.trips_year, route=rt, distance=3)
        psngr1 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_round_trip=stop1,
            trip_assignment__section=sxn,
        )
        stop2 = mommy.make(Stop, trips_year=self.trips_year, route=rt, distance=100)
        psngr2 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_to_hanover=stop2,
            trip_assignment__section=sxn,
        )
        bus = mommy.make(ExternalBus, trips_year=self.trips_year, route=rt, section=sxn)
        stops = bus.get_stops_to_hanover()
        self.assertEqual(stops[0], stop2)
        self.assertEqual(getattr(stops[0], bus.DROPOFF_ATTR), [])
        self.assertEqual(getattr(stops[0], bus.PICKUP_ATTR), [psngr2])
        self.assertEqual(stops[1], stop1)
        self.assertEqual(getattr(stops[1], bus.DROPOFF_ATTR), [])
        self.assertEqual(getattr(stops[1], bus.PICKUP_ATTR), [psngr1])
        self.assertEqual(stops[2], Hanover(self.trips_year))
        self.assertEqual(getattr(stops[2], bus.DROPOFF_ATTR), [psngr1, psngr2])
        self.assertEqual(getattr(stops[2], bus.PICKUP_ATTR), [])
        self.assertEqual(len(stops), 3)

    def test_get_stops_from_hanover(self):
        sxn = mommy.make(Section, trips_year=self.trips_year, is_local=True)
        rt = mommy.make(Route, trips_year=self.trips_year, category=Route.EXTERNAL)
        stop1 = mommy.make(Stop, trips_year=self.trips_year, route=rt, distance=5)
        psngr1 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_round_trip=stop1,
            trip_assignment__section=sxn,
        )
        stop2 = mommy.make(Stop, trips_year=self.trips_year, route=rt, distance=100)
        psngr2 = mommy.make(
            IncomingStudent,
            trips_year=self.trips_year,
            bus_assignment_from_hanover=stop2,
            trip_assignment__section=sxn,
        )
        bus = mommy.make(ExternalBus, trips_year=self.trips_year, route=rt, section=sxn)
        stops = bus.get_stops_from_hanover()
        self.assertEqual(stops[0], Hanover(self.trips_year))
        self.assertEqual(getattr(stops[0], bus.DROPOFF_ATTR), [])
        self.assertEqual(getattr(stops[0], bus.PICKUP_ATTR), [psngr1, psngr2])
        self.assertEqual(stops[1], stop1)
        self.assertEqual(getattr(stops[1], bus.DROPOFF_ATTR), [psngr1])
        self.assertEqual(getattr(stops[1], bus.PICKUP_ATTR), [])
        self.assertEqual(stops[2], stop2)
        self.assertEqual(getattr(stops[2], bus.DROPOFF_ATTR), [psngr2])
        self.assertEqual(getattr(stops[2], bus.PICKUP_ATTR), [])
        self.assertEqual(len(stops), 3)

    def test_date_to_hanover(self):
        bus = mommy.make(ExternalBus, section__leaders_arrive=date(2015, 1, 1))
        self.assertEqual(bus.date_to_hanover, date(2015, 1, 2))

    def test_date_from_hanover(self):
        bus = mommy.make(ExternalBus, section__leaders_arrive=date(2015, 1, 1))
        self.assertEqual(bus.date_from_hanover, date(2015, 1, 6))


class InternalBusTimingTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_old_trips_year()
        self.init_transport_config()

    @vcr.use_cassette
    def test_stop_times(self):
        bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            route__category=Route.INTERNAL,
            date=date(2015, 1, 1),
        )

        picked_up = mommy.make(
            Trip,
            trips_year=self.trips_year,
            pickup_route=bus.route,
            template__pickup_stop__lat_lng='Plymouth, NH',
            template__pickup_stop__distance=1,
            section__leaders_arrive=bus.date - timedelta(days=4),
        )

        dropped_off = mommy.make(
            Trip,
            trips_year=self.trips_year,
            dropoff_route=bus.route,
            template__dropoff_stop__address='Burlington, VT',
            template__dropoff_stop__distance=4,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )

        directions = bus.update_stop_times()
        self.assertEqual(bus.get_departure_time(), datetime(2015, 1, 1, 7, 30))

        self.assertEqual(picked_up.get_pickup_time(), time(8, 34, 2))
        self.assertEqual(dropped_off.get_dropoff_time(), time(11, 9, 44))

        self.assertEqual(picked_up.get_dropoff_time(), None)
        self.assertEqual(dropped_off.get_pickup_time(), None)

        self.assertEqual(directions.legs[0].start_time, time(7, 30))
        self.assertEqual(directions.legs[0].end_time, time(8, 34, 2))

        self.assertEqual(directions.legs[1].start_time, time(8, 49, 2))
        self.assertEqual(directions.legs[1].end_time, time(11, 9, 44))

        self.assertEqual(directions.legs[2].start_time, time(11, 24, 44))
        self.assertEqual(directions.legs[2].end_time, time(13, 27, 35))

    @vcr.use_cassette
    def test_stop_times_delayed_for_lodge(self):
        bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            route__category=Route.INTERNAL,
            date=date(2015, 1, 1),
        )

        dropped_off = mommy.make(
            Trip,
            trips_year=self.trips_year,
            dropoff_route=bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__dropoff_stop__distance=4,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )

        picked_up = mommy.make(
            Trip,
            trips_year=self.trips_year,
            pickup_route=bus.route,
            template__pickup_stop__lat_lng='43.704312, -72.298208',
            template__pickup_stop__distance=5,
            section__leaders_arrive=bus.date - timedelta(days=4),
        )

        bus.update_stop_times()
        self.assertEqual(bus.get_departure_time(), datetime(2015, 1, 1, 9, 15, 20))

        self.assertEqual(dropped_off.get_dropoff_time(), time(9, 23, 57))
        self.assertEqual(picked_up.get_pickup_time(), time(9, 48, 33))

        self.assertEqual(dropped_off.get_pickup_time(), None)
        self.assertEqual(picked_up.get_dropoff_time(), None)

    @vcr.use_cassette
    def test_stoporder_time_is_up_to_date(self):
        bus = mommy.make(
            InternalBus, trips_year=self.trips_year, route__category=Route.INTERNAL
        )

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            dropoff_route=bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__dropoff_stop__distance=4,
            section__leaders_arrive=bus.date - timedelta(days=2),
        )

        stoporder = trip.get_dropoff_stoporder()
        self.assertIsNone(stoporder.computed_time)

        # Accessing the `time` property computes times, and updates
        # the `computed_time` field
        self.assertEqual(stoporder.time, time(7, 38, 37))
        self.assertEqual(stoporder.computed_time, time(7, 38, 37))

    @vcr.use_cassette
    def test_resolve_dropoff_or_pickup_sets_dirty_flag(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        # Dropoffs:
        self.assertTrue(dropoff_bus.dirty)
        dropoff_bus.update_stop_times()
        dropoff_bus.refresh_from_db()
        self.assertFalse(dropoff_bus.dirty)
        resolve_dropoff(trip)
        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)

        # Same for pickups:
        self.assertTrue(pickup_bus.dirty)
        pickup_bus.update_stop_times()
        pickup_bus.refresh_from_db()
        self.assertFalse(pickup_bus.dirty)
        resolve_pickup(trip)
        pickup_bus.refresh_from_db()
        self.assertTrue(pickup_bus.dirty)

    def test_changing_stop_addresses_marks_bus_as_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__dropoff_stop__trips_year=self.trips_year,
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__trips_year=self.trips_year,
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark buses as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()
        pickup_bus.dirty = False
        pickup_bus.save()

        # Change addresses of stops on the route
        trip.template.pickup_stop.address = '12 Sargent St, Hanover, NH 03755'
        trip.template.pickup_stop.save()
        trip.template.dropoff_stop.lat_lng = '43.705639,-72.297404'
        trip.template.dropoff_stop.save()

        dropoff_bus.refresh_from_db()
        pickup_bus.refresh_from_db()

        self.assertTrue(dropoff_bus.dirty)
        self.assertTrue(dropoff_bus.dirty)

    def test_changing_hanover_marks_all_buses_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        other_year_bus = mommy.make(InternalBus, trips_year=self.old_trips_year)

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark buses as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()
        pickup_bus.dirty = False
        pickup_bus.save()
        other_year_bus.dirty = False
        other_year_bus.save()

        config = TransportConfig.objects.get(trips_year=self.trips_year)
        config.hanover = mommy.make(Stop, trips_year=self.trips_year)
        config.save()

        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)
        pickup_bus.refresh_from_db()
        self.assertTrue(pickup_bus.dirty)
        other_year_bus.refresh_from_db()
        self.assertFalse(other_year_bus.dirty)

    def test_changing_lodge_marks_all_buses_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        other_year_bus = mommy.make(InternalBus, trips_year=self.old_trips_year)

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark buses as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()
        pickup_bus.dirty = False
        pickup_bus.save()
        other_year_bus.dirty = False
        other_year_bus.save()

        config = TransportConfig.objects.get(trips_year=self.trips_year)
        config.lodge = mommy.make(Stop, trips_year=self.trips_year)
        config.save()

        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)
        pickup_bus.refresh_from_db()
        self.assertTrue(pickup_bus.dirty)
        other_year_bus.refresh_from_db()
        self.assertFalse(other_year_bus.dirty)

    def test_changing_hanover_address_marks_all_buses_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        other_year_bus = mommy.make(InternalBus, trips_year=self.old_trips_year)

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark buses as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()
        pickup_bus.dirty = False
        pickup_bus.save()
        other_year_bus.dirty = False
        other_year_bus.save()

        hanover = Hanover(self.trips_year)
        hanover.address = '1497 Something New Rd.'
        hanover.save()

        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)
        pickup_bus.refresh_from_db()
        self.assertTrue(pickup_bus.dirty)
        other_year_bus.refresh_from_db()
        self.assertFalse(other_year_bus.dirty)

    def test_changing_hanover_lat_lng_marks_all_buses_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        other_year_bus = mommy.make(InternalBus, trips_year=self.old_trips_year)

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark buses as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()
        pickup_bus.dirty = False
        pickup_bus.save()
        other_year_bus.dirty = False
        other_year_bus.save()

        hanover = Hanover(self.trips_year)
        hanover.lat_lng = '43.7030,-72.2895'
        hanover.save()

        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)
        pickup_bus.refresh_from_db()
        self.assertTrue(pickup_bus.dirty)
        other_year_bus.refresh_from_db()
        self.assertFalse(other_year_bus.dirty)

    def test_changing_lodge_address_marks_all_buses_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        other_year_bus = mommy.make(InternalBus, trips_year=self.old_trips_year)

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark buses as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()
        pickup_bus.dirty = False
        pickup_bus.save()
        other_year_bus.dirty = False
        other_year_bus.save()

        lodge = Lodge(self.trips_year)
        lodge.address = '1497 Something New Rd.'
        lodge.save()

        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)
        pickup_bus.refresh_from_db()
        self.assertTrue(pickup_bus.dirty)
        other_year_bus.refresh_from_db()
        self.assertFalse(other_year_bus.dirty)

    def test_changing_lodge_lat_lng_marks_all_buses_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        other_year_bus = mommy.make(InternalBus, trips_year=self.old_trips_year)

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            template__dropoff_stop__address='92 Lyme Rd, Hanover, NH 03755',
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark buses as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()
        pickup_bus.dirty = False
        pickup_bus.save()
        other_year_bus.dirty = False
        other_year_bus.save()

        lodge = Lodge(self.trips_year)
        lodge.lat_lng = '43.705639,-72.297404'
        lodge.save()

        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)
        pickup_bus.refresh_from_db()
        self.assertTrue(pickup_bus.dirty)
        other_year_bus.refresh_from_db()
        self.assertFalse(other_year_bus.dirty)

    def test_changing_ordering_marks_bus_as_dirty(self):
        date_leaders_arrive = date(2015, 1, 1)

        dropoff_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=2),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
        )

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__dropoff_stop__route=dropoff_bus.route,
            section__leaders_arrive=date_leaders_arrive,
        )

        # Mark bus as having computed times
        dropoff_bus.dirty = False
        dropoff_bus.save()

        # Update the StopOrder
        ordering = trip.get_dropoff_stoporder()
        ordering.order = 400
        ordering.save()

        dropoff_bus.refresh_from_db()
        self.assertTrue(dropoff_bus.dirty)

    @vcr.use_cassette
    def test_use_custom_times(self):
        date_leaders_arrive = date(2015, 1, 1)

        pickup_bus = mommy.make(
            InternalBus,
            trips_year=self.trips_year,
            date=date_leaders_arrive + timedelta(days=4),
            route__category=Route.INTERNAL,
            route__trips_year=self.trips_year,
            dirty=False,
        )

        trip = mommy.make(
            Trip,
            trips_year=self.trips_year,
            template__pickup_stop__route=pickup_bus.route,
            template__pickup_stop__address='92 Lyme Rd, Hanover, NH 03755',
            section__leaders_arrive=date_leaders_arrive,
        )

        stoporder = pickup_bus.stoporder_set.get(trip=trip)
        stoporder.computed_time = time(9, 00)
        stoporder.custom_time = time(13, 00)
        stoporder.save()

        self.assertEqual(stoporder.time, time(9, 00))

        pickup_bus.use_custom_times = True
        pickup_bus.save()

        self.assertEqual(stoporder.time, time(13, 00))

        legs = pickup_bus.update_stop_times().legs
        self.assertIsNone(legs[0].start_time)
        self.assertIsNone(legs[0].end_time)
        self.assertEqual(legs[1].start_time, time(13, 00))
        self.assertIsNone(legs[1].end_time)


class MapsTestCase(TransportTestCase):
    def setUp(self):
        self.init_trips_year()
        self.init_transport_config()

    def test_split_stops_handling(self):
        orig, waypoints, dest = maps._split_stops(
            [Hanover(self.trips_year), Lodge(self.trips_year)]
        )
        self.assertEqual(orig, Hanover(self.trips_year).location)
        self.assertEqual(waypoints, [])
        self.assertEqual(dest, Lodge(self.trips_year).location)

    @vcr.use_cassette
    def test_directions_handles_more_than_max_waypoints(self):
        """ Google maps restricts the number of waypoints per request."""
        stops = [
            mommy.make(Stop, trips_year=self.trips_year, lat_lng=coord)
            for coord in (
                '43.705639,-72.297404',
                '43.680288,-72.527876',
                '43.779934,-72.042908',
                '43.753303,-72.124643',
                '43.703049,-72.289567',
                '43.705639,-72.297404',
                '44.831956,-71.075664',
                '44.875039,-71.05471',
                '43.736252,-72.2519',
                '43.788074,-72.099655',
                '44.227489,-71.477737',
                '43.705639,-72.297404',
                '43.680288,-72.527876',
                '43.779934,-72.042908',
                '43.753303,-72.124643',
                '43.703049,-72.289567',
                '43.705639,-72.297404',
                '44.831956,-71.075664',
                '44.875039,-71.05471',
                '43.736252,-72.2519',
                '43.788074,-72.099655',
                '44.227489,-71.477737',
                '43.705639,-72.297404',
                '44.831956,-71.075664',
                '43.753303,-72.124643',
                '43.703049,-72.289567',
            )
        ]
        directions = maps.get_directions(stops)
        self.assertEqual(len(stops), len(directions.legs) + 1)
        for i, leg in enumerate(directions.legs):
            self.assertEqual(leg.start_stop, stops[i])
            self.assertEqual(leg.end_stop, stops[i + 1])

    def test_directions_with_one_stop_raises_error(self):
        with self.assertRaisesRegex(maps.MapError, 'Only one stop provided'):
            maps.get_directions([Hanover(self.trips_year)])


class LatLngTestCase(FytTestCase):
    def test_formatting(self):
        pairs = [
            ('43.736252, -72.251900', """43°44'10.5"N 72°15'06.8"W"""),
            ('43.977253,-71.8154831', """43°58'38.1"N 71°48'55.7"W"""),
            ('44.875039,-71.05471', """44°52'30.1"N 71°03'17.0"W"""),
            ('39.868318, -75.385580', """39°52'05.9"N 75°23'08.1"W"""),
            ('55.665117, 37.476230', """55°39'54.4"N 37°28'34.4"E"""),
            ('-43.562906, 171.029122', """43°33'46.5"S 171°01'44.8"E"""),
            ('6.255361, -75.037554', """6°15'19.3"N 75°02'15.2"W"""),
            ('-49.291034, -73.096607', """49°17'27.7"S 73°05'47.8"W"""),
        ]

        for dd, dms in pairs:
            self.assertEqual(lat_lng_dms(dd), dms)
