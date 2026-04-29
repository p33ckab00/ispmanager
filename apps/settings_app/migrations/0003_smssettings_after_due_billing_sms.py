from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0002_smssettings_billing_sms_repeat_interval_days'),
    ]

    operations = [
        migrations.AddField(
            model_name='smssettings',
            name='billing_sms_after_due_interval_days',
            field=models.IntegerField(default=2),
        ),
        migrations.AddField(
            model_name='smssettings',
            name='billing_sms_send_after_due',
            field=models.BooleanField(default=False),
        ),
    ]
