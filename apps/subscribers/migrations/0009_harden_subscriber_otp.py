from django.db import migrations, models
import django.db.models.deletion


def invalidate_plaintext_otps(apps, schema_editor):
    SubscriberOTP = apps.get_model('subscribers', 'SubscriberOTP')
    SubscriberOTP.objects.filter(is_used=False).update(is_used=True)


class Migration(migrations.Migration):

    dependencies = [
        ('subscribers', '0008_networknode_is_system_networknode_system_role_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='subscriberotp',
            name='code_hash',
            field=models.CharField(blank=True, default='', max_length=128),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='channel',
            field=models.CharField(choices=[('sms', 'SMS'), ('email', 'Email')], default='sms', max_length=20),
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='destination',
            field=models.CharField(blank=True, default='', max_length=255),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='sent_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='request_ip',
            field=models.GenericIPAddressField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='request_user_agent',
            field=models.TextField(blank=True, default=''),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='verify_attempts',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='last_attempt_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='subscriberotp',
            name='locked_until',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='subscriberotp',
            name='phone',
            field=models.CharField(max_length=30),
        ),
        migrations.AlterField(
            model_name='subscriberotp',
            name='subscriber',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='otps', to='subscribers.subscriber'),
        ),
        migrations.AddIndex(
            model_name='subscriberotp',
            index=models.Index(fields=['normalized_phone', 'created_at'], name='subscribers_normali_378ff8_idx'),
        ),
        migrations.AddIndex(
            model_name='subscriberotp',
            index=models.Index(fields=['request_ip', 'created_at'], name='subscribers_request_ad75d5_idx'),
        ),
        migrations.RunPython(invalidate_plaintext_otps, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='subscriberotp',
            name='code',
        ),
        migrations.RemoveField(
            model_name='subscriber',
            name='portal_otp',
        ),
        migrations.RemoveField(
            model_name='subscriber',
            name='portal_otp_expires',
        ),
    ]
