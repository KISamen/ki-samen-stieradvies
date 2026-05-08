"""
Regelgenerering op basis van gebruikersinstellingen.
Vertaalt drempelwaarden naar evalueerbare regels.
"""


def build_rules_from_settings(settings: dict) -> list[dict]:
    """
    Genereer de volledige regelset op basis van gebruikersinstellingen.
    Retourneert een platte lijst van regels.
    """
    vaars_threshold = settings.get('vaars_lactation_threshold', 92)
    koe_threshold = settings.get('koe_lactation_threshold', 98)
    insem_threshold = settings.get('insemination_threshold', 3)
    cell_threshold = settings.get('cell_count_threshold', 300)
    inbreed_threshold = settings.get('inbreeding_threshold', 12.5)

    return [
        {
            'id': 'bwb_vaars_low_lactation',
            'field': 'lactation_value',
            'condition': 'lt',
            'threshold': vaars_threshold,
            'extra_field': 'lactation_number',
            'extra_condition': 'eq',
            'extra_value': 1,
            'action': 'belgian_witblauw',
            'priority': 1,
            'reason': f'Vaars heeft lactatiewaarde onder de grens van {vaars_threshold}',
        },
        {
            'id': 'bwb_koe_low_lactation',
            'field': 'lactation_value',
            'condition': 'lt',
            'threshold': koe_threshold,
            'extra_field': 'lactation_number',
            'extra_condition': 'gt',
            'extra_value': 1,
            'action': 'belgian_witblauw',
            'priority': 1,
            'reason': f'Koe heeft lactatiewaarde onder de grens van {koe_threshold}',
        },
        {
            'id': 'bwb_high_inseminations',
            'field': 'inseminations',
            'condition': 'gte',
            'threshold': insem_threshold,
            'action': 'belgian_witblauw',
            'priority': 2,
            'reason': f'Dier heeft {"{inseminations}"} inseminaties (grens: {insem_threshold})',
            'reason_template': True,
        },
        {
            'id': 'bwb_high_cell_count',
            'field': 'cell_count',
            'condition': 'gt',
            'threshold': cell_threshold,
            'action': 'belgian_witblauw',
            'priority': 2,
            'reason': f'Celgetal is boven de grens van {cell_threshold}',
        },
        {
            'id': 'bwb_high_inbreeding',
            'field': 'inbreeding_coefficient',
            'condition': 'gt',
            'threshold': inbreed_threshold,
            'action': 'belgian_witblauw',
            'priority': 3,
            'reason': f'Inteelt is boven de grens van {inbreed_threshold}%',
        },
    ]


def evaluate_rule(animal_data: dict, rule: dict) -> bool:
    """Evalueer één regel. Retourneert True als de regel van toepassing is."""
    field = rule.get('field')
    condition = rule.get('condition')
    threshold = rule.get('threshold')

    value = animal_data.get(field)
    if value is None:
        return False
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False

    match = False
    if condition == 'lt':
        match = value < threshold
    elif condition == 'lte':
        match = value <= threshold
    elif condition == 'gt':
        match = value > threshold
    elif condition == 'gte':
        match = value >= threshold
    elif condition == 'eq':
        match = value == threshold
    elif condition == 'range':
        low = rule.get('threshold_low', 0)
        high = rule.get('threshold_high', 9999)
        match = low <= value < high

    if not match:
        return False

    extra_field = rule.get('extra_field')
    if extra_field:
        extra_value = animal_data.get(extra_field)
        if extra_value is None:
            return False
        try:
            extra_value = float(extra_value)
        except (TypeError, ValueError):
            return False
        extra_condition = rule.get('extra_condition')
        extra_threshold = rule.get('extra_value')
        if extra_condition == 'eq' and extra_value != extra_threshold:
            return False
        elif extra_condition == 'gt' and extra_value <= extra_threshold:
            return False
        elif extra_condition == 'lt' and extra_value >= extra_threshold:
            return False
        elif extra_condition == 'gte' and extra_value < extra_threshold:
            return False

    return True


