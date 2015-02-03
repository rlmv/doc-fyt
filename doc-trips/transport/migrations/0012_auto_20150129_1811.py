# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from django.db import models, migrations


class Migration(migrations.Migration):

    dependencies = [
        ('transport', '0011_auto_20150129_1810'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='route',
            options={'ordering': ['category', 'name']},
        ),
        migrations.AlterModelOptions(
            name='stop',
            options={'ordering': ['category', 'name']},
        ),
    ]