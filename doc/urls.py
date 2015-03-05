
from django.conf.urls import patterns, include, url
from django.contrib import admin

from doc.views import HomePage
from doc.permissions import initialize_groups_and_permissions

admin.autodiscover()
initialize_groups_and_permissions()
handler403 = 'doc.views.permission_denied'

urlpatterns = patterns('',
    url(r'^$', HomePage.as_view(), name='home'),
    url(r'^users/', include('doc.users.urls', namespace='users')),
    url(r'^dartdm/', include('doc.dartdm.urls', namespace='dartdm')),                   
    url(r'^permissions/', include('doc.permissions.urls', namespace='permissions')),
    url(r'^timetable/', include('doc.timetable.urls', namespace='timetable')),
    url(r'^db/', include('doc.db.urls', namespace='db')),
    url(r'^applications/', include('doc.applications.urls', namespace='applications')),
#    url(r'^leaders/', include('doc.leaders.urls', namespace='leaders')),
    url(r'^croos/', include('doc.croos.urls', namespace='croos')),                   
    url(r'^admin/', include(admin.site.urls)),
)

