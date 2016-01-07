
from crispy_forms.layout import Layout, Submit, Field, HTML, Row, Div
from crispy_forms.helper import FormHelper

from fyt.transport.models import StopOrder
from django import forms


class StopOrderForm(forms.ModelForm):

    class Meta:
        model = StopOrder
        fields = ['order']

    trip = forms.CharField()
    stop_type = forms.CharField()
    stop = forms.CharField()

    def __init__(self, *args, **kwargs):
        super(StopOrderForm, self).__init__(*args, **kwargs)
        self.fields['trip'].initial = self.instance.trip
        self.fields['stop_type'].initial = self.instance.stop_type
        self.fields['stop'].initial = self.instance.stop.name


StopOrderFormset = forms.models.modelformset_factory(
    StopOrder, form=StopOrderForm, extra=0
)


class StopOrderFormHelper(FormHelper):
    layout = Layout(
        Row(
            Field('stop', readonly=True),
            Field('stop_type', readonly=True),
            Field('trip', readonly=True),
            'order',
        )
    )
    form_class = 'form-inline'

    def __init__(self, *args, **kwargs):
        super(StopOrderFormHelper, self).__init__(*args, **kwargs)
        self.add_input(Submit('submit', 'Save'))