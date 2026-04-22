from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.landing.forms import LandingFAQForm, LandingInquiryForm, LandingInquiryStatusForm
from apps.landing.models import LandingFAQ, LandingInquiry, LandingPage, LandingPlan
from apps.core.models import AuditLog

LANDING_EDITABLE_FIELDS = [
    'hero_badge', 'hero_title', 'hero_subtitle',
    'hero_primary_cta_label', 'hero_primary_cta_url',
    'hero_secondary_cta_label', 'hero_secondary_cta_url',
    'nav_plans_label', 'nav_why_us_label', 'nav_coverage_label', 'nav_contact_label',
    'admin_login_label', 'dashboard_label', 'logout_label',
    'portal_button_label', 'portal_nav_label',
    'hero_stat_plans_label', 'hero_stat_support_label',
    'hero_stat_portal_value', 'hero_stat_portal_label',
    'meta_title', 'meta_description', 'meta_keywords', 'og_title', 'og_description',
    'about_text',
    'network_promise_eyebrow', 'network_promise_title', 'network_promise_body',
    'quick_actions_eyebrow',
    'quick_link_portal_title', 'quick_link_portal_text',
    'quick_link_plans_title', 'quick_link_plans_text',
    'quick_link_contact_title', 'quick_link_contact_text',
    'operations_eyebrow', 'operations_points',
    'plans_section_eyebrow', 'plans_section_title', 'plans_section_intro',
    'featured_plan_badge', 'plan_cta_label', 'plan_fallback_features',
    'why_section_eyebrow', 'why_section_title', 'why_section_intro',
    'why_card_1_eyebrow', 'why_card_1_title', 'why_card_1_body',
    'why_card_2_eyebrow', 'why_card_2_title', 'why_card_2_body',
    'why_card_3_eyebrow', 'why_card_3_title', 'why_card_3_body',
    'coverage_section_eyebrow', 'coverage_section_title', 'coverage_section_intro',
    'coverage_title', 'coverage_text', 'coverage_card_title',
    'payment_section_eyebrow', 'payment_section_title', 'payment_empty_notes',
    'faq_section_eyebrow', 'faq_section_title', 'faq_section_intro',
    'faq_empty_eyebrow', 'faq_empty_title', 'faq_empty_body',
    'inquiry_section_eyebrow', 'inquiry_section_title', 'inquiry_section_intro',
    'inquiry_info_eyebrow', 'inquiry_info_title', 'inquiry_info_body',
    'inquiry_highlights', 'inquiry_submit_label', 'inquiry_success_message',
    'inquiry_full_name_label', 'inquiry_full_name_placeholder',
    'inquiry_mobile_label', 'inquiry_mobile_placeholder',
    'inquiry_service_address_label', 'inquiry_service_address_placeholder',
    'inquiry_plan_label', 'inquiry_message_label', 'inquiry_message_placeholder',
    'contact_section_eyebrow', 'contact_section_title', 'contact_section_intro',
    'contact_card_eyebrow', 'contact_card_title',
    'about_card_eyebrow', 'about_card_title',
    'cta_banner_title', 'cta_banner_body',
    'support_hours', 'payment_channels',
    'contact_phone', 'contact_email', 'contact_address',
    'footer_text', 'announcement',
]


@login_required
def landing_dashboard(request):
    homepage = LandingPage.get_homepage()
    captive = LandingPage.get_captive()
    return render(request, 'landing/dashboard.html', {
        'homepage': homepage,
        'captive': captive,
        'homepage_faq_count': homepage.faqs.count(),
        'homepage_inquiry_count': homepage.inquiries.count(),
        'homepage_new_inquiry_count': homepage.inquiries.filter(status='new').count(),
    })


@login_required
def landing_edit(request, page_type):
    if page_type not in ['homepage', 'captive']:
        return redirect('landing-dashboard')

    page = LandingPage.objects.get_or_create(page_type=page_type)[0]
    plans = page.plans.all()

    if request.method == 'POST':
        for field_name in LANDING_EDITABLE_FIELDS:
            setattr(page, field_name, request.POST.get(field_name, ''))
        page.primary_color = request.POST.get('primary_color', '#2563eb')
        page.save()

        AuditLog.log('update', 'landing', f"Landing page updated: {page_type}", user=request.user)
        messages.success(request, 'Page content saved.')
        return redirect('landing-edit', page_type=page_type)

    return render(request, 'landing/edit.html', {'page': page, 'plans': plans, 'page_type': page_type})


@login_required
def landing_publish(request, page_type):
    page = get_object_or_404(LandingPage, page_type=page_type)
    page.is_published = not page.is_published
    page.save(update_fields=['is_published'])
    status = 'published' if page.is_published else 'unpublished'
    messages.success(request, f"Page {status}.")
    return redirect('landing-dashboard')


