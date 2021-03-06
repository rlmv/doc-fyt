from collections import defaultdict, namedtuple
from datetime import datetime

from braces.views import FormValidMessageMixin
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.functional import cached_property
from raven.contrib.django.raven_compat.models import client as sentry
from vanilla.views import FormView, TemplateView

from fyt.core.views import (
    DatabaseCreateView,
    DatabaseDeleteView,
    DatabaseDetailView,
    DatabaseListView,
    DatabaseTemplateView,
    DatabaseUpdateView,
    TripsYearMixin,
)
from fyt.incoming.models import IncomingStudent
from fyt.permissions.views import (
    DatabaseEditPermissionRequired,
    DatabaseReadPermissionRequired,
)
from fyt.transport.forms import StopOrderFormset
from fyt.transport.models import (
    ExternalBus,
    Hanover,
    InternalBus,
    Lodge,
    Route,
    Stop,
    StopOrder,
    TransportConfig,
    Vehicle,
)
from fyt.trips.models import Section, Trip, TripTemplate
from fyt.trips.views import _SectionMixin
from fyt.utils.matrix import OrderedMatrix
from fyt.utils.views import PopulateMixin


NOT_SCHEDULED = 'NOT_SCHEDULED'
EXCEEDS_CAPACITY = 'EXCEEDS_CAPACITY'


class UpdateTransportConfig(DatabaseUpdateView):
    model = TransportConfig
    delete_button = False

    def get_headline(self):
        return 'Edit Transport Settings'

    def get_object(self):
        return TransportConfig.objects.get(trips_year=self.trips_year)

    def get_success_url(self):
        return self.request.path


def get_internal_route_matrix(trips_year):
    """
    A matrix of all the scheduled internal buses, categorized by date and by
    route.
    """
    routes = Route.objects.internal(trips_year).select_related('vehicle')
    dates = Section.dates.trip_dates(trips_year)
    matrix = OrderedMatrix(routes, dates)
    scheduled = (
        InternalBus.objects.internal(trips_year)
        .select_related('route__vehicle')
        .prefetch_related('stoporder_set')
    )

    preload_transported_trips(scheduled, trips_year)

    for bus in scheduled:
        matrix[bus.route][bus.date] = bus

    return matrix


def preload_transported_trips(buses, trips_year):
    trips = Trip.objects.with_counts(trips_year=trips_year).select_related(
        'dropoff_route',
        'pickup_route',
        'return_route',
        'template__pickup_stop__route',
        'template__dropoff_stop__route',
        'template__return_route',
    )

    dropoffs = defaultdict(lambda: defaultdict(list))
    pickups = defaultdict(lambda: defaultdict(list))
    returns = defaultdict(lambda: defaultdict(list))

    for trip in trips:
        dropoffs[trip.get_dropoff_route()][trip.dropoff_date].append(trip)
        pickups[trip.get_pickup_route()][trip.pickup_date].append(trip)
        returns[trip.get_return_route()][trip.return_date].append(trip)

    hanover = Hanover(trips_year)
    lodge = Lodge(trips_year)

    for bus in buses:
        bus.trip_cache = InternalBus.TripCache(
            trips,
            dropoffs[bus.route][bus.date],
            pickups[bus.route][bus.date],
            returns[bus.route][bus.date],
            hanover,
            lodge,
        )

    return buses


def trip_transport_matrix(trips_year):
    """
    Return the matrices of TripTemplates and dates, with each entry
    containing the trip that is (dropped off, picked up, return to Hanover)
    on the given date.
    """

    # TODO: only show visible triptypes
    templates = TripTemplate.objects.filter(trips_year=trips_year)
    dates = Section.dates.trip_dates(trips_year)

    dropoff_matrix = OrderedMatrix(templates, dates)
    pickup_matrix = OrderedMatrix(templates, dates)
    return_matrix = OrderedMatrix(templates, dates)

    trips = Trip.objects.with_counts(trips_year=trips_year).select_related(
        'dropoff_route',
        'pickup_route',
        'return_route',
        'template__pickup_stop__route',
        'template__dropoff_stop__route',
        'template__return_route',
    )
    for trip in trips:
        dropoff_matrix[trip.template][trip.dropoff_date] = trip
        pickup_matrix[trip.template][trip.pickup_date] = trip
        return_matrix[trip.template][trip.return_date] = trip

    return dropoff_matrix, pickup_matrix, return_matrix


def as_set(trips):
    if trips is None:
        return set()
    return set(trips)


