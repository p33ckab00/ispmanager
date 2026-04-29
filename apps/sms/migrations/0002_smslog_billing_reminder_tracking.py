import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
        ('sms', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='smslog',
            name='billing_due_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='smslog',
            name='billing_snapshot',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sms_logs',
                to='billing.billingsnapshot',
            ),
        ),
        migrations.AddField(
            model_name='smslog',
            name='reminder_run_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='smslog',
            name='reminder_stage',
            field=models.IntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name='smslog',
            index=models.Index(
                fields=['billing_snapshot', 'sms_type', 'reminder_run_date'],
                name='sms_smslog_billing_d8fa1d_idx',
            ),
        ),
    ]
