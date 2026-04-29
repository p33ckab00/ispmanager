from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='invoice',
            constraint=models.UniqueConstraint(
                fields=('subscriber', 'period_start'),
                name='uniq_invoice_subscriber_period_start',
            ),
        ),
        migrations.AddConstraint(
            model_name='billingsnapshot',
            constraint=models.UniqueConstraint(
                fields=('subscriber', 'period_start'),
                name='uniq_snapshot_subscriber_period_start',
            ),
        ),
    ]