class Riders:
    """
    Utility class to represent the number of riders on a route.

    Riders objects can be added to each other. An empty Riders object
    evaluates to False for convenience.

    TODO: "Riders" doesn't really mean much, semantically.
    """

    def __init__(self, dropping_off=None, picking_up=None, returning=None):
        self.dropping_off = as_set(dropping_off)
        self.picking_up = as_set(picking_up)
        self.returning = as_set(returning)

    def __add__(self, y):
        return Riders(
            self.dropping_off.union(y.dropping_off),
            self.picking_up.union(y.picking_up),
            self.returning.union(y.returning),
        )

    def __bool__(self):
        return bool(self.dropping_off or self.picking_up or self.returning)

    def __eq__(self, y):
        return (
            self.dropping_off == y.dropping_off
            and self.picking_up == y.picking_up
            and self.returning == y.returning
        )

    def __ne__(self, y):
        return not self.__eq__(y)

    def __str__(self):
        return "Dropping off {}, picking up {}, returning {} to campus".format(
            self.dropping_off, self.picking_up, self.returning
        )

    __repr__ = __str__


def get_internal_rider_matrix(trips_year):
    """
    Compute which trips are riding on each route every day.
    """
    routes = Route.objects.internal(trips_year).select_related('vehicle')
    dates = Section.dates.trip_dates(trips_year)
    trips = Trip.objects.with_counts(trips_year).select_related(
        'template',
        'section',
        'pickup_route',
        'dropoff_route',
        'return_route',
        'template__dropoff_stop__route',
        'template__pickup_stop__route',
        'template__return_route',
    )
    matrix = OrderedMatrix(routes, dates, lambda: Riders())

    for trip in trips:
        # dropoff
        if trip.get_dropoff_route():
            matrix[trip.get_dropoff_route()][trip.dropoff_date] += Riders(
                dropping_off=[trip]
            )
        # pickup
        if trip.get_pickup_route():
            matrix[trip.get_pickup_route()][trip.pickup_date] += Riders(
                picking_up=[trip]
            )
        # return
        matrix[trip.get_return_route()][trip.return_date] += Riders(returning=[trip])

    return matrix


def get_internal_issues_matrix(transport_matrix, riders_matrix):
    assert len(transport_matrix.keys()) == len(riders_matrix.keys())

    matrix = riders_matrix.map(lambda x: None)  # new matrix w/ null entries

    for route, dates in matrix.items():
        for date in dates:
            transport = transport_matrix[route][date]
            riders = riders_matrix[route][date]
            if riders and not transport:
                matrix[route][date] = NOT_SCHEDULED
            elif transport and transport.over_capacity():
                matrix[route][date] = EXCEEDS_CAPACITY

    return matrix


def total_size(trips):
    return sum(trip.size for trip in trips)


class InternalBusMatrix(DatabaseReadPermissionRequired, TripsYearMixin, TemplateView):
    template_name = 'transport/internal_matrix.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['matrix'] = matrix = get_internal_route_matrix(self.trips_year)
        context['riders'] = riders = get_internal_rider_matrix(self.trips_year)
        context['issues'] = get_internal_issues_matrix(matrix, riders)
        context['NOT_SCHEDULED'] = NOT_SCHEDULED
        context['EXCEEDS_CAPACITY'] = EXCEEDS_CAPACITY

        # Transport numbers
        # TODO: move to separate view
        context['dropoff_matrix'] = riders.map(
            lambda x: total_size(x.dropping_off)
        ).truncate()
        context['pickup_matrix'] = riders.map(
            lambda x: total_size(x.picking_up)
        ).truncate()
        context['return_matrix'] = riders.map(
            lambda x: total_size(x.returning)
        ).truncate()

        return context


class InternalBusCreateView(PopulateMixin, DatabaseCreateView):
    model = InternalBus
    fields = ['route', 'date']

    def get_success_url(self):
        return reverse('core:internalbus:index', kwargs=self.kwargs)


class InternalBusUpdateView(DatabaseUpdateView):
    model = InternalBus
    fields = ['use_custom_times', 'notes']
    delete_button = False


class InternalBusDeleteView(DatabaseDeleteView):
    model = InternalBus
    success_url_pattern = 'core:internalbus:index'


class ExternalBusCreate(PopulateMixin, DatabaseCreateView):
    model = ExternalBus
    fields = ['route', 'section']

    def get_success_url(self):
        return reverse(
            'core:externalbus:matrix', kwargs={'trips_year': self.trips_year}
        )


class ExternalBusDelete(DatabaseDeleteView):
    model = ExternalBus
    success_url_pattern = 'core:externalbus:matrix'


