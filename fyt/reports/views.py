import csv

from braces.views import AllVerbsMixin
from vanilla import View
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse
from django.db.models import Avg, Q

from fyt.db.views import TripsYearMixin, DatabaseTemplateView
from fyt.applications.models import GeneralApplication as Application
from fyt.incoming.models import Registration, IncomingStudent
from fyt.incoming.models import Settings
from fyt.permissions.views import DatabaseReadPermissionRequired
from fyt.utils.choices import S, M, L, XL
from fyt.utils.cache import cache_as
from fyt.trips.models import Trip


class GenericReportView(DatabaseReadPermissionRequired,
                        TripsYearMixin, AllVerbsMixin, View):
    # TODO use a ListView here?

    file_prefix = None
    header = None

    def get_filename(self):
        return "{}-{}.csv".format(
            self.file_prefix, self.kwargs['trips_year']
        )

    def get_header(self):
        if self.header is not None:
            return self.header
        raise ImproperlyConfigured("add 'header' property")

    def get_queryset(self):
        raise ImproperlyConfigured('implement get_queryset()')

    def get_row(self, obj):
        raise ImproperlyConfigured('implement get_row()')

    def all(self, request, *args, **kwargs):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            'attachment; filename="{}"'.format(self.get_filename())
        )
        writer = csv.writer(response)
        writer.writerow(self.get_header())
        for obj in self.get_queryset():
            writer.writerow(self.get_row(obj))
        return response


class VolunteerCSV(GenericReportView):

    file_prefix = 'TL-and-Croo-applicants'
    header = ['name', 'class year', 'netid']

    def get_queryset(self):
        return Application.objects.leader_or_croo_applications(
            self.kwargs['trips_year']
        ).select_related('applicant')

    def get_row(self, application):
        user = application.applicant
        return [user.name, application.class_year, user.netid]


class TripLeaderApplicationsCSV(GenericReportView):

    file_prefix = 'TL-applicants'
    header = ['name', 'class year', 'netid', 'avg score']

    def get_queryset(self):
        return (Application.objects
                .leader_applications(self.kwargs['trips_year'])
                .annotate(avg_score=Avg('leader_supplement__grades__grade'))
                .select_related('leader_supplement')
                .prefetch_related('leader_supplement__grades'))

    def get_row(self, application):
        user = application.applicant
        if application.avg_score:
            avg_score = "%.1f" % application.avg_score
        else:
            avg_score = None
        row = [user.name, application.class_year,
               user.netid, avg_score]
        return row + [grade.grade for grade in
                      application.leader_supplement.grades.all()]


class CrooApplicationsCSV(GenericReportView):

    file_prefix = 'Croo-applicants'
    header = ['name', 'class year', 'netid', 'avg score']

    def get_queryset(self):
        return (Application.objects
                .croo_applications(self.kwargs['trips_year'])
                .annotate(avg_score=Avg('croo_supplement__grades__grade'))
                .select_related('croo_supplement')
                .prefetch_related('croo_supplement__grades'))

    def get_row(self, application):
        user = application.applicant
        if application.avg_score:
            avg_score = "%.1f" % application.avg_score
        else:
            avg_score = None
        row = [user.name, application.class_year,
               user.netid, avg_score]
        return row + [grade.grade for grade in
                      application.croo_supplement.grades.all()]


class TripLeadersCSV(GenericReportView):
    file_prefix = 'Leaders'

    def get_queryset(self):
        return Application.objects.leaders(
            self.kwargs['trips_year']
        ).select_related('applicant')

    header = ['name', 'netid']
    def get_row(self, leader):
        return [leader.name, leader.applicant.netid.upper()]


class CrooMembersCSV(TripLeadersCSV):
    file_prefix = 'Croo-Members'

    def get_queryset(self):
        return Application.objects.croo_members(
            self.kwargs['trips_year']
        ).select_related('applicant')


class FinancialAidCSV(GenericReportView):

    file_prefix = 'Financial-aid'
    header = ['name', 'preferred name', 'netid', 'blitz', 'email']

    def get_queryset(self):
        return Registration.objects.want_financial_aid(
            self.get_trips_year()
        ).select_related('user')

    def get_row(self, reg):
        user = reg.user
        return [user.name, reg.name, user.netid, user.email, reg.email]


