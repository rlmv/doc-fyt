# -*- coding: utf-8 -*-
# Generated by Django 1.10 on 2017-02-20 21:05
from __future__ import unicode_literals

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0044_auto_20170220_1555'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='leadersupplement',
            name='cannot_participate_in',
        ),
        migrations.RemoveField(
            model_name='leadersupplement',
            name='trip_preference_comments',
        ),
    ]