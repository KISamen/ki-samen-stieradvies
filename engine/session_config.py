"""
Sessie-management voor Streamlit session_state.
"""
import uuid
from datetime import datetime

import streamlit as st


DEFAULT_SETTINGS = {
    'vaars_lactation_threshold': 92,
    'koe_lactation_threshold': 98,
    'insemination_threshold': 3,
    'cell_count_threshold': 300,
    'inbreeding_threshold': 12.5,
    'custom_requests': '',
    'set_at': None,
}

DEFAULT_OVERRIDES = {
    'skip_animals': set(),
    'force_bulls': {},
    'excluded_bulls': set(),
    'excluded_breeders': set(),
    'threshold_adjustments': {},
}

DEFAULT_REPORT_SETTINGS = {
    'title': 'Stieradvies',
    'logo_path': None,
    'footer_text': '',
    'brand_colors': {},
}


def init_session_state():
    """Initialiseer alle session state variabelen als ze nog niet bestaan."""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())

    if 'created_at' not in st.session_state:
        st.session_state.created_at = datetime.now()

    if 'animals_df' not in st.session_state:
        st.session_state.animals_df = None

    if 'column_mapping' not in st.session_state:
        st.session_state.column_mapping = {}

    if 'advice_result' not in st.session_state:
        st.session_state.advice_result = {}

    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []

    if 'session_rules' not in st.session_state:
        st.session_state.session_rules = []

    if 'overrides' not in st.session_state:
        st.session_state.overrides = dict(DEFAULT_OVERRIDES)

    if 'report_settings' not in st.session_state:
        st.session_state.report_settings = dict(DEFAULT_REPORT_SETTINGS)

    if 'default_settings' not in st.session_state:
        st.session_state.default_settings = dict(DEFAULT_SETTINGS)

    if 'company_name' not in st.session_state:
        st.session_state.company_name = 'Mijn Bedrijf'


def get_effective_settings():
    """Retourneer de huidige instellingen uit session state."""
    return st.session_state.default_settings


def apply_threshold_override(field, value):
    """Pas een drempelwaarde aan in sessie-settings."""
    field_map = {
        'cell_count': 'cell_count_threshold',
        'inseminations': 'insemination_threshold',
        'lactation_value': 'koe_lactation_threshold',
        'inbreeding_coefficient': 'inbreeding_threshold',
        'cell_count_threshold': 'cell_count_threshold',
        'insemination_threshold': 'insemination_threshold',
        'koe_lactation_threshold': 'koe_lactation_threshold',
        'vaars_lactation_threshold': 'vaars_lactation_threshold',
        'inbreeding_threshold': 'inbreeding_threshold',
    }

    settings_key = field_map.get(field, field)
    if settings_key in st.session_state.default_settings:
        st.session_state.default_settings[settings_key] = value
        return True
    return False
