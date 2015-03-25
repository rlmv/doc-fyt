
from django.db import models
from django.core.exceptions import ValidationError

from doc.db.models import DatabaseModel
from doc.transport.managers import StopManager, RouteManager


class Stop(DatabaseModel):
    """
    A stop on a transportation route.

    Represents a pickup or dropoff point for a trip OR a
    bus stop where local sections are picked up.
    """

    class Meta:
        ordering = ['route__category', 'route', 'name']

    objects = StopManager()

    name = models.CharField(max_length=255)
    # TODO: validate that lat and long are interdependet / location is there?
    address = models.CharField(max_length=255, help_text='Plain text address, eg. Hanover, NH 03755. This must take you to the location in Google maps.')
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)

    # verbal directions, descriptions. migrated from legacy.
    directions = models.TextField(blank=True)

    route = models.ForeignKey('Route', null=True, blank=True,
                              on_delete=models.PROTECT, related_name='stops')

    # TODO: validate that this only is used if route.category==EXTERNAL?
    cost = models.DecimalField(max_digits=5, decimal_places=2,
                               blank=True, null=True)
    # mostly used for external routes
    pickup_time = models.TimeField(blank=True, null=True)
    dropoff_time = models.TimeField(blank=True, null=True)

    # legacy data from old db - hide on site?
    distance = models.IntegerField(null=True)

    @property
    def category(self):
        return self.route.category

    def __str__(self):
        return self.name


class Route(DatabaseModel):
    """
    A transportation route.

    A route is either INTERNAL (transporting students to/from Hanover,
    trip dropoffs/pickups, and the lodge) or EXTERNAl (moving local
    students to and from campus before and after their trips.)
    """

    name = models.CharField(max_length=255)
    INTERNAL = 'INTERNAL'
    EXTERNAL = 'EXTERNAL'
    TRANSPORT_CATEGORIES = (
        (INTERNAL, 'Internal'),
        (EXTERNAL, 'External'),
    )
    category = models.CharField(max_length=20, choices=TRANSPORT_CATEGORIES)
    vehicle = models.ForeignKey('Vehicle', on_delete=models.PROTECT)

    objects = RouteManager()

    class Meta:
        ordering = ['category', 'vehicle', 'name']

    def __str__(self):
        return self.name


class Vehicle(DatabaseModel):
    """ A type of vehicle """

    # eg. Internal Bus, Microbus,
    name = models.CharField(max_length=255)
    capacity = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class ScheduledTransport(DatabaseModel):
    """ 
    Represents a scheduled transport.

    The model is either scheduled for a date, if INTERNAL
    or a section

    TODO: should this be separated into Internal and 
    and External models? Or just schedule for date?
    """
    route = models.ForeignKey('Route', on_delete=models.PROTECT)

    # has a date if INTERNAL, section if EXTERNAL
    date = models.DateField(null=True, blank=True)
    section = models.ForeignKey('trips.Section', null=True, blank=True)

    def clean(self):
        if self.date and self.section:
            msg = "Transport can only be scheduled for a date OR section"
            raise ValidationError(msg)
        if self.date is None and self.section is None:
            msg = "Transport must be scheduled for a data OR a section"
            raise ValidationError(msg)
        if self.route.category == Route.INTERNAL and self.section:
            msg = "Internal transport must be scheduled for a date"
            raise ValidationError(msg)
        elif self.route.category == Route.EXTERNAL and self.date:
            msg = "External transport must be scheduled for a section"
            raise ValidationError(msg)
