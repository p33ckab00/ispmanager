from django.db import models


class LandingPage(models.Model):
    PAGE_TYPE_CHOICES = [
        ('homepage', 'ISP Homepage'),
        ('captive', 'Captive Portal'),
    ]

    page_type = models.CharField(max_length=20, choices=PAGE_TYPE_CHOICES, unique=True)
    is_published = models.BooleanField(default=False)
    hero_badge = models.CharField(max_length=120, blank=True)
    hero_title = models.CharField(max_length=255, blank=True)
    hero_subtitle = models.TextField(blank=True)
    hero_primary_cta_label = models.CharField(max_length=80, blank=True)
    hero_primary_cta_url = models.CharField(max_length=255, blank=True)
    hero_secondary_cta_label = models.CharField(max_length=80, blank=True)
    hero_secondary_cta_url = models.CharField(max_length=255, blank=True)
    nav_plans_label = models.CharField(max_length=80, blank=True)
    nav_why_us_label = models.CharField(max_length=80, blank=True)
    nav_coverage_label = models.CharField(max_length=80, blank=True)
    nav_contact_label = models.CharField(max_length=80, blank=True)
    admin_login_label = models.CharField(max_length=80, blank=True)
    dashboard_label = models.CharField(max_length=80, blank=True)
    logout_label = models.CharField(max_length=80, blank=True)
    portal_button_label = models.CharField(max_length=80, blank=True)
    portal_nav_label = models.CharField(max_length=80, blank=True)
    hero_stat_plans_label = models.CharField(max_length=255, blank=True)
    hero_stat_support_label = models.CharField(max_length=255, blank=True)
    hero_stat_portal_value = models.CharField(max_length=50, blank=True)
    hero_stat_portal_label = models.CharField(max_length=255, blank=True)
    meta_title = models.CharField(max_length=255, blank=True)
    meta_description = models.TextField(blank=True)
    meta_keywords = models.CharField(max_length=255, blank=True)
    og_title = models.CharField(max_length=255, blank=True)
    og_description = models.TextField(blank=True)
    about_text = models.TextField(blank=True)
    network_promise_eyebrow = models.CharField(max_length=120, blank=True)
    network_promise_title = models.CharField(max_length=255, blank=True)
    network_promise_body = models.TextField(blank=True)
    quick_actions_eyebrow = models.CharField(max_length=120, blank=True)
    quick_link_portal_title = models.CharField(max_length=120, blank=True)
    quick_link_portal_text = models.CharField(max_length=255, blank=True)
    quick_link_plans_title = models.CharField(max_length=120, blank=True)
    quick_link_plans_text = models.CharField(max_length=255, blank=True)
    quick_link_contact_title = models.CharField(max_length=120, blank=True)
    quick_link_contact_text = models.CharField(max_length=255, blank=True)
    operations_eyebrow = models.CharField(max_length=120, blank=True)
    operations_points = models.TextField(blank=True, help_text='One operations highlight per line')
    plans_section_eyebrow = models.CharField(max_length=120, blank=True)
    plans_section_title = models.CharField(max_length=255, blank=True)
    plans_section_intro = models.TextField(blank=True)
    featured_plan_badge = models.CharField(max_length=120, blank=True)
    plan_cta_label = models.CharField(max_length=120, blank=True)
    plan_fallback_features = models.TextField(blank=True, help_text='One fallback feature per line')
    why_section_eyebrow = models.CharField(max_length=120, blank=True)
    why_section_title = models.CharField(max_length=255, blank=True)
    why_section_intro = models.TextField(blank=True)
    why_card_1_eyebrow = models.CharField(max_length=120, blank=True)
    why_card_1_title = models.CharField(max_length=255, blank=True)
    why_card_1_body = models.TextField(blank=True)
    why_card_2_eyebrow = models.CharField(max_length=120, blank=True)
    why_card_2_title = models.CharField(max_length=255, blank=True)
    why_card_2_body = models.TextField(blank=True)
    why_card_3_eyebrow = models.CharField(max_length=120, blank=True)
    why_card_3_title = models.CharField(max_length=255, blank=True)
    why_card_3_body = models.TextField(blank=True)
    coverage_section_eyebrow = models.CharField(max_length=120, blank=True)
    coverage_section_title = models.CharField(max_length=255, blank=True)
    coverage_section_intro = models.TextField(blank=True)
    coverage_title = models.CharField(max_length=120, blank=True)
    coverage_text = models.TextField(blank=True)
    coverage_card_title = models.CharField(max_length=255, blank=True)
    payment_section_eyebrow = models.CharField(max_length=120, blank=True)
    payment_section_title = models.CharField(max_length=255, blank=True)
    payment_empty_notes = models.TextField(blank=True, help_text='One payment fallback note per line')
    faq_section_eyebrow = models.CharField(max_length=120, blank=True)
    faq_section_title = models.CharField(max_length=255, blank=True)
    faq_section_intro = models.TextField(blank=True)
    faq_empty_eyebrow = models.CharField(max_length=120, blank=True)
    faq_empty_title = models.CharField(max_length=255, blank=True)
    faq_empty_body = models.TextField(blank=True)
    inquiry_section_eyebrow = models.CharField(max_length=120, blank=True)
    inquiry_section_title = models.CharField(max_length=255, blank=True)
    inquiry_section_intro = models.TextField(blank=True)
    inquiry_info_eyebrow = models.CharField(max_length=120, blank=True)
    inquiry_info_title = models.CharField(max_length=255, blank=True)
    inquiry_info_body = models.TextField(blank=True)
    inquiry_highlights = models.TextField(blank=True, help_text='One inquiry highlight per line')
    inquiry_submit_label = models.CharField(max_length=120, blank=True)
    inquiry_success_message = models.CharField(max_length=255, blank=True)
    inquiry_full_name_label = models.CharField(max_length=120, blank=True)
    inquiry_full_name_placeholder = models.CharField(max_length=255, blank=True)
    inquiry_mobile_label = models.CharField(max_length=120, blank=True)
    inquiry_mobile_placeholder = models.CharField(max_length=255, blank=True)
    inquiry_service_address_label = models.CharField(max_length=120, blank=True)
    inquiry_service_address_placeholder = models.CharField(max_length=255, blank=True)
    inquiry_plan_label = models.CharField(max_length=120, blank=True)
    inquiry_message_label = models.CharField(max_length=120, blank=True)
    inquiry_message_placeholder = models.CharField(max_length=255, blank=True)
    contact_section_eyebrow = models.CharField(max_length=120, blank=True)
    contact_section_title = models.CharField(max_length=255, blank=True)
    contact_section_intro = models.TextField(blank=True)
    contact_card_eyebrow = models.CharField(max_length=120, blank=True)
    contact_card_title = models.CharField(max_length=255, blank=True)
    about_card_eyebrow = models.CharField(max_length=120, blank=True)
    about_card_title = models.CharField(max_length=255, blank=True)
    cta_banner_title = models.CharField(max_length=255, blank=True)
    cta_banner_body = models.TextField(blank=True)
    support_hours = models.CharField(max_length=120, blank=True)
    payment_channels = models.TextField(blank=True, help_text='One payment channel per line')
    contact_phone = models.CharField(max_length=50, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_address = models.TextField(blank=True)
    footer_text = models.TextField(blank=True)
    announcement = models.TextField(blank=True)
    primary_color = models.CharField(max_length=7, default='#2563eb')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.get_page_type_display()

    def payment_channel_list(self):
        return [item.strip() for item in self.payment_channels.split('\n') if item.strip()]

    @staticmethod
    def _split_lines(value):
        return [item.strip() for item in value.split('\n') if item.strip()]

    def operations_point_list(self):
        return self._split_lines(self.operations_points)

    def plan_fallback_feature_list(self):
        return self._split_lines(self.plan_fallback_features)

    def payment_empty_note_list(self):
        return self._split_lines(self.payment_empty_notes)

    def inquiry_highlight_list(self):
        return self._split_lines(self.inquiry_highlights)

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


class LandingFAQ(models.Model):
    page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name='faqs')
    question = models.CharField(max_length=255)
    answer = models.TextField()
    is_published = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'id']

    def __str__(self):
        return self.question


class LandingInquiry(models.Model):
    STATUS_CHOICES = [
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('closed', 'Closed'),
    ]

    page = models.ForeignKey(LandingPage, on_delete=models.CASCADE, related_name='inquiries')
    full_name = models.CharField(max_length=150)
    mobile_number = models.CharField(max_length=30)
    service_address = models.TextField()
    preferred_plan = models.CharField(max_length=120, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', '-created_at']

    def __str__(self):
        return f"{self.full_name} ({self.mobile_number})"
