from django.conf.urls import url, include

from fyt.applications.urls import (
    application_urlpatterns, grade_urlpatterns
)
from fyt.croos.urls import croo_urlpatterns
from fyt.db.views import (
    DatabaseLandingPage, RedirectToCurrentDatabase, MigrateForward)
from fyt.incoming.urls import (
    trippee_urlpatterns, registration_urlpatterns, settings_urlpatterns
)
from fyt.transport.urls import (
    scheduledtransport_urlpatterns, transportstop_urlpatterns,
    vehicle_urlpatterns, route_urlpatterns,
    externalbus_urlpatterns
)
from fyt.trips.urls import (
    trip_urlpatterns, template_urlpatterns, triptype_urlpatterns,
    campsite_urlpatterns, section_urlpatterns, leader_urlpatterns,
    foodbox_urlpatterns, packet_urlpatterns, checklist_urlpatterns
)

"""
All database urlpatterns take a trips_year param.
"""

database_urlpatterns = [
    url(r'^$', DatabaseLandingPage.as_view(), name='landing_page'),
    url(r'^trips/', include(trip_urlpatterns)),
    url(r'^leaders/', include(leader_urlpatterns)),
    url(r'^templates/', include(template_urlpatterns)),
    url(r'^types/', include(triptype_urlpatterns)),
    url(r'^campsites/', include(campsite_urlpatterns)),
    url(r'^sections/', include(section_urlpatterns)),
    url(r'^croos/', include(croo_urlpatterns)),
    url(r'^stops/', include(transportstop_urlpatterns)),
    url(r'^routes/', include(route_urlpatterns)),
    url(r'^vehicles/', include(vehicle_urlpatterns)),
    url(r'^applications/', include(application_urlpatterns)),
    url(r'^grades/', include(grade_urlpatterns)),
    url(r'^trippees/', include(trippee_urlpatterns)),
    url(r'^registrations/', include(registration_urlpatterns)),
    url(r'^', include(settings_urlpatterns)),
    url(r'^transport/', include(scheduledtransport_urlpatterns)),
    url(r'^transport/external/', include(externalbus_urlpatterns)),
    url(r'^emails/', include('fyt.emails.urls', namespace='emails')),
    url(r'^reports/', include('fyt.reports.urls', namespace='reports')),
    url(r'^raids/', include('fyt.raids.urls', namespace='raids')),
    url(r'^foodbox/', include(foodbox_urlpatterns, namespace='foodbox')),
    url(r'^packets/', include(packet_urlpatterns, namespace='packets')),
    url(r'^incidents/', include('fyt.safety.urls', namespace='safety')),
    url(r'^checklists/', include(checklist_urlpatterns, namespace='checklists')),
]

urlpatterns = [
    url(r'^$', RedirectToCurrentDatabase.as_view(), name='db_redirect'),
    url(r'^migrate/$', MigrateForward.as_view(), name='migrate'),
    # capture the 'trips_year' parameter
    url(r'^(?P<trips_year>[0-9]+)/', include(database_urlpatterns)),
]