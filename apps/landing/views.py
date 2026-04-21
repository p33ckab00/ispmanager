from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from apps.landing.models import LandingPage, LandingPlan
from apps.core.models import AuditLog


@login_required
def landing_dashboard(request):
    homepage = LandingPage.get_homepage()
    captive = LandingPage.get_captive()
    return render(request, 'landing/dashboard.html', {'homepage': homepage, 'captive': captive})


@login_required
def landing_edit(request, page_type):
    if page_type not in ['homepage', 'captive']:
        return redirect('landing-dashboard')

    page = LandingPage.objects.get_or_create(page_type=page_type)[0]
    plans = page.plans.all()

    if request.method == 'POST':
        page.hero_title = request.POST.get('hero_title', '')
        page.hero_subtitle = request.POST.get('hero_subtitle', '')
        page.about_text = request.POST.get('about_text', '')
        page.contact_phone = request.POST.get('contact_phone', '')
        page.contact_email = request.POST.get('contact_email', '')
        page.contact_address = request.POST.get('contact_address', '')
        page.footer_text = request.POST.get('footer_text', '')
        page.announcement = request.POST.get('announcement', '')
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


# Public pages
def public_homepage(request):
    page = LandingPage.get_homepage()
    if not page.is_published:
        return render(request, 'landing/coming_soon.html', {'page': page})
    return render(request, 'landing/public_home.html', {'page': page, 'plans': page.plans.all()})


def public_captive(request):
    page = LandingPage.get_captive()
    return render(request, 'landing/public_captive.html', {'page': page, 'plans': page.plans.all()})
