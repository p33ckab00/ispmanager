RMO_38_2018_URL = 'https://bir-cdn.bir.gov.ph/local/pdf/RMO_No.38-2018.pdf'
RMO_18_2025_URL = 'https://bir-cdn.bir.gov.ph/BIR/pdf/RMO%20No.%2018-2025%20Digest.pdf'
RMO_46_2025_URL = 'https://bir-cdn.bir.gov.ph/BIR/pdf/RMO%20No.%2046-2025%20Digest.pdf'
TAXUMO_ATC_URL = (
    'https://taxumo.com/blog/list-of-bir-atc-for-income-tax-filing-and-withholding-tax/'
)


def _atc(
    code,
    description,
    rate,
    taxpayer_type,
    payor_type='any',
    source_reference='BIR RMO No. 38-2018',
    source_url=RMO_38_2018_URL,
    bir_form='1601-EQ/2307',
    is_active=True,
    notes='',
):
    rate_text = f"{rate:g}%"
    return {
        'code': code,
        'description': description,
        'tax_family': 'expanded_withholding_tax',
        'taxpayer_type': taxpayer_type,
        'rate': f"{rate:.4f}",
        'rate_label': rate_text,
        'bir_form': bir_form,
        'payor_type': payor_type,
        'source_reference': source_reference,
        'source_url': source_url,
        'is_active': is_active,
        'notes': notes,
    }


def _threshold_pair(base_code, description, individual_rates=(5, 10), corporate_rates=(10, 15)):
    rows = [
        _atc(
            f"WI{base_code}0",
            f"{description} - individual, gross income for the current year did not exceed P3M",
            individual_rates[0],
            'individual',
        ),
        _atc(
            f"WI{base_code}1",
            f"{description} - individual, gross income is more than P3M or VAT registered",
            individual_rates[1],
            'individual',
        ),
    ]
    if corporate_rates:
        rows.extend([
            _atc(
                f"WC{base_code}0",
                f"{description} - corporate, gross income for the current year did not exceed P720,000",
                corporate_rates[0],
                'corporation',
            ),
            _atc(
                f"WC{base_code}1",
                f"{description} - corporate, gross income exceeds P720,000",
                corporate_rates[1],
                'corporation',
            ),
        ])
    return rows


def _both(code, description, rate, payor_type='any', **kwargs):
    return [
        _atc(f"WI{code}", description, rate, 'individual', payor_type=payor_type, **kwargs),
        _atc(f"WC{code}", description, rate, 'corporation', payor_type=payor_type, **kwargs),
    ]