@login_required
def landing_plan_add(request, page_type):
    page = get_object_or_404(LandingPage, page_type=page_type)
    if request.method == 'POST':
        LandingPlan.objects.create(
            page=page,
            name=request.POST.get('name', ''),
            speed=request.POST.get('speed', ''),
            price=request.POST.get('price', ''),
            features=request.POST.get('features', ''),
            is_featured='is_featured' in request.POST,
            sort_order=int(request.POST.get('sort_order', 0)),
        )
        messages.success(request, 'Plan added.')
    return redirect('landing-edit', page_type=page_type)


@login_required
def landing_plan_delete(request, pk):
    plan = get_object_or_404(LandingPlan, pk=pk)
    page_type = plan.page.page_type
    plan.delete()
    messages.success(request, 'Plan removed.')
    return redirect('landing-edit', page_type=page_type)


@login_required
def landing_faq_list(request, page_type):
    if page_type not in ['homepage', 'captive']:
        return redirect('landing-dashboard')

    page = LandingPage.objects.get_or_create(page_type=page_type)[0]
    faq_form = LandingFAQForm()
    faqs = page.faqs.all()
    return render(request, 'landing/faqs.html', {
        'page': page,
        'page_type': page_type,
        'faq_form': faq_form,
        'faqs': faqs,
    })


@login_required
def landing_faq_add(request, page_type):
    if page_type not in ['homepage', 'captive']:
        return redirect('landing-dashboard')

    page = LandingPage.objects.get_or_create(page_type=page_type)[0]
    if request.method != 'POST':
        return redirect('landing-faq-list', page_type=page_type)

    form = LandingFAQForm(request.POST)
    if form.is_valid():
        faq = form.save(commit=False)
        faq.page = page
        faq.save()
        AuditLog.log('create', 'landing', f"Landing FAQ added: {faq.question}", user=request.user)
        messages.success(request, 'FAQ added.')
    else:
        messages.error(request, 'Please fix the FAQ form errors and try again.')
    return redirect('landing-faq-list', page_type=page_type)


@login_required
def landing_faq_edit(request, pk):
    faq = get_object_or_404(LandingFAQ, pk=pk)
    if request.method != 'POST':
        return redirect('landing-faq-list', page_type=faq.page.page_type)

    form = LandingFAQForm(request.POST, instance=faq)
    if form.is_valid():
        form.save()
        AuditLog.log('update', 'landing', f"Landing FAQ updated: {faq.question}", user=request.user)
        messages.success(request, 'FAQ updated.')
    else:
        messages.error(request, 'FAQ update failed. Please review the fields.')
    return redirect('landing-faq-list', page_type=faq.page.page_type)


@login_required
def landing_faq_delete(request, pk):
    faq = get_object_or_404(LandingFAQ, pk=pk)
    page_type = faq.page.page_type
    question = faq.question
    faq.delete()
    AuditLog.log('delete', 'landing', f"Landing FAQ removed: {question}", user=request.user)
    messages.success(request, 'FAQ removed.')
    return redirect('landing-faq-list', page_type=page_type)


@login_required
def landing_inquiry_list(request):
    homepage = LandingPage.get_homepage()
    status_filter = request.GET.get('status', '').strip()
    inquiries = homepage.inquiries.all()
    if status_filter:
        inquiries = inquiries.filter(status=status_filter)

    return render(request, 'landing/inquiries.html', {
        'homepage': homepage,
        'inquiries': inquiries,
        'status_filter': status_filter,
        'status_choices': LandingInquiry.STATUS_CHOICES,
    })


@login_required
def landing_inquiry_update(request, pk):
    inquiry = get_object_or_404(LandingInquiry, pk=pk)
    if request.method != 'POST':
        return redirect('landing-inquiry-list')

    form = LandingInquiryStatusForm(request.POST, instance=inquiry)
    if form.is_valid():
        form.save()
        AuditLog.log('update', 'landing', f"Landing inquiry status updated: {inquiry.full_name}", user=request.user)
        messages.success(request, 'Inquiry status updated.')
    else:
        messages.error(request, 'Unable to update inquiry status.')
    return redirect('landing-inquiry-list')


# Public pages
def public_homepage(request):
    page = LandingPage.get_homepage()
    if not page.is_published:
        return render(request, 'landing/coming_soon.html', {'page': page})

    inquiry_form = LandingInquiryForm(page=page)
    if request.method == 'POST':
        inquiry_form = LandingInquiryForm(request.POST, page=page)
        if inquiry_form.is_valid():
            inquiry = inquiry_form.save(commit=False)
            inquiry.page = page
            inquiry.save()
            AuditLog.log('create', 'landing', f"Landing inquiry submitted: {inquiry.full_name}", user=None)
            messages.success(request, page.inquiry_success_message or 'Inquiry received. Our team will reach out soon.')
            return redirect('public-homepage')
        messages.error(request, 'Please review the inquiry form and try again.')

    faqs = page.faqs.filter(is_published=True)
    return render(request, 'landing/public_home.html', {
        'page': page,
        'plans': page.plans.all(),
        'faqs': faqs,
        'inquiry_form': inquiry_form,
    })


def public_captive(request):
    page = LandingPage.get_captive()
    return render(request, 'landing/public_captive.html', {'page': page, 'plans': page.plans.all()})
