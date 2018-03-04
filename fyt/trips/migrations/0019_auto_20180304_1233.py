# Generated by Django 2.0.2 on 2018-03-04 17:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0018_section_sophomore_leaders_ok'),
    ]

    operations = [
        migrations.AlterField(
            model_name='section',
            name='sophomore_leaders_ok',
            field=models.BooleanField(default=False, verbose_name='Sophomores taking classes this summer can lead trips during this section'),
        ),
    ]
