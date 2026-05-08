"""
Advies-engine: evalueert dieren volgens vaste controleerbare regelset.

Volgorde per dier:
  1. Uitsluitingen dier (status)
  2. Datakwaliteitscontrole
  3. Bepaal adviesrichting (BWB of fokstier)
  4. Filter stieren op selectie + categorie
  5. Harde uitsluitingen per stier (beschikbaarheid, vaars, inteelt)
  6. Scoreberekening per overgebleven stier
  7. Kies beste stier
  8. Stel adviesresultaat samen met alle redenen en waarschuwingen
"""
import math

import pandas as pd

from engine.bulls_loader import filter_bulls_by_names, load_bulls_from_csv
from engine.rule_builder import (
    build_rules_from_settings,
    check_data_quality,
    get_all_bwb_reasons,
    get_data_warnings,
)

# ── Constanten ────────────────────────────────────────────────────────────────
BASE_SCORE = 100
MIN_CALF_EASE_HEIFER = 9500   # Onder deze waarde: uitgesloten voor vaarzen (10000-schaal)
INDEX_AVERAGE = 10000.0       # 10000 = rasgemiddeld op 10000-schaal


# ── Inteeltcontrole ───────────────────────────────────────────────────────────

def _check_inbreeding(animal: dict, bull: pd.Series, inbreed_threshold: float) -> dict:
    """
    Controleer inteeltrisico tussen dier en stier.

    Retourneert:
        {
            'hard_exclusion': bool,
            'exclusion_reason': str | None,
            'warning': str | None,
            'score_penalty': int,   # 0-100
        }
    """
    result = {'hard_exclusion': False, 'exclusion_reason': None, 'warning': None, 'score_penalty': 0}

    animal_sire = str(animal.get('sire_name', '') or '').strip().lower()
    animal_sire_code = str(animal.get('sire_code', '') or '').strip()
    bull_name = str(bull.get('name', '') or '').strip().lower()
    bull_code = str(bull.get('stier_code', '') or '').strip()
    bull_sire = str(bull.get('sire_name', '') or '').strip().lower()

    # Harde uitsluiting: stier IS de vader van dit dier
    if animal_sire and bull_name and animal_sire == bull_name:
        result['hard_exclusion'] = True
        result['exclusion_reason'] = f'Stier is de vader van dit dier.'
        return result

    # Harde uitsluiting: stiercode klopt overeen met vadercode
    if (animal_sire_code and bull_code and
            animal_sire_code != 'nan' and bull_code != 'nan' and
            animal_sire_code == bull_code):
        result['hard_exclusion'] = True
        result['exclusion_reason'] = 'Stier heeft dezelfde code als de vader van dit dier.'
        return result

    # Waarschuwing: gedeelde vaderlijn (dier en stier hebben dezelfde vader)
    if animal_sire and bull_sire and animal_sire != 'nan' and bull_sire != 'nan':
        if animal_sire == bull_sire:
            result['warning'] = f'Gedeelde vaderlijn: beide hebben vader "{bull_sire}".'
            result['score_penalty'] = 25

    # Controleer eigen inteeltcoëfficiënt van het dier als proxy
    animal_inbreeding = animal.get('inbreeding_coefficient', 0.0)
    try:
        animal_inbreeding = float(animal_inbreeding)
    except (TypeError, ValueError):
        animal_inbreeding = 0.0

    if animal_inbreeding > inbreed_threshold:
        # Al hoog inteeltpercentage → extra voorzichtig
        result['score_penalty'] = max(result['score_penalty'], 30)
        if not result['warning']:
            result['warning'] = (
                f'Dier heeft al een inteeltpercentage van {animal_inbreeding:.1f}% '
                f'(grens: {inbreed_threshold}%).'
            )
    elif animal_inbreeding > inbreed_threshold * 0.75:
        result['score_penalty'] = max(result['score_penalty'], 10)

    # Stamboomdata ontbreekt
    if not animal_sire or animal_sire == 'nan':
        if not result['warning']:
            result['warning'] = 'Inteeltcontrole beperkt: vadernaam dier ontbreekt.'

    return result