class ExternalBusCSV(GenericReportView):

    file_prefix = 'External-Bus-Requests'
    header = ['name', 'preferred_name', 'netid', 'requested stop', 'on route']

    def get_queryset(self):
        return Registration.objects.want_bus(
            self.get_trips_year()
        ).select_related(
            'user', 'bus_stop', 'bus_stop__route'
        )

    def get_row(self, reg):
        user = reg.user
        return [user.name, reg.name, user.netid, reg.bus_stop, reg.bus_stop.route]


class TrippeesCSV(GenericReportView):
    """
    All trippees going on trips
    """
    file_prefix = 'Trippees'

    def get_queryset(self):
        return IncomingStudent.objects.with_trip(self.kwargs['trips_year'])

    header = ['name', 'netid']
    def get_row(self, trippee):
        return [trippee.name, trippee.netid.upper()]


class Charges(GenericReportView):
    """
    CSV file of charges to be applied to each trippee.

    All values are adjusted by financial aid, if applicable
    """
    file_prefix = 'Charges'

    def get_queryset(self):
        return IncomingStudent.objects.filter(
            (Q(trip_assignment__isnull=False) |
             Q(cancelled=True) |
             Q(registration__doc_membership=True) |
             Q(registration__green_fund_donation__gt=0)),
            trips_year=self.get_trips_year(),
        ).prefetch_related(
            'registration'
        )

    header = [
        'name',
        'netid',
        'total charge',
        'aid award (percentage)',
        'trip',
        'bus',
        'doc membership',
        'green fund',
        'cancellation'
    ]
    def get_row(self, incoming):
        reg = incoming.get_registration()
        return [
            incoming.name,
            incoming.netid,
            incoming.compute_cost(self.costs),
            incoming.financial_aid or '',
            incoming.trip_cost(self.costs) or '',
            incoming.bus_cost() or '',
            incoming.doc_membership_cost(self.costs) or '',
            incoming.green_fund_donation() or '',
            incoming.cancellation_cost(self.costs) or '',
        ]

    @property
    @cache_as('_costs')
    def costs(self):
        return Settings.objects.get(
            trips_year=self.kwargs['trips_year']
        )

class DocMembers(GenericReportView):
    """
    CSV file of registrations requesting DOC memberships.
    """
    file_prefix = 'DOC-Members'

    def get_queryset(self):
        return Registration.objects.filter(
            trips_year=self.kwargs['trips_year'], doc_membership=True
        ).select_related('user')

    header = ['name', 'netid', 'email']
    def get_row(self, reg):
        return [reg.user.name, reg.user.netid, reg.user.email]


def _tshirt_count(qs):
    """
    Return a dict with S, M, L, XL keys, each
    with the number of shirts needed in that size.
    """
    counts = {S: 0, M: 0, L: 0, XL: 0}
    for size in [S, M, L, XL]:
        counts[size] += qs.filter(tshirt_size=size).count()
    return counts

def leader_tshirts(trips_year):
    return _tshirt_count(Application.objects.filter(
        trips_year=trips_year, status=Application.LEADER
    ))

def croo_tshirts(trips_year):
    return _tshirt_count(Application.objects.filter(
        trips_year=trips_year, status=Application.CROO
    ))

def trippee_tshirts(trips_year):
    return _tshirt_count(Registration.objects.filter(
        trips_year=trips_year
    ))


class TShirts(DatabaseTemplateView):
    """
    Counts of all tshirt sizes requested by leaders, croos, and trippees.
    """
    template_name = "reports/tshirts.html"

    def get_context_data(self, **kwargs):
        kwargs.update({
            'leaders': leader_tshirts(self.kwargs['trips_year']),
            'croos': croo_tshirts(self.kwargs['trips_year']),
            'trippees': trippee_tshirts(self.kwargs['trips_year'])
        })
        return super(TShirts, self).get_context_data(**kwargs)


class Housing(GenericReportView):

    file_prefix = 'Housing'

    def get_queryset(self):
        return IncomingStudent.objects.filter(
            trips_year=self.kwargs['trips_year']
        ).prefetch_related(
            'registration'
        )

    header = ['name', 'netid', 'trip', 'section', 'start date', 'end date',
              'native', 'fysep', 'international']
    def get_row(self, incoming):
        is_assigned = incoming.trip_assignment is not None
        reg = incoming.get_registration()
        trip = incoming.trip_assignment
        fmt = "%m/%d"
        return [
            incoming.name,
            incoming.netid,
            trip if is_assigned else "",
            trip.section.name if is_assigned else "",
            trip.section.trippees_arrive.strftime(fmt) if is_assigned else "",
            trip.section.return_to_campus.strftime(fmt) if is_assigned else "",
            'yes' if reg and reg.is_native else '',
            'yes' if reg and reg.is_fysep else '',
            'yes' if reg and reg.is_international else '',
        ]


