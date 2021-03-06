# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-03-30 16:49
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('timetable', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='timetable',
            name='scoring_available',
            field=models.BooleanField(default=False, help_text='Turn this on to begin the scoring process. Graders will have access to the scoring page when this is enabled.'),
        ),
    ]
