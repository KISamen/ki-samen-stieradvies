"""
Dynamische regelgenerering op basis van gebruikersinstellingen.
Vertaalt gebruikersvoorkeuren naar applicabele regels.
"""


def build_rules_from_settings(settings):
    """
    Genereer complete regelset op basis van gebruikersinstellingen.

    Input: settings dict met thresholds en preferenties
    Output: rules dict met alle geëvalueerde regels
    """
    vaars_threshold = settings.get('vaars_lactation_threshold', 92)
    koe_threshold = settings.get('koe_lactation_threshold', 98)
    insem_threshold = settings.get('insemination_threshold', 3)
    cell_threshold = settings.get('cell_count_threshold', 300)
    inbreed_threshold = settings.get('inbreeding_threshold', 12.5)

    rules = {
        'belgian_witblauw': [
            {
                'id': 'bwb_vaars_low_lactation',
                'name': 'Vaars met lage melkproductie',
                'field': 'lactation_value',
                'condition': 'lt',
                'threshold': vaars_threshold,
                'extra_field': 'lactation_number',
                'extra_condition': 'eq',
                'extra_value': 1,
                'action': 'belgian_witblauw',
                'priority': 1,
                'reason': f'Vaars met lactatiewaarde < {vaars_threshold}',
                'applies_to': 'vaars',
            },
            {
                'id': 'bwb_koe_low_lactation',
                'name': 'Koe met lage melkproductie',
                'field': 'lactation_value',
                'condition': 'lt',
                'threshold': koe_threshold,
                'extra_field': 'lactation_number',
                'extra_condition': 'gt',
                'extra_value': 1,
                'action': 'belgian_witblauw',
                'priority': 1,
                'reason': f'Koe met lactatiewaarde < {koe_threshold}',
                'applies_to': 'koe',
            },
            {
                'id': 'bwb_high_inseminations',
                'name': 'Veel inseminaties',
                'field': 'inseminations',
                'condition': 'gte',
                'threshold': insem_threshold,
                'action': 'belgian_witblauw',
                'priority': 2,
                'reason': f'>={insem_threshold} inseminaties',
                'applies_to': 'all',
            },
            {
                'id': 'bwb_high_cell_count',
                'name': 'Hoog celgetal',
                'field': 'cell_count',
                'condition': 'gt',
                'threshold': cell_threshold,
                'action': 'belgian_witblauw',
                'priority': 2,
                'reason': f'Celgetal > {cell_threshold}',
                'applies_to': 'all',
            },
            {
                'id': 'bwb_high_inbreeding',
                'name': 'Hoog inteeltrisico',
                'field': 'inbreeding_coefficient',
                'condition': 'gt',
                'threshold': inbreed_threshold,
                'action': 'belgian_witblauw',
                'priority': 3,
                'reason': f'Inteelt > {inbreed_threshold}%',
                'applies_to': 'all',
            },
        ],
        'milking_sire': [
            {
                'id': 'milking_sire_medium_lactation',
                'name': 'Gemiddelde melkproductie',
                'field': 'lactation_value',
                'condition': 'range',
                'threshold_low': vaars_threshold,
                'threshold_high': koe_threshold,
                'action': 'milking_sire',
                'priority': 2,
                'reason': 'Fokstier aanbevolen',
                'applies_to': 'all',
            },
        ],
        'genetic_merit': [
            {
                'id': 'genetic_merit_high_lactation',
                'name': 'Hoge melkproductie',
                'field': 'lactation_value',
                'condition': 'gte',
                'threshold': koe_threshold,
                'action': 'genetic_merit',
                'priority': 3,
                'reason': 'Fokstier op genetische verdienste',
                'applies_to': 'all',
            },
        ],
    }

    return rules


def evaluate_rule(animal_data, rule):
    """
    Evalueer één regel tegen dierdata.
    Retourneert True als de regel van toepassing is.
    """
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

    # Primaire conditie
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

    # Extra conditie (bijv. lactation_number check)
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


def get_applicable_rules(animal_data, rules):
    """
    Bepaal welke regels van toepassing zijn op dit dier.
    """
    applicable = []

    for category, rule_list in rules.items():
        for rule in rule_list:
            if evaluate_rule(animal_data, rule):
                applicable.append({
                    'category': category,
                    'rule': rule,
                    'priority': rule.get('priority', 999),
                })

    applicable.sort(key=lambda x: x['priority'])
    return applicable


def determine_advice_type(animal_data, rules):
    """
    Bepaal het adviestype voor één dier.
    Retourneer het adviestype met hoogste prioriteit.
    """
    applicable = get_applicable_rules(animal_data, rules)

    if not applicable:
        return 'genetic_merit', 'Standaard advies: hoge genetische verdienste'

    best = applicable[0]
    return best['category'], best['rule'].get('reason', '')


def format_rules_for_display(rules):
    """
    Formatteer regels voor UI-weergave als lijst van dicts.
    """
    formatted = []

    for category, rule_list in rules.items():
        for rule in rule_list:
            formatted.append({
                'Categorie': category,
                'Naam': rule.get('name', ''),
                'Reden': rule.get('reason', ''),
                'Prioriteit': rule.get('priority', 999),
            })

    return formatted
