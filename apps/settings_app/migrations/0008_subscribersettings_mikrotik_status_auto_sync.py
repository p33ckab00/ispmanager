from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0007_subscribersettings_portal_otp_security'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscribersettings',
            name='mikrotik_status_auto_sync_enabled',
            field=models.BooleanField(
                default=False,
                help_text='Automatically refresh subscriber online/offline status from MikroTik PPP active sessions.',
            ),
        ),
        migrations.AddField(
            model_name='subscribersettings',
            name='mikrotik_status_sync_interval_minutes',
            field=models.IntegerField(
                default=5,
                help_text='How often subscriber MikroTik status auto-sync runs, in minutes.',
            ),
        ),
    ]