class DietaryRestrictions(GenericReportView):

    file_prefix = 'Dietary-Restrictions'

    def get_queryset(self):
        return Registration.objects.filter(
            trips_year=self.kwargs['trips_year']
        ).select_related(
            'user'
        ).prefetch_related(
            'trippee__trip_assignment',
            'trippee__trip_assignment__section'
        )

    header = [
        'name', 'netid', 'section', 'trip',
        'food allergies',
        'dietary restrictions',
        'epipen'
    ]
    def get_row(self, reg):
        trip = reg.get_trip_assignment()
        return [
            reg.name,
            reg.user.netid,
            trip.section.name if trip else '',
            trip,
            reg.food_allergies,
            reg.dietary_restrictions,
            reg.get_epipen_display()
        ]


class MedicalInfo(GenericReportView):

    file_prefix = 'Medical-Info'

    def get_queryset(self):
        return Registration.objects.filter(
            trips_year=self.kwargs['trips_year']
        )

    header = [
        'name', 'netid', 'section', 'trip',
        'medical conditions',
        'food allergies',
        'dietary restrictions',
        'epipen',
        'needs',
    ]
    def get_row(self, reg):
        trip = reg.get_trip_assignment()
        return [
            reg.name,
            reg.user.netid,
            trip.section.name if trip else '',
            trip,
            reg.medical_conditions,
            reg.food_allergies,
            reg.dietary_restrictions,
            reg.get_epipen_display(),
            reg.needs,
        ]

class VolunteerDietaryRestrictions(GenericReportView):

    file_prefix = 'Volunteer-Dietary-Restrictions'

    def get_queryset(self):
        return Application.objects.filter(
            trips_year=self.kwargs['trips_year']
        ).filter(
            Q(status=Application.LEADER) | Q(status=Application.CROO)
        ).order_by(
            'status'
        ).select_related(
            'applicant'
        )

    header = [
        'name',
        'netid',
        'role',
        'trip',
        'food allergies',
        'dietary restrictions',
        'epipen'
    ]
    def get_row(self, app):
        return [
            app.applicant.name,
            app.applicant.netid,
            app.status,
            app.assigned_trip or '',
            app.food_allergies,
            app.dietary_restrictions,
            app.get_epipen_display()
        ]


class Feelings(GenericReportView):

    file_prefix = 'Feelings'

    def get_queryset(self):
        return Registration.objects.filter(
            trips_year=self.kwargs['trips_year']
        )

    header = ['']
    def get_row(self, reg):
        return [reg.final_request]


class Foodboxes(GenericReportView):

    file_prefix = 'Foodboxes'

    def get_queryset(self):
        return Trip.objects.filter(
            trips_year=self.kwargs['trips_year']
        )

    header = [
        'trip',
        'section',
        'size',
        'full box',
        'half box',
        'supplement',
        'bagels'
    ]
    def get_row(self, trip):
        return [
            trip,
            trip.section.name,
            trip.size(),
            '1',
            '1' if trip.half_foodbox else '',
            '1' if trip.supp_foodbox else '',
            trip.bagels
        ]


class Statistics(DatabaseTemplateView):
    """
    Basic statistics regarding trippees
    """
    template_name = 'reports/statistics.html'

    def extra_context(self):
        IS = IncomingStudent

        counts = lambda qs: {
            'firstyear_count': qs.filter(incoming_status=IS.FIRSTYEAR).count(),
            'transfer_count': qs.filter(incoming_status=IS.TRANSFER).count(),
            'exchange_count': qs.filter(incoming_status=IS.EXCHANGE).count(),
            'unlabeled': qs.filter(incoming_status='').count(),
            'total': qs.count()
        }

        return {
            'with_trip': counts(IS.objects.with_trip(self.kwargs['trips_year'])),
            'cancelled': counts(IS.objects.cancelled(self.kwargs['trips_year']))
        }