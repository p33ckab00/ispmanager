from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('settings_app', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='smssettings',
            name='billing_sms_repeat_interval_days',
            field=models.IntegerField(default=2),
        ),
    ]