# ── aAa matching ──────────────────────────────────────────────────────────────

def _parse_aaa(code: str) -> list[str]:
    """Normaliseer aAa-code naar lijst van karakters/cijfers."""
    if not code or str(code).strip() in ('', 'nan', 'None'):
        return []
    code = str(code).strip().replace('-', '').replace(' ', '')
    return list(code)


def _score_aaa_match(animal_aaa: str, bull_aaa: str) -> int:
    """Score aAa-match. Retourneert 0-20 punten."""
    animal_chars = _parse_aaa(animal_aaa)
    bull_chars = _parse_aaa(bull_aaa)
    if not animal_chars or not bull_chars:
        return 0
    # Prioriteit: eerste 2 posities van de dier-aAa zijn het belangrijkst
    matches = sum(1 for c in animal_chars[:3] if c in bull_chars[:3])
    return min(20, matches * 7)


# ── PFW matching ──────────────────────────────────────────────────────────────

def _score_pfw_match(animal_pfw: str, bull_pfw: str) -> int:
    """Score PFW-match. Retourneert 0-20 punten."""
    if not animal_pfw or not bull_pfw:
        return 0
    ap = str(animal_pfw).strip()
    bp = str(bull_pfw).strip()
    if ap in ('nan', 'None', '') or bp in ('nan', 'None', ''):
        return 0
    # Eenvoudige match: zelfde eerste cijfer
    if ap and bp and ap[0] == bp[0]:
        return 10
    return 0


# ── Index-scores ──────────────────────────────────────────────────────────────

