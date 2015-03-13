import csv
import io
import logging

from django import forms
from django.core.urlresolvers import reverse_lazy, reverse
from django.shortcuts import get_object_or_404
from django.http import HttpResponseRedirect
from django.contrib import messages
from vanilla import CreateView, UpdateView, DetailView, TemplateView, ListView, FormView
from braces.views import LoginRequiredMixin

from doc.trippees.models import TrippeeRegistration, Trippee, CollegeInfo
from doc.trippees.forms import RegistrationForm, IncomingStudentsForm
from doc.db.models import TripsYear
from doc.db.views import TripsYearMixin
from doc.timetable.models import Timetable
from doc.permissions.views import (DatabaseReadPermissionRequired,
                                   DatabaseEditPermissionRequired)

logger = logging.getLogger(__name__)

class IfRegistrationAvailable():
    """ Redirect if trippee registration is not currently available """

    def dispatch(self, request, *args, **kwargs):
        
        if not Timetable.objects.timetable().registration_available():
            return HttpResponseRedirect(reverse('trippees:registration_not_available'))
        return super(IfRegistrationAvailable, self).dispatch(request, *args, **kwargs)


class RegistrationNotAvailable(TemplateView):
    template_name = 'trippees/not_available.html'


class Register(LoginRequiredMixin, IfRegistrationAvailable, CreateView):
    """ 
    Register for trips 
    """
    model = TrippeeRegistration
    template_name = 'trippees/register.html'
    form_class = RegistrationForm
    success_url = reverse_lazy('trippees:view_registration')

    def form_valid(self, form, **kwargs):
        """ 
        Add the registering user to the registration 

        The registration will be automagically matched with a 
        corresponding Trippee model if it exists.
        """

        form.instance.trips_year = TripsYear.objects.current()
        form.instance.user = self.request.user
        return super(Register, self).form_valid(form, **kwargs)


class EditRegistration(LoginRequiredMixin, IfRegistrationAvailable, UpdateView):
    """
    Edit a trippee registration.
    """
    model = TrippeeRegistration
    template_name = 'trippees/register.html'
    form_class = RegistrationForm
    success_url = reverse_lazy('trippees:view_registration')

    def get_object(self):
        """ Get registration for user """        
        return get_object_or_404(
            self.model, user=self.request.user,
            trips_year=TripsYear.objects.current()
        )
           
 
class ViewRegistration(LoginRequiredMixin, IfRegistrationAvailable, DetailView):
    """
    View a complete registration 
    """
    model = TrippeeRegistration
    template_name = 'trippees/completed_registration.html'
    fields = ['name'] # TODO
    
    def get_object(self):
        """ Get registration for user """
        return get_object_or_404(
            self.model, user=self.request.user,
            trips_year=TripsYear.objects.current()
        )
           
         

class RegistrationIndexView(DatabaseReadPermissionRequired, 
                            TripsYearMixin, ListView):
    
    model = TrippeeRegistration
    template_name = 'trippees/registration_index.html'

    
class TrippeeIndexView(DatabaseReadPermissionRequired,
                       TripsYearMixin, ListView):
    
    model = Trippee
    template_name = 'trippees/trippee_index.html'
    

class UploadIncomingStudentData(DatabaseEditPermissionRequired,
                                TripsYearMixin, FormView):
    """
    Accept an upload of CSV file of incoming students. 

    Parses the CSV file and adds the data to the database as
    CollegeInfo objects.
    """

    form_class = IncomingStudentsForm
    template_name = 'trippees/upload_incoming_students.html'

    def form_valid(self, form):
        
        file = io.TextIOWrapper(form.files['csv_file'].file, 
                                encoding='utf-8', errors='replace')

        reader = csv.DictReader(file)
        for row in reader:

            kwargs = {
                'netid': row['Id'],
                'name': row['Formatted Fml Name'],
                'class_year': row['Class Year'],
                'gender': row['Gender'],
                'ethnic_code': row['Fine Ethnic Code'],
                'email': row['EMail'],
                'dartmouth_email': row['Blitz'],
            }
            
            kwargs['trips_year'] = self.kwargs['trips_year']
            
            try:
                netid = kwargs['netid']
                CollegeInfo.objects.get(netid=netid, trips_year=self.kwargs['trips_year'])
                msg = 'Incoming student with NetId %s already exists. Ignoring'
                logger.warn(msg % netid)
                messages.warning(self.request, msg % netid)
                continue

            except CollegeInfo.DoesNotExist:
                msg = 'Creating incoming student %s'
                logger.info(msg % kwargs['name'])
                messages.info(self.request, msg % kwargs['name'])
                CollegeInfo.objects.create(**kwargs)
                
        return super(UploadIncomingStudentData, self).form_valid(form)
                

    def get_success_url(self):
        return self.request.path
        
        


 

    
