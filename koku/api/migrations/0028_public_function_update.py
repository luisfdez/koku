# Generated by Django 2.2.15 on 2020-09-02 16:26
import os
import sys

from django.db import migrations

from koku import migration_sql_helpers as msh


def apply_public_function_updates(apps, schema_editor):
    path = msh.find_db_functions_dir()
    for funcfile in (
        "partitioned_tables_manage_trigger_function.sql",
        "partitioned_tables_active_trigger_function.sql",
        "scan_date_partitions.sql",
    ):
        msh.apply_sql_file(schema_editor, os.path.join(path, funcfile), literal_placeholder=True)


class Migration(migrations.Migration):

    dependencies = [("api", "0027_customer_date_updated")]

    operations = [migrations.RunPython(code=apply_public_function_updates)]
