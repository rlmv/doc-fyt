
from django.conf.urls import patterns, url

from trip.views import *

trip_urlpatterns = patterns('', 
    ScheduledTripListView.urlpattern(),
    ScheduledTripCreateView.urlpattern(),                            
    ScheduledTripUpdateView.urlpattern(),                            
    ScheduledTripDeleteView.urlpattern(),                        
)

template_urlpatterns = patterns('',
    TripTemplateListView.urlpattern(),
    TripTemplateCreateView.urlpattern(),                            
    TripTemplateUpdateView.urlpattern(),                            
    TripTemplateDeleteView.urlpattern(),                        
)                                

triptype_urlpatterns = TripTypeViews.get_urls()

campsite_urlpatterns = CampsiteViews.get_urls()

section_urlpatterns = SectionViews.get_urls()
