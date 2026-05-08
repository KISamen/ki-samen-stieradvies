"""
Advies-engine: evalueert dieren op basis van regelset en stiert-matching.
"""
import json
import os

import pandas as pd

from engine.rule_builder import build_rules_from_settings, determine_advice_type, get_applicable_rules


def load_bulls_from_config():
    """Laad stieren uit config bestand."""
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'bull_categories.json')
    try:
        with open(config_path, encoding='utf-8') as f:
            data = json.load(f)
        return pd.DataFrame(data.get('sample_bulls', []))
    except Exception:
        return pd.DataFrame()


def get_bulls_database():
    """
    Laad stierendatabase.
    Toekomst: Playwright scraper. Nu: config-bestand + cache.
    """
    bulls_df = load_bulls_from_config()

    # Voeg cache toe als die bestaat
    cache_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'bulls_cache.json')
    if os.path.exists(cache_path):
        try:
            cached = pd.read_json(cache_path)
            if not cached.empty:
                bulls_df = pd.concat([bulls_df, cached], ignore_index=True)
                bulls_df = bulls_df.drop_duplicates(subset=['name'])
        except Exception:
            pass

    return bulls_df


def _score_bull(animal_data, bull, advice_type):
    """
    Score een stier voor een dier op basis van meerdere factoren.
    Retourneert float 0.0-1.0.
    """
    score = 0.5  # Basiscore

    # Ras-match: stier moet passen bij adviestype
    bull_breed = str(bull.get('breed', '')).lower().replace(' ', '_')
    if advice_type == 'belgian_witblauw' and 'belgisch' in bull_breed or 'belgian' in bull_breed:
        score += 0.3
    elif advice_type in ('milking_sire', 'genetic_merit') and 'belgisch' not in bull_breed and 'belgian' not in bull_breed:
        score += 0.2

    # Kalfgemak voor vaarzen
    lactation_number = animal_data.get('lactation_number', 2)
    try:
        lactation_number = float(lactation_number)
    except (TypeError, ValueError):
        lactation_number = 2

    if lactation_number == 1:
        calf_ease = bull.get('calf_ease_female', 85)
        try:
            calf_ease = float(calf_ease)
        except (TypeError, ValueError):
            calf_ease = 85
        if calf_ease >= 90:
            score += 0.15
        elif calf_ease >= 85:
            score += 0.08

    # Beschikbaarheid
    if bull.get('available', True):
        score += 0.05

    # Kappa-caseïne bonus
    if bull.get('kappa_casein') == 'BB':
        score += 0.05

    return min(1.0, score)


def _find_best_bull(animal_data, bulls_df, advice_type, excluded_bulls=None):
    """
    Vind de beste stier voor dit dier en adviestype.
    """
    if bulls_df.empty:
        return None, 0.0

    excluded_bulls = excluded_bulls or set()

    # Filter op adviestype
    type_map = {
        'belgian_witblauw': ['belgian_witblauw'],
        'milking_sire': ['milking_sire', 'genetic_merit'],
        'genetic_merit': ['genetic_merit', 'milking_sire'],
    }
    allowed_breeds = type_map.get(advice_type, ['genetic_merit'])

    candidates = bulls_df[bulls_df['breed'].isin(allowed_breeds)].copy()
    candidates = candidates[~candidates['name'].isin(excluded_bulls)]
    candidates = candidates[candidates.get('available', pd.Series([True] * len(candidates)))]

    if candidates.empty:
        candidates = bulls_df[~bulls_df['name'].isin(excluded_bulls)]

    if candidates.empty:
        return None, 0.0

    # Score elke kandidaat
    scores = []
    for _, bull in candidates.iterrows():
        score = _score_bull(animal_data, bull, advice_type)
        scores.append(score)

    candidates = candidates.copy()
    candidates['_score'] = scores
    best = candidates.sort_values('_score', ascending=False).iloc[0]

    return best['name'], float(best['_score'])


def evaluate_animals(animals_df, settings, overrides=None):
    """
    Evalueer alle dieren en bepaal adviezen.

    Args:
        animals_df: DataFrame met dieren
        settings: dict met drempelwaarden
        overrides: dict met sessie-overrides

    Returns:
        dict {animal_id: advice_dict}
    """
    overrides = overrides or {}
    skip_animals = overrides.get('skip_animals', set())
    force_bulls = overrides.get('force_bulls', {})
    excluded_bulls = overrides.get('excluded_bulls', set())

    rules = build_rules_from_settings(settings)
    bulls_db = get_bulls_database()

    advice_result = {}

    for _, animal in animals_df.iterrows():
        animal_id = str(animal.get('animal_id', ''))
        animal_dict = animal.to_dict()

        # Skip als gevraagd
        if animal_id in skip_animals:
            advice_result[animal_id] = {
                'advice_type': 'overgeslagen',
                'recommended_bull': None,
                'confidence_score': 0.0,
                'explanation': 'Dier overgeslagen door gebruiker',
                'applied_rules': [],
            }
            continue

        # Bepaal adviestype
        advice_type, reason = determine_advice_type(animal_dict, rules)

        # Toegepaste regels voor uitleg
        applicable = get_applicable_rules(animal_dict, rules)
        applied_rule_reasons = [r['rule'].get('reason', '') for r in applicable]

        # Forceer stier als ingesteld
        if animal_id in force_bulls:
            bull_name = force_bulls[animal_id]
            confidence = 1.0
            explanation = f'Stier geforceerd door gebruiker: {bull_name}'
        else:
            bull_name, confidence = _find_best_bull(
                animal_dict, bulls_db, advice_type, excluded_bulls
            )
            explanation = reason if reason else f'Standaard advies: {advice_type}'

        advice_result[animal_id] = {
            'advice_type': advice_type,
            'recommended_bull': bull_name,
            'confidence_score': round(confidence, 2),
            'explanation': explanation,
            'applied_rules': applied_rule_reasons,
        }

    return advice_result