class ExternalBusMatrix(DatabaseTemplateView):
    template_name = 'transport/external_matrix.html'

    def extra_context(self):
        return {
            'matrix': ExternalBus.objects.schedule_matrix(self.trips_year),
            'to_hanover': ExternalBus.passengers.matrix_to_hanover(self.trips_year),
            'from_hanover': ExternalBus.passengers.matrix_from_hanover(self.trips_year),
            'invalid_riders': ExternalBus.passengers.invalid_riders(self.trips_year),
        }


class StopListView(DatabaseListView):
    model = Stop
    context_object_name = 'stops'
    template_name = 'transport/stop_index.html'

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related('route')
            .order_by('route__category', 'name')
        )


class StopCreateView(DatabaseCreateView):
    model = Stop


class StopDetailView(DatabaseDetailView):
    model = Stop
    fields = [
        'name',
        'address',
        'lat_lng',
        'route',
        'directions',
        'picked_up_trips',
        'dropped_off_trips',
        'cost_round_trip',
        'cost_one_way',
        'pickup_time',
        'dropoff_time',
        'distance',
    ]


class StopUpdateView(DatabaseUpdateView):
    model = Stop


class StopDeleteView(DatabaseDeleteView):
    model = Stop
    success_url_pattern = 'core:stop:index'


class RouteListView(DatabaseListView):
    model = Route
    context_object_name = 'routes'
    template_name = 'transport/route_index.html'


class RouteCreateView(DatabaseCreateView):
    model = Route


class RouteDetailView(DatabaseDetailView):
    model = Route
    fields = ['name', 'vehicle', 'category', 'stops']


class RouteUpdateView(DatabaseUpdateView):
    model = Route


class RouteDeleteView(DatabaseDeleteView):
    model = Route
    success_url_pattern = 'core:route:index'


class VehicleListView(DatabaseListView):
    model = Vehicle
    context_object_name = 'vehicles'
    template_name = 'transport/vehicle_index.html'


class VehicleCreateView(DatabaseCreateView):
    model = Vehicle


class VehicleDetailView(DatabaseDetailView):
    model = Vehicle
    fields = ['name', 'capacity', 'chartered']


class VehicleUpdateView(DatabaseUpdateView):
    model = Vehicle


class VehicleDeleteView(DatabaseDeleteView):
    model = Vehicle
    success_url_pattern = 'core:vehicle:index'


class _DateMixin:
    """
    Mixin to get a date object from url kwargs.
    """

    @cached_property
    def date(self):
        """
        Convert from ISO date format
        """
        return datetime.strptime(self.kwargs['date'], "%Y-%m-%d").date()

    def get_context_data(self, **kwargs):
        kwargs['date'] = self.date
        return super().get_context_data(**kwargs)


class _RouteMixin:
    """
    Mixin to get a route object from url kwargs.
    """

    @cached_property
    def route(self):
        return Route.objects.get(pk=self.kwargs['route_pk'])

    def get_context_data(self, **kwargs):
        kwargs['route'] = self.route
        return super().get_context_data(**kwargs)


class TransportChecklist(_DateMixin, _RouteMixin, DatabaseTemplateView):
    """
    Shows all trips which are supposed to be dropped off,
    picked up, or returned to campus on the date and route
    in the kwargs.
    """

    template_name = 'transport/transport_checklist.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        args = (self.route, self.date, self.trips_year)
        context['dropoffs'] = Trip.objects.dropoffs(*args)
        context['pickups'] = Trip.objects.pickups(*args)
        context['returns'] = Trip.objects.returns(*args)

        context['scheduled'] = bus = InternalBus.objects.filter(
            trips_year=self.trips_year, date=self.date, route=self.route
        ).first()

        if bus:
            context['stops'] = bus.all_stops
            context['over_capacity'] = bus.over_capacity()

            # TODO: remove this?
            # Sanity check that bus routes still look good
            try:
                bus.validate_stop_ordering()
            except ValidationError:
                sentry.capture_exception()

        return context


class ExternalBusChecklist(_RouteMixin, _SectionMixin, DatabaseTemplateView):

    template_name = 'transport/externalbus_checklist.html'

    def extra_context(self):
        return {
            'section': self.section,
            'bus': ExternalBus.objects.filter(
                trips_year=self.trips_year, route=self.route, section=self.section
            ).first(),
            'passengers_to_hanover': IncomingStudent.objects.passengers_to_hanover(
                self.trips_year, self.route, self.section
            ),
            'passengers_from_hanover': IncomingStudent.objects.passengers_from_hanover(
                self.trips_year, self.route, self.section
            ),
        }


