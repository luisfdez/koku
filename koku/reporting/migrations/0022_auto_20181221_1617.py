# Generated by Django 2.1.2 on 2018-12-21 16:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reporting', '0021_auto_20181212_1816'),
    ]

    operations = [
        migrations.AddField(
            model_name='ocpusagelineitemdaily',
            name='cluster_alias',
            field=models.CharField(max_length=256, null=True),
        ),
        migrations.AddField(
            model_name='ocpusagelineitemdailysummary',
            name='cluster_alias',
            field=models.CharField(max_length=256, null=True),
        ),
    ]
