import csv
import hashlib
import io
import json
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse
from django.template.loader import render_to_string
from django.utils import timezone


def _display_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if value is None:
        return ''
    return str(value)


def _workbook_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    return value


def canonical_csv_bytes(headers, rows):
    text = io.StringIO()
    writer = csv.writer(text)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_display_value(value) for value in row])
    return text.getvalue().encode('utf-8')


def build_report_manifest(report_name, filename_base, headers, rows, filters, entity='', generated_by=''):
    csv_bytes = canonical_csv_bytes(headers, rows)
    return {
        'report_name': report_name,
        'entity': str(entity or ''),
        'generated_at': timezone.now().isoformat(),
        'generated_by': generated_by or '',
        'filters': filters,
        'row_count': len(rows),
        'columns': list(headers),
        'canonical_data': {
            'filename': f'{filename_base}.csv',
            'sha256': hashlib.sha256(csv_bytes).hexdigest(),
            'bytes': len(csv_bytes),
        },
        'notes': [
            'Hash is computed from canonical CSV data for this report run.',
            'Manifest is a generated workpaper record; immutable archive storage is a future slice.',
        ],
    }


def csv_report_response(filename, headers, rows, manifest):
    response = HttpResponse(canonical_csv_bytes(headers, rows), content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Report-Data-SHA256'] = manifest['canonical_data']['sha256']
    return response


def xlsx_report_response(filename, report_name, headers, rows, manifest):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    workbook = Workbook()
    manifest_sheet = workbook.active
    manifest_sheet.title = 'Manifest'
    manifest_sheet.append(['Field', 'Value'])
    for key in ('report_name', 'entity', 'generated_at', 'generated_by', 'row_count'):
        manifest_sheet.append([key, manifest[key]])
    manifest_sheet.append(['canonical_csv_filename', manifest['canonical_data']['filename']])
    manifest_sheet.append(['canonical_csv_sha256', manifest['canonical_data']['sha256']])
    manifest_sheet.append(['filters', json.dumps(manifest['filters'], default=str, sort_keys=True)])

    report_sheet = workbook.create_sheet('Report')
    report_sheet.append(list(headers))
    for cell in report_sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF')
        cell.fill = PatternFill('solid', fgColor='374151')
    for row in rows:
        report_sheet.append([_workbook_value(value) for value in row])
    report_sheet.freeze_panes = 'A2'

    for sheet in (manifest_sheet, report_sheet):
        for column_cells in sheet.columns:
            max_length = max(len(_display_value(cell.value)) for cell in column_cells)
            sheet.column_dimensions[column_cells[0].column_letter].width = min(max(max_length + 2, 12), 48)

    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Report-Data-SHA256'] = manifest['canonical_data']['sha256']
    return response


def pdf_report_response(request, filename, report_name, headers, rows, filters, manifest, entity=''):
    html = render_to_string('accounting/report_export_pdf.html', {
        'report_name': report_name,
        'entity': entity,
        'headers': headers,
        'rows': rows,
        'filters': filters,
        'manifest': manifest,
    }, request=request)

    try:
        from xhtml2pdf import pisa
        pdf_buffer = io.BytesIO()
        status = pisa.CreatePDF(html.encode('utf-8'), dest=pdf_buffer, encoding='utf-8')
        if status.err:
            raise RuntimeError(f'PDF generation failed: {status.err}')
        response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
    except Exception:
        response = HttpResponse(html, content_type='text/html')
        response['Content-Disposition'] = f'attachment; filename="{filename.replace(".pdf", ".html")}"'
    response['X-Report-Data-SHA256'] = manifest['canonical_data']['sha256']
    return response


def manifest_response(filename, manifest):
    payload = json.dumps(manifest, indent=2, default=str, sort_keys=True).encode('utf-8')
    response = HttpResponse(payload, content_type='application/json')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Report-Data-SHA256'] = manifest['canonical_data']['sha256']
    return response


def report_export_response(request, filename_base, report_name, headers, rows, filters, entity=''):
    export_format = (request.GET.get('format') or '').lower()
    if export_format not in ('csv', 'xlsx', 'pdf', 'manifest'):
        return None

    rows = list(rows)
    generated_by = request.user.get_username() if getattr(request, 'user', None) and request.user.is_authenticated else ''
    manifest = build_report_manifest(
        report_name,
        filename_base,
        headers,
        rows,
        filters,
        entity=entity,
        generated_by=generated_by,
    )
    if export_format == 'csv':
        return csv_report_response(f'{filename_base}.csv', headers, rows, manifest)
    if export_format == 'xlsx':
        return xlsx_report_response(f'{filename_base}.xlsx', report_name, headers, rows, manifest)
    if export_format == 'pdf':
        return pdf_report_response(
            request,
            f'{filename_base}.pdf',
            report_name,
            headers,
            rows,
            filters,
            manifest,
            entity=entity,
        )
    return manifest_response(f'{filename_base}-manifest.json', manifest)
