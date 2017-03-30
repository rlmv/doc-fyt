# -*- coding: utf-8 -*-
# Generated by Django 1.10 on 2017-03-05 21:06
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('transport', '0002_auto_20150909_2313'),
    ]

    operations = [
        migrations.AlterField(
            model_name='stop',
            name='distance',
            field=models.PositiveIntegerField(help_text='this rough distance from Hanover is used for bus routing'),
        ),
    ]