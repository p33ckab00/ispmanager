from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0006_subscribersettings_disconnected_credit_policy'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscribersettings',
            name='portal_otp_expiry_minutes',
            field=models.IntegerField(default=10, help_text='How long subscriber portal OTP codes remain valid.'),
        ),
        migrations.AddField(
            model_name='subscribersettings',
            name='portal_otp_resend_cooldown_seconds',
            field=models.IntegerField(default=60, help_text='Minimum wait before another OTP request for the same phone number.'),
        ),
        migrations.AddField(
            model_name='subscribersettings',
            name='portal_otp_max_verify_attempts',
            field=models.IntegerField(default=5, help_text='Maximum wrong OTP attempts before temporary lockout.'),
        ),
        migrations.AddField(
            model_name='subscribersettings',
            name='portal_otp_lockout_minutes',
            field=models.IntegerField(default=15, help_text='How long OTP verification is locked after too many wrong attempts.'),
        ),
        migrations.AddField(
            model_name='subscribersettings',
            name='portal_otp_phone_hourly_limit',
            field=models.IntegerField(default=5, help_text='Maximum OTP requests per normalized phone number per hour.'),
        ),
        migrations.AddField(
            model_name='subscribersettings',
            name='portal_otp_ip_hourly_limit',
            field=models.IntegerField(default=30, help_text='Maximum OTP requests per source IP per hour.'),
        ),
    ]
