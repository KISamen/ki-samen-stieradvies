"""
Advies-engine: evalueert dieren op basis van regelset en stiert-matching.
"""
import pandas as pd

from engine.bulls_loader import filter_bulls_by_names, load_bulls_from_csv
from engine.rule_builder import build_rules_from_settings, determine_advice_type, get_applicable_rules


def get_bulls_database(selected_bulls: list[str] | None = None) -> pd.DataFrame:
    """
    Laad actieve stieren uit CSV en filter op eigen selectie als opgegeven.
    """
    bulls_df = load_bulls_from_csv()
    if selected_bulls:
        bulls_df = filter_bulls_by_names(bulls_df, selected_bulls)
    return bulls_df


def _score_bull(animal_data: dict, bull: pd.Series, advice_type: str) -> float:
    """Score een stier voor een dier. Retourneert float 0.0–1.0."""
    score = 0.5

    category = str(bull.get('category', '')).lower()

    if advice_type == 'belgian_witblauw' and category == 'belgian_witblauw':
        score += 0.30
    elif advice_type in ('milking_sire', 'genetic_merit') and category in ('milking_sire', 'genetic_merit'):
        score += 0.20

    # NVI bonus voor fokstieren (schaal: positief = beter dan rasgemiddeld)
    nvi = bull.get('nvi')
    if pd.notna(nvi):
        try:
            nvi = float(nvi)
            if nvi > 100:
                score += 0.10
            elif nvi > 0:
                score += 0.05
        except (TypeError, ValueError):
            pass

    # Geboortegemak voor vaarzen (schaal: 10000 = rasgemiddeld)
    lactation_number = animal_data.get('lactation_number', 2)
    try:
        lactation_number = float(lactation_number)
    except (TypeError, ValueError):
        lactation_number = 2

    if lactation_number == 1 or bull.get('suitable_for_heifers', False):
        calf_ease = bull.get('calf_ease', 9800)
        try:
            calf_ease = float(calf_ease)
            if calf_ease >= 10200:
                score += 0.15
            elif calf_ease >= 10000:
                score += 0.08
            elif calf_ease >= 9800:
                score += 0.03
        except (TypeError, ValueError):
            pass

    # Kappa-caseïne BB bonus
    if str(bull.get('kappa_casein', '')).upper() == 'BB':
        score += 0.05

    return min(1.0, score)


def _find_best_bull(
    animal_data: dict,
    bulls_df: pd.DataFrame,
    advice_type: str,
    excluded_bulls: set | None = None,
) -> tuple[str | None, float]:
    """Vind de beste stier voor dit dier en adviestype."""
    if bulls_df.empty:
        return None, 0.0

    excluded_bulls = excluded_bulls or set()

    type_map = {
        'belgian_witblauw': ['belgian_witblauw'],
        'milking_sire': ['milking_sire', 'genetic_merit'],
        'genetic_merit': ['genetic_merit', 'milking_sire'],
    }
    allowed = type_map.get(advice_type, ['genetic_merit'])

    candidates = bulls_df[bulls_df['category'].isin(allowed)].copy()
    candidates = candidates[~candidates['name'].isin(excluded_bulls)]

    # Fallback: als geen match op categorie, gebruik alle niet-uitgesloten
    if candidates.empty:
        candidates = bulls_df[~bulls_df['name'].isin(excluded_bulls)].copy()

    if candidates.empty:
        return None, 0.0

    scores = [_score_bull(animal_data, bull, advice_type) for _, bull in candidates.iterrows()]
    candidates = candidates.copy()
    candidates['_score'] = scores
    best = candidates.sort_values('_score', ascending=False).iloc[0]

    return str(best['name']), float(best['_score'])


def evaluate_animals(
    animals_df: pd.DataFrame,
    settings: dict,
    overrides: dict | None = None,
) -> dict:
    """
    Evalueer alle dieren en bepaal adviezen.

    Args:
        animals_df: DataFrame met dieren
        settings: dict met drempelwaarden
        overrides: dict met sessie-overrides (skip_animals, force_bulls,
                   excluded_bulls, selected_bulls)

    Returns:
        dict {animal_id: advice_dict}
    """
    overrides = overrides or {}
    skip_animals = overrides.get('skip_animals', set())
    force_bulls = overrides.get('force_bulls', {})
    excluded_bulls = overrides.get('excluded_bulls', set())
    selected_bulls = list(overrides.get('selected_bulls', []))

    rules = build_rules_from_settings(settings)
    bulls_db = get_bulls_database(selected_bulls if selected_bulls else None)

    advice_result = {}

    for _, animal in animals_df.iterrows():
        animal_id = str(animal.get('animal_id', ''))
        animal_dict = animal.to_dict()

        if animal_id in skip_animals:
            advice_result[animal_id] = {
                'advice_type': 'overgeslagen',
                'recommended_bull': None,
                'confidence_score': 0.0,
                'explanation': 'Dier overgeslagen door gebruiker',
                'applied_rules': [],
            }
            continue

        advice_type, reason = determine_advice_type(animal_dict, rules)
        applicable = get_applicable_rules(animal_dict, rules)
        applied_rule_reasons = [r['rule'].get('reason', '') for r in applicable]

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