def _index_bonus(value, target: float = INDEX_AVERAGE, max_bonus: int = 15) -> int:
    """
    Bereken bonus op basis van index ten opzichte van rasgemiddelde.
    Waarden boven INDEX_AVERAGE geven punten (max max_bonus).
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return 0
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0
    delta = v - target
    if delta <= 0:
        return 0
    return min(max_bonus, int(delta / 100))


# ── Score-BWB ────────────────────────────────────────────────────────────────

def _score_bwb_bull(animal: dict, bull: pd.Series, excluded_bulls: set) -> tuple[int, str | None]:
    """
    Score een BWB-stier voor dit dier.
    Retourneert (score: int, exclusion_reason: str | None).
    Score 0 + exclusion_reason = harde uitsluiting.
    """
    is_heifer = _is_heifer(animal)

    # Harde uitsluitingen
    if str(bull.get('name', '')) in excluded_bulls:
        return 0, 'Uitgesloten door gebruiker.'

    if not bull.get('available', True):
        return 0, 'Stier niet beschikbaar.'

    if bull.get('category') != 'belgian_witblauw':
        return 0, 'Geen BWB-stier.'

    if is_heifer and not bull.get('suitable_for_heifers', False):
        return 0, 'Niet geschikt voor gebruik op vaarzen.'

    calf_ease = _safe_float(bull.get('calf_ease'), 9800)
    if is_heifer and calf_ease < MIN_CALF_EASE_HEIFER:
        return 0, f'Geboortegemak te laag voor vaars (index: {calf_ease:.0f}, minimum: {MIN_CALF_EASE_HEIFER}).'

    # Scoreberekening
    score = BASE_SCORE

    # Kalfgemak (zwaarder voor vaarzen)
    if is_heifer:
        if calf_ease >= 10400:
            score += 20
        elif calf_ease >= 10200:
            score += 12
        elif calf_ease >= 10000:
            score += 6
    else:
        if calf_ease >= 10000:
            score += 5

    # Voorkeur zuiver BWB boven kruising
    if str(bull.get('bwb_type', '')).lower() == 'zuiver':
        score += 5

    # Pinkenstier-bonus als het een vaars is
    if is_heifer and bull.get('suitable_for_heifers', False):
        score += 5

    return score, None


# ── Score-fokstier ────────────────────────────────────────────────────────────

def _score_fokstier_bull(
    animal: dict,
    bull: pd.Series,
    excluded_bulls: set,
    inbreed_threshold: float,
    breeding_goals: list[str],
) -> tuple[int, str | None, str | None]:
    """
    Score een fokstier voor dit dier.
    Retourneert (score: int, exclusion_reason: str | None, warning: str | None).
    """
    is_heifer = _is_heifer(animal)
    bull_name = str(bull.get('name', ''))

    # ── Harde uitsluitingen ──
    if bull_name in excluded_bulls:
        return 0, 'Uitgesloten door gebruiker.', None

    if not bull.get('available', True):
        return 0, 'Stier niet beschikbaar.', None

    if bull.get('category') not in ('milking_sire', 'genetic_merit'):
        return 0, 'Geen fokstier.', None

    if is_heifer and not bull.get('suitable_for_heifers', False):
        return 0, 'Niet geschikt voor gebruik op vaarzen.', None

    calf_ease = _safe_float(bull.get('calf_ease'), 9800)
    if is_heifer and calf_ease < MIN_CALF_EASE_HEIFER:
        return 0, f'Geboortegemak te laag voor vaars (index: {calf_ease:.0f}).', None

    # ── Inteeltcontrole ──
    inbreed = _check_inbreeding(animal, bull, inbreed_threshold)
    if inbreed['hard_exclusion']:
        return 0, inbreed['exclusion_reason'], None

    # ── Scoreberekening ──
    score = BASE_SCORE
    warning = inbreed.get('warning')

    # Inteelt-aftrek
    score -= inbreed['score_penalty']

    # NVI bonus (positief = beter dan rasgemiddeld)
    nvi = _safe_float(bull.get('nvi'), None)
    if nvi is not None:
        if nvi > 200:
            score += 15
        elif nvi > 100:
            score += 10
        elif nvi > 0:
            score += 5
        elif nvi < -200:
            score -= 10
        elif nvi < 0:
            score -= 5

    # Kalfgemak voor vaarzen
    if is_heifer:
        if calf_ease >= 10400:
            score += 15
        elif calf_ease >= 10200:
            score += 8
        elif calf_ease >= 10000:
            score += 3

    # aAa-match
    animal_aaa = str(animal.get('aaa_code', '') or '')
    bull_aaa = str(bull.get('aaa_code', '') or '')
    score += _score_aaa_match(animal_aaa, bull_aaa)

    # PFW-match
    animal_pfw = str(animal.get('pfw', '') or '')
    bull_pfw = str(bull.get('pfw_code', '') or '')
    score += _score_pfw_match(animal_pfw, bull_pfw)

    # Kappa-caseïne BB
    if str(bull.get('kappa_casein', '')).upper() == 'BB':
        score += 5

    # Beta-caseïne A2A2
    if str(bull.get('beta_casein', '')).upper() in ('A2/A2', 'A2A2'):
        score += 5

    # Fokdoel-bonussen
    for goal in breeding_goals:
        score += _breeding_goal_bonus(bull, goal)

    return max(0, score), None, warning


def _breeding_goal_bonus(bull: pd.Series, goal: str) -> int:
    """Geef bonus op basis van fokdoel en beschikbare stierindices."""
    goal_l = goal.lower()

    if 'uier' in goal_l:
        bonus = _index_bonus(bull.get('udder_index'), max_bonus=15)
        bonus += _index_bonus(bull.get('udder_health'), max_bonus=10)
        bonus += _index_bonus(bull.get('somatic_cell'), max_bonus=5)
        return min(25, bonus)

    if 'benen' in goal_l or 'klau' in goal_l:
        bonus = _index_bonus(bull.get('leg_index'), max_bonus=15)
        bonus += _index_bonus(bull.get('claw_health'), max_bonus=10)
        return min(25, bonus)

    if 'levensduur' in goal_l or 'duurzaam' in goal_l:
        return min(20, _index_bonus(bull.get('longevity'), max_bonus=20))

    if 'vrucht' in goal_l or 'fertilit' in goal_l:
        return min(15, _index_bonus(bull.get('fertility'), max_bonus=15))

    if 'robot' in goal_l:
        return min(15, _index_bonus(bull.get('robot_efficiency'), max_bonus=15))

    if 'melk' in goal_l or 'productie' in goal_l:
        return min(15, _index_bonus(bull.get('nvi'), target=0, max_bonus=15))

    return 0


# ── Hulpfuncties ──────────────────────────────────────────────────────────────

def _is_heifer(animal: dict) -> bool:
    try:
        return float(animal.get('lactation_number', 2)) == 1
    except (TypeError, ValueError):
        return False


def _safe_float(value, default):
    if value is None:
        return default
    try:
        f = float(value)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def _build_explanation(reasons: list[str], warnings: list[str], bull_name: str | None) -> str:
    """Stel een leesbare uitleg samen voor in het rapport."""
    parts = []
    if reasons:
        parts.append('Redenen: ' + '; '.join(reasons))
    if bull_name:
        parts.append(f'Aanbevolen stier: {bull_name}')
    if warnings:
        parts.append('Waarschuwingen: ' + '; '.join(warnings))
    return ' | '.join(parts) if parts else 'Geen informatie beschikbaar.'


# ── Hoofd-evaluatiefunctie ────────────────────────────────────────────────────

def evaluate_animals(
    animals_df: pd.DataFrame,
    settings: dict,
    overrides: dict | None = None,
) -> dict:
    """
    Evalueer alle dieren en genereer controleerbare adviezen.

    Returns:
        dict {animal_id: advice_dict}

    advice_dict bevat:
        advice_type: str
        recommended_bull: str | None
        confidence_score: float (0.0-1.0)
        reasons: list[str]
        warnings: list[str]
        data_quality: dict
        bull_scores: dict  (naam -> score, voor transparantie)
        excluded_bulls_detail: dict  (naam -> reden)
        explanation: str  (samenvatting voor rapport)
        applied_rules: list[str]  (backwards compat)
    """
    overrides = overrides or {}
    skip_animals = overrides.get('skip_animals', set())
    force_bulls = overrides.get('force_bulls', {})
    excluded_bulls = overrides.get('excluded_bulls', set())
    selected_bulls = list(overrides.get('selected_bulls', []))
    breeding_goals = _parse_breeding_goals(settings.get('custom_requests', ''))
    inbreed_threshold = settings.get('inbreeding_threshold', 12.5)

    rules = build_rules_from_settings(settings)

    all_bulls = load_bulls_from_csv()
    if selected_bulls:
        all_bulls = filter_bulls_by_names(all_bulls, selected_bulls)

    advice_result = {}

    for _, animal in animals_df.iterrows():
        animal_id = str(animal.get('animal_id', ''))
        animal_dict = animal.to_dict()

        # ── Stap 1: dier-uitsluitingen ────────────────────────────────────
        if animal_id in skip_animals:
            advice_result[animal_id] = _make_advice(
                'geen_advies', None, 0.0, [], [],
                explanation='Dier overgeslagen door gebruiker.',
            )
            continue

        status = str(animal_dict.get('pregnant', '') or '').lower()
        if status in ('true', '1', 'drachtig', 'ja'):
            advice_result[animal_id] = _make_advice(
                'geen_advies', None, 0.0, [],
                ['Dier is drachtig.'],
                explanation='Geen advies: dier is drachtig.',
            )
            continue

        # ── Stap 2: datakwaliteit ─────────────────────────────────────────
        quality = check_data_quality(animal_dict)
        data_warnings = get_data_warnings(quality)

        # Alleen lactatiewaarde + lactatienummer zijn kritiek;
        # inseminaties None wordt behandeld als 0 (DMS-formaat laat 0 weg)
        missing_critical = any(
            quality.get(f) == 'missing'
            for f in ('lactation_value', 'lactation_number')
        )
        if missing_critical:
            advice_result[animal_id] = _make_advice(
                'onvoldoende_data', None, 0.0, [],
                data_warnings,
                data_quality=quality,
                explanation='Geen definitief advies: essentiële gegevens ontbreken.',
            )
            continue

        # ── Stap 3: adviesrichting bepalen ────────────────────────────────
        bwb_reasons = get_all_bwb_reasons(animal_dict, rules)
        is_bwb = len(bwb_reasons) > 0

        # ── Geforceerde stier (chat/gebruiker) ────────────────────────────
        if animal_id in force_bulls:
            bull_name = force_bulls[animal_id]
            advice_type = 'belgian_witblauw' if is_bwb else 'fokstier'
            reasons = bwb_reasons if is_bwb else ['Dier voldoet aan fokstieradvies.']
            reasons.append(f'Stier handmatig ingesteld: {bull_name}.')
            advice_result[animal_id] = _make_advice(
                advice_type, bull_name, 1.0, reasons, data_warnings,
                data_quality=quality,
            )
            continue

        # ── Stap 4-8: stier selecteren ────────────────────────────────────
        if is_bwb:
            advice = _select_bwb_bull(
                animal_dict, all_bulls, excluded_bulls, bwb_reasons,
                data_warnings, quality,
            )
        else:
            fokstier_reasons = [
                'Dier voldoet niet aan de Belgisch Witblauw-regels.',
                'Dier is geschikt voor een fokstieradvies.',
            ]
            advice = _select_fokstier_bull(
                animal_dict, all_bulls, excluded_bulls, fokstier_reasons,
                data_warnings, quality, inbreed_threshold, breeding_goals,
            )

        advice_result[animal_id] = advice

    return advice_result


def _select_bwb_bull(animal, bulls, excluded_bulls, reasons, data_warnings, quality):
    bwb_bulls = bulls[bulls['category'] == 'belgian_witblauw'].copy()

    if bwb_bulls.empty:
        return _make_advice(
            'belgian_witblauw', None, 0.0, reasons,
            data_warnings + ['Geen passend advies: geen geselecteerde BWB-stier beschikbaar.'],
            data_quality=quality,
        )

    scored = []
    excluded_detail = {}
    for _, bull in bwb_bulls.iterrows():
        score, excl_reason = _score_bwb_bull(animal, bull, excluded_bulls)
        if excl_reason:
            excluded_detail[str(bull['name'])] = excl_reason
        else:
            scored.append((bull, score))

    if not scored:
        return _make_advice(
            'belgian_witblauw', None, 0.0, reasons,
            data_warnings + ['Geen passende BWB-stier: alle stieren uitgesloten.'],
            excluded_bulls_detail=excluded_detail,
            data_quality=quality,
        )

    best_bull, best_score = max(scored, key=lambda x: x[1])
    bull_name = str(best_bull['name'])

    is_heifer = _is_heifer(animal)
    extra_reasons = []
    if is_heifer and best_bull.get('suitable_for_heifers', False):
        extra_reasons.append('Stier is geschikt voor gebruik op vaarzen.')
    calf_ease = _safe_float(best_bull.get('calf_ease'), 9800)
    if calf_ease >= 10000:
        extra_reasons.append(f'Goed geboortegemak (index: {calf_ease:.0f}).')

    return _make_advice(
        'belgian_witblauw', bull_name,
        min(1.0, best_score / 130),
        reasons + extra_reasons, data_warnings,
        excluded_bulls_detail=excluded_detail,
        data_quality=quality,
        bull_scores={str(b['name']): s for b, s in scored},
    )


def _select_fokstier_bull(
    animal, bulls, excluded_bulls, reasons, data_warnings,
    quality, inbreed_threshold, breeding_goals,
):
    fokstier_bulls = bulls[bulls['category'].isin(['milking_sire', 'genetic_merit'])].copy()

    if fokstier_bulls.empty:
        return _make_advice(
            'fokstier', None, 0.0, reasons,
            data_warnings + ['Geen passend advies: geen geselecteerde fokstier beschikbaar.'],
            data_quality=quality,
        )

    scored = []
    excluded_detail = {}
    all_warnings = list(data_warnings)

    for _, bull in fokstier_bulls.iterrows():
        score, excl_reason, warn = _score_fokstier_bull(
            animal, bull, excluded_bulls, inbreed_threshold, breeding_goals
        )
        if excl_reason:
            excluded_detail[str(bull['name'])] = excl_reason
        else:
            if warn and warn not in all_warnings:
                all_warnings.append(warn)
            scored.append((bull, score))

    if not scored:
        return _make_advice(
            'fokstier', None, 0.0, reasons,
            all_warnings + ['Geen passende fokstier: alle stieren uitgesloten door inteelt of andere uitsluitingsregel.'],
            excluded_bulls_detail=excluded_detail,
            data_quality=quality,
        )

    best_bull, best_score = max(scored, key=lambda x: x[1])
    bull_name = str(best_bull['name'])

    extra_reasons = _build_fokstier_choice_reasons(animal, best_bull, breeding_goals)

    return _make_advice(
        'fokstier', bull_name,
        min(1.0, best_score / 170),
        reasons + extra_reasons, all_warnings,
        excluded_bulls_detail=excluded_detail,
        data_quality=quality,
        bull_scores={str(b['name']): s for b, s in sorted(scored, key=lambda x: -x[1])[:10]},
    )


def _build_fokstier_choice_reasons(animal: dict, bull: pd.Series, breeding_goals: list[str]) -> list[str]:
    reasons = []

    animal_aaa = str(animal.get('aaa_code', '') or '')
    bull_aaa = str(bull.get('aaa_code', '') or '')
    if _score_aaa_match(animal_aaa, bull_aaa) > 0:
        reasons.append(f'Goede aAa-match (dier: {animal_aaa}, stier: {bull_aaa}).')

    animal_pfw = str(animal.get('pfw', '') or '')
    bull_pfw = str(bull.get('pfw_code', '') or '')
    if _score_pfw_match(animal_pfw, bull_pfw) > 0:
        reasons.append(f'PFW-code sluit aan (dier: {animal_pfw}, stier: {bull_pfw}).')

    nvi = _safe_float(bull.get('nvi'), None)
    if nvi is not None and nvi > 0:
        reasons.append(f'NVI boven rasgemiddeld: {nvi:.0f}.')

    if breeding_goals:
        goals_str = ', '.join(breeding_goals[:3])
        reasons.append(f'Past bij fokdoel: {goals_str}.')

    if str(bull.get('kappa_casein', '')).upper() == 'BB':
        reasons.append('Kappa-caseïne BB.')

    return reasons


def _parse_breeding_goals(custom_requests: str) -> list[str]:
    """Extraheer fokdoelen uit vrije tekst."""
    if not custom_requests:
        return []
    keywords = ['uier', 'benen', 'klauwen', 'levensduur', 'vruchtbaarheid',
                'robot', 'melkproductie', 'gehalten', 'duurzaamheid']
    found = []
    text = custom_requests.lower()
    for kw in keywords:
        if kw in text:
            found.append(kw)
    return found


def _make_advice(
    advice_type: str,
    recommended_bull: str | None,
    confidence_score: float,
    reasons: list[str],
    warnings: list[str],
    data_quality: dict | None = None,
    bull_scores: dict | None = None,
    excluded_bulls_detail: dict | None = None,
    explanation: str | None = None,
) -> dict:
    if explanation is None:
        explanation = _build_explanation(reasons, warnings, recommended_bull)
    return {
        'advice_type': advice_type,
        'recommended_bull': recommended_bull,
        'confidence_score': round(confidence_score, 2),
        'reasons': reasons,
        'warnings': warnings,
        'data_quality': data_quality or {},
        'bull_scores': bull_scores or {},
        'excluded_bulls_detail': excluded_bulls_detail or {},
        'explanation': explanation,
        'applied_rules': reasons,  # backwards compat
    }
