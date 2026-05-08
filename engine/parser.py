"""
PDF-parsing module voor melkcontrole-rapporten.
Ondersteunt Nederlandse, Deense, Duitse en Belgische formaten.
"""
import io
import json
import re

import pandas as pd
import pdfplumber


COLUMN_ALIASES = {
    'animal_id': [
        'dier nr', 'diernr', 'dier_nr', 'animal id', 'animal_id',
        'dyr. nr.', 'dyr nr', 'id', 'levensnummer', 'oornummer',
        'koe nr', 'koenr', 'stalnum', 'stalnummer',
    ],
    'animal_name': [
        'naam', 'name', 'navn', 'tiername', 'koename',
        'animal name', 'animal_name',
    ],
    'lactation_number': [
        'lakt. nr.', 'lakt nr', 'lactatienummer', 'lactation number',
        'lakt.', 'ln', 'parity', 'pariteit', 'kalfsnum', 'kalving',
    ],
    'lactation_value': [
        'lakt. waarde', 'laktwaarde', 'lactatiewaarde', 'lactation value',
        'lakt. vardi', 'lakt. värd', 'lv', 'index', 'productie index',
        'melkindex', 'nvi', 'inet',
    ],
    'inseminations': [
        'inseminaties', 'ins', 'antal ins.', 'aantal ins', 'insem',
        'insemination', 'dekking', 'aantal dekkingen',
    ],
    'pregnant': [
        'drachtig', 'drägt.', 'pregnant', 'gravid', 'drächtig',
        'gust', 'status',
    ],
    'milk_yield': [
        'melk', 'melkgift', 'milk', 'mælk', 'milch', 'kg melk',
        'milk yield', 'melkproductie', '305d',
    ],
    'cell_count': [
        'celgetal', 'cel', 'scc', 'celfetal', 'celtal', 'somatic',
        'cell count', 'cellen', 'tankgetal',
    ],
    'protein': [
        'eiwit', 'eiwit %', 'protein', 'protein %', 'protein%',
        'proteine', 'eiwitgehalte',
    ],
    'fat': [
        'vet', 'vet %', 'fat', 'fedt %', 'fett', 'vetgehalte', 'fat%',
    ],
    'urea': [
        'ureum', 'urea', 'ure', 'urea mmol',
    ],
    'sire_name': [
        'vadernaam', 'vader', 'sire', 'far', 'vater', 'stier vader',
        'sire name', 'vadersnaam',
    ],
    'sire_code': [
        'vadercode', 'tyrkode', 'sire code', 'vader code', 'stierkode',
    ],
    'aaa_code': [
        'aaa', 'aaa code', 'aaa-code',
    ],
    'pfw': [
        'pfw', 'pfw code',
    ],
    'breed': [
        'ras', 'breed', 'race', 'rasse',
    ],
    'inbreeding_coefficient': [
        'inteelt', 'inbreeding', 'f%', 'inteeltcoefficient',
    ],
}


def _normalize(text):
    """Lowercase + strip voor fuzzy matching."""
    if not text:
        return ''
    return re.sub(r'\s+', ' ', str(text).lower().strip())


def _detect_column_mapping(headers):
    """
    Match kolomkoppen op bekende aliassen.
    Retourneert dict: standaard_veld -> originele kolomnaam.
    """
    mapping = {}
    normalized_headers = {_normalize(h): h for h in headers if h}

    for std_field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            norm_alias = _normalize(alias)
            if norm_alias in normalized_headers:
                mapping[std_field] = normalized_headers[norm_alias]
                break

    return mapping


def _extract_tables_from_pdf(pdf_file):
    """
    Extraheer alle tabellen uit de PDF met pdfplumber.
    Retourneert lijst van DataFrames (één per tabel).
    """
    tables = []

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_tables = page.extract_tables()
            for tbl in page_tables:
                if not tbl or len(tbl) < 2:
                    continue
                try:
                    df = pd.DataFrame(tbl[1:], columns=tbl[0])
                    df = df.dropna(how='all')
                    tables.append(df)
                except Exception:
                    continue

    return tables


def _merge_tables(tables):
    """
    Voeg tabellen samen als ze dezelfde kolommen hebben.
    Kies de grootste/beste tabel.
    """
    if not tables:
        return pd.DataFrame()

    # Sorteer op aantal rijen (meeste rijen = meest complete tabel)
    tables_sorted = sorted(tables, key=lambda df: len(df), reverse=True)

    best = tables_sorted[0]

    # Probeer tabellen met zelfde kolommen te stapelen
    for tbl in tables_sorted[1:]:
        if set(tbl.columns) == set(best.columns):
            best = pd.concat([best, tbl], ignore_index=True)

    return best


def _clean_numeric(series):
    """Schoon een series op voor numerieke waarden."""
    return pd.to_numeric(
        series.astype(str).str.replace(',', '.').str.extract(r'([\d.]+)')[0],
        errors='coerce'
    )


