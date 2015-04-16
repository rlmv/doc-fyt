

from django import forms
from django.core.urlresolvers import reverse
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from bootstrap3_datetime.widgets import DateTimePicker

from doc.applications.models import LeaderSupplement, GeneralApplication
from doc.trips.models import Section


class SectionForm(forms.ModelForm):
    """ Form for Section Create and Update views. """
    
    class Meta:
        model = Section
        widgets = {
            'leaders_arrive': DateTimePicker(options={'format': 'MM/DD/YYYY', 
                                                      'pickTime': False})
        }

    def __init__(self, *args, **kwargs):
        super(SectionForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper(self)
        self.helper.add_input(Submit('submit', 'Submit'))


class TripLeaderAssignmentForm(forms.ModelForm):
    
    class Meta:
        model = GeneralApplication
        fields = ['assigned_trip']
        widgets = {
            'assigned_trip': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        super(TripLeaderAssignmentForm, self).__init__(*args, **kwargs)
        self.helper = FormHelper(self)

        params = {'trips_year': kwargs['instance'].trips_year.year,
                  'leader_pk': kwargs['instance'].pk}
        self.helper.form_action = reverse('db:assign_leader_to_trip', kwargs=params)

        label = 'Assign to %s' % self.initial['assigned_trip']
        self.helper.add_input(Submit('submit', label, css_class='btn-xs'))

    def clean(self):
        """ Change status to leader if trip assignment is successful """
        if self.cleaned_data.get('assigned_trip'):
            self.instance.status = GeneralApplication.LEADER
        return super(TripLeaderAssignmentForm, self).clean()