def get_all_bwb_reasons(animal_data: dict, rules: list[dict]) -> list[str]:
    """
    Geeft ALLE redenen terug waarom dit dier BWB-advies krijgt.
    Lege lijst = geen BWB-indicatie → fokstieradvies.
    """
    reasons = []
    for rule in rules:
        if rule.get('action') != 'belgian_witblauw':
            continue
        if not evaluate_rule(animal_data, rule):
            continue

        reason_text = rule.get('reason', '')
        # Vervang {inseminations} placeholder als aanwezig
        if rule.get('reason_template'):
            insem = animal_data.get('inseminations', '?')
            reason_text = f'Dier heeft {insem} inseminaties (grens: {rule["threshold"]})'
        reasons.append(reason_text)

    return reasons


def check_data_quality(animal_data: dict) -> dict[str, str]:
    """
    Controleer datakwaliteit per veld.
    Retourneert dict {veld: 'ok'|'missing'|'warning'}.
    """
    quality = {}
    required = {
        'animal_id': 'Dier-ID',
        'lactation_number': 'Lactatienummer',
        'lactation_value': 'Lactatiewaarde',
        'inseminations': 'Aantal inseminaties',
        'cell_count': 'Celgetal',
    }
    optional = {
        'sire_name': 'Vadernaam (inteeltcontrole)',
        'aaa_code': 'aAa-code (bouwcorrectie)',
        'pfw': 'PFW-code (bouwcorrectie)',
        'inbreeding_coefficient': 'Inteeltcoëfficiënt',
    }

    for field, label in required.items():
        val = animal_data.get(field)
        if val is None or str(val).strip() in ('', 'nan', '0', 'None'):
            quality[field] = 'missing'
        else:
            try:
                if float(val) == 0.0 and field in ('lactation_value', 'inseminations', 'cell_count'):
                    quality[field] = 'warning'
                else:
                    quality[field] = 'ok'
            except (TypeError, ValueError):
                quality[field] = 'ok'

    for field, label in optional.items():
        val = animal_data.get(field)
        if val is None or str(val).strip() in ('', 'nan', 'None'):
            quality[field] = 'missing'
        else:
            quality[field] = 'ok'

    return quality


def get_data_warnings(quality: dict[str, str]) -> list[str]:
    """Vertaal datakwaliteitsresultaat naar leesbare waarschuwingen."""
    warnings = []
    field_labels = {
        'animal_id': 'Dier-ID',
        'lactation_number': 'Lactatienummer',
        'lactation_value': 'Lactatiewaarde',
        'inseminations': 'Aantal inseminaties',
        'cell_count': 'Celgetal',
        'sire_name': 'Vadernaam',
        'aaa_code': 'aAa-code',
        'pfw': 'PFW-code',
        'inbreeding_coefficient': 'Inteeltcoëfficiënt',
    }

    missing_required = [
        f for f in ('lactation_value', 'lactation_number', 'inseminations', 'cell_count')
        if quality.get(f) == 'missing'
    ]
    if missing_required:
        labels = [field_labels.get(f, f) for f in missing_required]
        warnings.append(f"Geen definitief advies mogelijk: ontbrekende velden: {', '.join(labels)}.")

    zero_warning = [
        f for f in ('lactation_value', 'cell_count')
        if quality.get(f) == 'warning'
    ]
    if zero_warning:
        labels = [field_labels.get(f, f) for f in zero_warning]
        warnings.append(f"Controleer velden met waarde 0: {', '.join(labels)}.")

    if quality.get('sire_name') == 'missing':
        warnings.append('Inteeltcontrole beperkt: vadernaam ontbreekt.')

    if quality.get('aaa_code') == 'missing' and quality.get('pfw') == 'missing':
        warnings.append('Bouwcorrectie niet mogelijk: aAa-code en PFW-code ontbreken.')

    return warnings