def _apply_mapping(df, mapping):
    """
    Maak een nieuwe DataFrame met gestandaardiseerde kolomnamen.
    """
    result = pd.DataFrame()

    for std_field, orig_col in mapping.items():
        if orig_col in df.columns:
            result[std_field] = df[orig_col]

    # Zorg dat verplichte velden bestaan
    required_fields = [
        'animal_id', 'lactation_number', 'lactation_value',
        'inseminations', 'cell_count',
    ]
    for field in required_fields:
        if field not in result.columns:
            result[field] = None

    # Numeriek omzetten
    numeric_fields = [
        'lactation_number', 'lactation_value', 'inseminations',
        'milk_yield', 'cell_count', 'protein', 'fat', 'urea',
        'inbreeding_coefficient',
    ]
    for field in numeric_fields:
        if field in result.columns:
            result[field] = _clean_numeric(result[field])

    # animal_id als string
    if 'animal_id' in result.columns:
        result['animal_id'] = result['animal_id'].astype(str).str.strip()

    # Verwijder lege rijen
    result = result.dropna(subset=['animal_id'])
    result = result[result['animal_id'].str.len() > 0]
    result = result[result['animal_id'] != 'nan']
    result = result.reset_index(drop=True)

    # Voeg ontbrekende kolommen toe met defaults
    defaults = {
        'animal_name': '',
        'lactation_number': 1,
        'lactation_value': 0.0,
        'inseminations': 0,
        'cell_count': 0,
        'pregnant': False,
        'milk_yield': 0.0,
        'protein': 0.0,
        'fat': 0.0,
        'urea': 0.0,
        'pfw': '',
        'aaa_code': '',
        'breed': 'Holstein',
        'sire_name': '',
        'sire_code': '',
        'inbreeding_coefficient': 0.0,
        'advisor_note': '',
    }
    for col, default in defaults.items():
        if col not in result.columns:
            result[col] = default

    # Fillna met defaults
    for col, default in defaults.items():
        if col in result.columns:
            result[col] = result[col].fillna(default)

    return result


def parse_pdf_and_detect_columns(pdf_file):
    """
    Hoofdfunctie: parse melkcontrole PDF en detecteer kolommen.

    Args:
        pdf_file: Bestandsobject (Streamlit UploadedFile of file path)

    Returns:
        Tuple (animals_df: DataFrame, column_mapping: dict)
    """
    # Reset bestandspositie als dat mogelijk is
    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)

    # Extraheer tabellen
    tables = _extract_tables_from_pdf(pdf_file)

    if not tables:
        # Geen tabellen gevonden: retourneer lege df met demo-data
        return _create_demo_dataframe(), {}

    # Kies beste tabel
    raw_df = _merge_tables(tables)

    if raw_df.empty:
        return _create_demo_dataframe(), {}

    # Detecteer kolomnamen
    headers = [str(c) for c in raw_df.columns]
    mapping = _detect_column_mapping(headers)

    if not mapping:
        # Geen mapping gevonden: gebruik positie-gebaseerde fallback
        mapping = _positional_mapping_fallback(headers)

    # Pas mapping toe
    animals_df = _apply_mapping(raw_df, mapping)

    return animals_df, mapping


def _positional_mapping_fallback(headers):
    """
    Als geen kolomnamen herkend worden, probeer positionele mapping.
    Vul de eerste paar kolommen in als animal_id, naam, etc.
    """
    mapping = {}
    field_order = [
        'animal_id', 'animal_name', 'lactation_number', 'lactation_value',
        'inseminations', 'cell_count', 'milk_yield', 'protein', 'fat',
    ]

    for i, field in enumerate(field_order):
        if i < len(headers) and headers[i]:
            mapping[field] = headers[i]

    return mapping


def _create_demo_dataframe():
    """
    Maak een demo-DataFrame als er geen PDF-data is.
    """
    data = {
        'animal_id': ['NL123456789', 'NL987654321', 'NL111222333', 'NL444555666'],
        'animal_name': ['Bella', 'Rosa', 'Mia', 'Lola'],
        'lactation_number': [1, 3, 2, 1],
        'lactation_value': [89.0, 95.0, 110.0, 78.0],
        'inseminations': [2, 4, 1, 1],
        'cell_count': [180, 320, 95, 150],
        'milk_yield': [7200.0, 9500.0, 11000.0, 6800.0],
        'protein': [3.4, 3.5, 3.6, 3.3],
        'fat': [4.1, 4.0, 4.2, 4.3],
        'urea': [24, 28, 22, 26],
        'pfw': ['203', '312', '421', '103'],
        'aaa_code': ['ABC', 'BCE', 'ACE', 'BCD'],
        'breed': ['Holstein', 'Holstein', 'Holstein', 'Holstein'],
        'sire_name': ['Topnotch', 'Altaspring', 'Goldwyn', 'Ranger'],
        'sire_code': ['NL9012', 'US5678', 'CA3456', 'BE7890'],
        'inbreeding_coefficient': [6.5, 8.2, 5.1, 11.0],
        'advisor_note': ['', '', '', ''],
        'pregnant': [False, True, False, False],
    }
    return pd.DataFrame(data)