COMMON_BIR_ATC_CODES = [
    *_threshold_pair('01', 'Professionals such as lawyers, CPAs, engineers and similar providers'),
    *_threshold_pair('02', 'Professional entertainers such as actors, singers, lyricists, composers and emcees'),
    *_threshold_pair('03', 'Professional athletes including basketball players, pelotaris and jockeys'),
    *_threshold_pair('04', 'Movie, stage, radio, television and musical directors/producers'),
    *_threshold_pair('05', 'Management and technical consultants'),
    *_threshold_pair('06', 'Business and bookkeeping agents and agencies'),
    *_threshold_pair('07', 'Insurance agents and insurance adjusters'),
    *_threshold_pair('08', 'Other recipients of talent fees'),
    *_threshold_pair('09', 'Fees of directors who are not employees of the company', corporate_rates=None),
    *_both('100', 'Rentals for real or personal property, poles, satellites, transmission facilities and billboards', 5),
    *_both('110', 'Cinematographic film rentals and other payments to resident cinematographic film owners, lessors or distributors', 5),
    *_both('120', 'Income payments to certain contractors, prime contractors and subcontractors', 2),
    _atc('WI130', 'Income distribution to beneficiaries of estates and trusts', 15, 'individual'),
    _atc(
        'WI139',
        'Gross commissions or service fees of customs, insurance, stock, immigration and commercial brokers, agents of professional entertainers and real estate service practitioners - individual below threshold',
        5,
        'individual',
    ),
    _atc(
        'WI140',
        'Gross commissions or service fees of customs, insurance, stock, immigration and commercial brokers, agents of professional entertainers and real estate service practitioners - individual above threshold',
        10,
        'individual',
    ),
    _atc(
        'WC139',
        'Gross commissions or service fees of customs, insurance, stock, immigration and commercial brokers, agents of professional entertainers and real estate service practitioners - corporate below threshold',
        10,
        'corporation',
    ),
    _atc(
        'WC140',
        'Gross commissions or service fees of customs, insurance, stock, immigration and commercial brokers, agents of professional entertainers and real estate service practitioners - corporate above threshold',
        15,
        'corporation',
    ),
    _atc('WI151', 'Professional fees paid to medical practitioners by hospitals, clinics, HMOs or similar establishments - individual below threshold', 5, 'individual'),
    _atc('WI150', 'Professional fees paid to medical practitioners by hospitals, clinics, HMOs or similar establishments - individual above threshold', 10, 'individual'),
    _atc('WC151', 'Professional fees paid to medical practitioners by hospitals, clinics, HMOs or similar establishments - corporate below threshold', 10, 'corporation'),
    _atc('WC150', 'Professional fees paid to medical practitioners by hospitals, clinics, HMOs or similar establishments - corporate above threshold', 15, 'corporation'),
    _atc('WI152', 'Payments by general professional partnerships to partners - current year income payments did not exceed P720,000', 10, 'individual'),
    _atc('WI153', 'Payments by general professional partnerships to partners - current year income payments exceed P720,000', 15, 'individual'),
    *_both(
        '156',
        'Income payments made by credit card companies',
        0.5,
        source_reference='BIR RMO No. 18-2025',
        source_url=RMO_18_2025_URL,
        notes='RMO No. 18-2025 modified the rate to 1/2%.',
    ),
    _atc('WI159', 'Additional income payments to government personnel from importers, shipping and airline companies or their agents for overtime services', 15, 'individual'),
    *_both('640', 'Income payments made by the government to local or resident suppliers of goods', 1, payor_type='government'),
    *_both('157', 'Income payments made by the government to local or resident suppliers of services', 2, payor_type='government'),
    *_both('158', 'Income payments made by top withholding agents to local or resident suppliers of goods other than those covered by other rates', 1, payor_type='top_withholding_agent'),
    *_both('160', 'Income payments made by top withholding agents to local or resident suppliers of services other than those covered by other rates', 2, payor_type='top_withholding_agent'),
    _atc('WI515', 'Commissions, rebates, discounts and similar considerations to independent sales representatives and marketing agents - individual below threshold', 5, 'individual'),
    _atc('WI516', 'Commissions, rebates, discounts and similar considerations to independent sales representatives and marketing agents - individual above threshold', 10, 'individual'),
    _atc('WC515', 'Commissions, rebates, discounts and similar considerations to independent sales representatives and marketing agents - corporate below threshold', 10, 'corporation'),
    _atc('WC516', 'Commissions, rebates, discounts and similar considerations to independent sales representatives and marketing agents - corporate above threshold', 15, 'corporation'),
    _atc('WI530', 'Gross payments to embalmers by funeral parlors', 1, 'individual'),
    *_both('535', 'Payments made by pre-need companies to funeral parlors', 1),
    *_both('540', 'Tolling fees paid to refineries', 5),
    *_both('610', 'Income payments to suppliers of agricultural products in excess of cumulative annual amount threshold', 1),
    *_both('630', 'Income payments on purchases of minerals, mineral products and quarry resources', 5),
    *_both('632', 'Income payments on purchases of minerals, mineral products and quarry resources paid by BSP to gold miners or suppliers', 1),
    *_both('650', 'Refund of bill deposit by MERALCO to customers with active contracts', 15),
    *_both('651', 'Refund of bill deposit by MERALCO to customers with inactive or terminated contracts', 15),
    *_both('660', 'Interest on refund of meter deposit paid to residential and general service customers with monthly electricity consumption not exceeding 200 kWh', 10),
    *_both('661', 'Interest on refund of meter deposit paid to non-residential customers with monthly electricity consumption not exceeding 200 kWh', 15),
    *_both('662', 'Interest on refund of meter deposit paid to residential and general service customers with monthly electricity consumption exceeding 200 kWh', 10),
    *_both('663', 'Interest on refund of meter deposit paid to non-residential customers with monthly electricity consumption exceeding 200 kWh', 15),
    *_both('680', 'Income payments by political parties and candidates for campaign purchases of goods and services', 5),
    _atc('WC690', 'Income payments received by Real Estate Investment Trust (REIT)', 1, 'corporation'),
    *_both('710', 'Income derived from debt instruments not within the coverage of deposit substitutes and revenue regulations', 15),
    *_both('720', 'Income payments on locally produced raw sugar', 1),
    _atc(
        'WI760',
        'Dropped: gross remittances by e-marketplace operators and digital financial service providers to sellers or merchants',
        1,
        'individual',
        source_reference='BIR RMO No. 18-2025',
        source_url=RMO_18_2025_URL,
        is_active=False,
        notes='Dropped by RMO No. 18-2025.',
    ),
    _atc(
        'WC760',
        'Dropped: gross remittances by e-marketplace operators and digital financial service providers to sellers or merchants',
        1,
        'corporation',
        source_reference='BIR RMO No. 18-2025',
        source_url=RMO_18_2025_URL,
        is_active=False,
        notes='Dropped by RMO No. 18-2025.',
    ),
    *_both(
        '820',
        'One-half of gross remittances by e-marketplace operators to sellers or merchants for goods or services sold or paid through their platform',
        0.5,
        payor_type='top_withholding_agent',
        source_reference='BIR RMO No. 18-2025',
        source_url=RMO_18_2025_URL,
    ),
    *_both(
        '830',
        'One-half of gross remittances by digital financial services providers to sellers or merchants for goods or services sold or paid through their facility',
        0.5,
        payor_type='top_withholding_agent',
        source_reference='BIR RMO No. 18-2025',
        source_url=RMO_18_2025_URL,
    ),
    *_both(
        '840',
        'Income payments by top withholding agents to manufacturers and direct importers of motor vehicles and motor vehicle parts/accessories',
        0.5,
        payor_type='top_withholding_agent',
        source_reference='BIR RMO No. 46-2025',
        source_url=RMO_46_2025_URL,
    ),
]


DEFAULT_BIR_ATC_CODES = COMMON_BIR_ATC_CODES
