

from django.conf.urls import patterns, include, url

urlpatterns = patterns('', 
    url(r'^login/$', 'django_cas.views.login', name='login'),
    url(r'^logout/$', 'django_cas.views.logout', name='logout'),
)
