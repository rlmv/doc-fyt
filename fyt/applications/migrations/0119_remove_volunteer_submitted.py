# Generated by Django 2.1.5 on 2019-01-23 12:06

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0118_auto_20190123_0706'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='volunteer',
            name='submitted',
        ),
    ]
