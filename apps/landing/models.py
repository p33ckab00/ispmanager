from django.db import models


class LandingPage(models.Model):
    PAGE_TYPE_CHOICES = [
        ('homepage', 'ISP Homepage'),
        ('captive', 'Captive Portal'),
    ]

    page_type = models.CharField(max_length=20, choices=PAGE_TYPE_CHOICES, unique=True)
    is_published = models.BooleanField(default=False)
    hero_title = models.CharField(max_length=255, blank=True)
    hero_subtitle = models.TextField(blank=True)
    about_text = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_address = models.TextField(blank=True)
    footer_text = models.TextField(blank=True)
    announcement = models.TextField(blank=True)
    primary_color = models.CharField(max_length=7, default='#2563eb')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.get_page_type_display()

    @classmethod
    def get_homepage(cls):
        obj, _ = cls.objects.get_or_create(page_type='homepage')
        return obj

    @classmethod
    def get_captive(cls):
        obj, _ = cls.objects.get_or_create(page_type='captive')
        return obj


class LandingPlan(models.Model):
    page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name='plans')
    name = models.CharField(max_length=100)
    speed = models.CharField(max_length=50, blank=True)
    price = models.CharField(max_length=50, blank=True)
    features = models.TextField(blank=True, help_text='One feature per line')
    is_featured = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.name

    def feature_list(self):
        return [f.strip() for f in self.features.split('\n') if f.strip()]
