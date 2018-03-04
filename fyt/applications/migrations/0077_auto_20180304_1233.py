# Generated by Django 2.0.2 on 2018-03-04 17:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('applications', '0076_auto_20180304_1140'),
    ]

    operations = [
        migrations.AlterField(
            model_name='leadersupplement',
            name='availability',
            field=models.TextField(blank=True, verbose_name='Looking at the Trips descriptions, please feel free to use this space to address any concerns or explain your availability. If applicable, please also elaborate on any particular trips or activities that you absolutely CANNOT participate in. All information in this application will remain confidential.'),
        ),
    ]