class OrderStops(
    DatabaseEditPermissionRequired, TripsYearMixin, FormValidMessageMixin, FormView
):
    template_name = 'transport/internal_order.html'
    form_valid_message = 'Route order has been updated'

    def get_queryset(self):
        return self.bus.get_stop_ordering()

    @cached_property
    def bus(self):
        return get_object_or_404(
            InternalBus, pk=self.kwargs['bus_pk'], trips_year=self.trips_year
        )

    def get_form(self, **kwargs):
        return StopOrderFormset(queryset=self.get_queryset(), **kwargs)

    def form_valid(self, formset):
        formset.save()
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return self.request.path

    def get_context_data(self, **kwargs):
        kwargs.update({'bus': self.bus, 'checklist_url': self.bus.detail_url()})
        return super().get_context_data(**kwargs)


class TripWrapper:
    def __init__(self, trip, route_getter):
        self.trip = trip
        self.route = getattr(trip, route_getter)()

    @property
    def color(self):
        if self.route:
            return self.route.display_color

    def detail_url(self):
        return self.trip.detail_url()

    def __str__(self):
        return str(self.trip)


def wrap_trip(trip, route_getter):
    """
    Wrap a Trip, adding `route` and `color` properties.
    """
    if trip:
        return TripWrapper(trip, route_getter)


class InternalTransportByDate(DatabaseTemplateView):
    template_name = 'transport/internal_by_date.html'

    def extra_context(self):
        d, p, r = trip_transport_matrix(self.trips_year)
        return {
            'dropoff_matrix': d.map(lambda t: wrap_trip(t, 'get_dropoff_route')),
            'pickup_matrix': p.map(lambda t: wrap_trip(t, 'get_pickup_route')),
            'return_matrix': r.map(lambda t: wrap_trip(t, 'get_return_route')),
        }


class InternalBusPacket(DatabaseListView):
    """
    Directions and notes for all internal buses.
    """

    model = InternalBus
    template_name = 'transport/internal_packet.html'
    context_object_name = 'bus_list'

    def modify_queryset(self, qs):
        """
        Used by subclasses to modify qs before preloading trips.
        """
        return qs

    def get_queryset(self):
        qs = super().get_queryset()
        qs = self.modify_queryset(qs)
        return preload_transported_trips(qs, self.trips_year)


class InternalBusPacketForDate(_DateMixin, InternalBusPacket):
    """
    All internal bus directions for a certain date.
    """

    def modify_queryset(self, qs):
        return qs.filter(date=self.date)


class InternalBusPacketForBusCompany(InternalBusPacket):
    """
    All internal bus directions to send to the bus company. These are only
    the large chartered buses.
    """

    template_name = 'transport/internal_packet_for_bus_company.html'

    def modify_queryset(self, qs):
        return qs.filter(route__vehicle__chartered=True)


class ExternalBusPacket(DatabaseListView):
    """
    """

    model = ExternalBus
    template_name = 'transport/external_packet.html'

    TO_HANOVER = 'to Hanover'
    FROM_HANOVER = 'from Hanover'

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.select_related('section', 'route')

    def get_bus_list(self):
        bus_list = []
        for bus in self.get_queryset():
            bus_list += [self.to_hanover_tuple(bus), self.from_hanover_tuple(bus)]
        return bus_list

    def extra_context(self):
        # sort by date, then bus name, then direction
        order = {self.TO_HANOVER: 0, self.FROM_HANOVER: 1}
        key = lambda x: (x[0], x[2].route.name, order[x[1]])
        return {'bus_list': sorted(self.get_bus_list(), key=key)}

    def to_hanover_tuple(self, bus):
        return (bus.date_to_hanover, self.TO_HANOVER, bus)

    def from_hanover_tuple(self, bus):
        return (bus.date_from_hanover, self.FROM_HANOVER, bus)


class ExternalBusPacketForDate(_DateMixin, ExternalBusPacket):
    """
    External bus directions for a certain date.
    """

    def get_bus_list(self):
        bus_list = []
        for bus in self.get_queryset():
            if self.date == bus.date_to_hanover:
                bus_list.append(self.to_hanover_tuple(bus))
            elif self.date == bus.date_from_hanover:
                bus_list.append(self.from_hanover_tuple(bus))
        return bus_list


class ExternalBusPacketForDateAndRoute(_RouteMixin, ExternalBusPacketForDate):
    """
    External bus directions for a date and route
    """

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(route=self.route)
