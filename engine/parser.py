"""
PDF-parsing module voor melkcontrole-rapporten.
Ondersteunt CRV (NL), DMS (DK), DE en BE formaten.
"""
import re

import pandas as pd
import pdfplumber


# ── Kolomaliassen (tabel-gebaseerde PDFs) ─────────────────────────────────────
COLUMN_ALIASES = {
    'animal_id': [
        'dier nr', 'diernr', 'dier_nr', 'animal id', 'animal_id',
        'dyr. nr.', 'dyr nr', 'id', 'levensnummer', 'oornummer',
        'koe nr', 'koenr', 'stalnum', 'stalnummer', 'nr', 'koenummer',
        'life number', 'reg. no', 'reg.no', 'koe', 'koenr.',
    ],
    'animal_name': [
        'naam', 'name', 'navn', 'tiername', 'koename',
        'animal name', 'animal_name', 'roepnaam',
    ],
    'lactation_number': [
        'lakt. nr.', 'lakt nr', 'lactatienummer', 'lactation number',
        'lakt.', 'lakt', 'ln', 'parity', 'pariteit', 'kalfsnum',
        'kalving', 'lact', 'lact.', 'lactatie', 'lact.nr.', 'lact.nr',
        'lak', 'lak.', 'lakt.nr.', 'lakt. nr',
    ],
    'lactation_value': [
        'lakt. waarde', 'laktwaarde', 'lactatiewaarde', 'lactation value',
        'lakt. vardi', 'lakt. värd', 'lv', 'index', 'productie index',
        'melkindex', 'nvi', 'inet', 'lw', 'lakt.w.', 'lakt.w',
        'laktw', 'lakt. w.', 'lakt.waarde', 'l.w.', 'lw.',
        'lakt. værdi', 'laktationsværdi', 'lakt.værdi',
    ],
    'inseminations': [
        'inseminaties', 'ins', 'antal ins.', 'aantal ins', 'insem',
        'insemination', 'dekking', 'aantal dekkingen', 'ins.', 'ins.',
        'ins.nr', 'insem.', 'dekk.', 'di', 'aantal ins.', 'antal ins',
    ],
    'pregnant': [
        'drachtig', 'drägt.', 'pregnant', 'gravid', 'drächtig',
        'gust', 'status', 'dr.',
    ],
    'milk_yield': [
        'melk', 'melkgift', 'milk', 'mælk', 'milch', 'kg melk',
        'milk yield', 'melkproductie', '305d', 'melk kg', 'melk(kg)',
        'kg', 'melkg', 'melk305', 'kg.', 'kg. i',
    ],
    'cell_count': [
        'celgetal', 'cel', 'scc', 'celfetal', 'celtal', 'somatic',
        'cell count', 'cellen', 'tankgetal', 'celg', 'celg.', 'cg',
        'cel.getal', 'celget.', 's.12 mdr.', 's.12mdr', 'somatisk',
    ],
    'protein': [
        'eiwit', 'eiwit %', 'protein', 'protein %', 'protein%',
        'proteine', 'eiwitgehalte', 'eiw', 'eiw.', 'eiw%', 'eiw. %',
        'prot.', 'prot', 'proteinprocent',
    ],
    'fat': [
        'vet', 'vet %', 'fat', 'fedt %', 'fett', 'vetgehalte', 'fat%',
        'vet%', 'vet.', 'vg', 'v%', 'fedt', 'fedtprocent',
    ],
    'urea': ['ureum', 'urea', 'ure', 'urea mmol', 'ur'],
    'sire_name': [
        'vadernaam', 'vader', 'sire', 'far', 'vater', 'stier vader',
        'sire name', 'vadersnaam', 'v.naam', 'va', 'vad.', 'morfar',
    ],
    'sire_code': ['vadercode', 'tyrkode', 'sire code', 'vader code'],
    'aaa_code': ['aaa', 'aaa code', 'aaa-code', 'aaa_code'],
    'pfw': ['pfw', 'pfw code', 'pfw-code'],
    'breed': ['ras', 'breed', 'race', 'rasse'],
    'inbreeding_coefficient': [
        'inteelt', 'inbreeding', 'f%', 'inteeltcoefficient',
        'int.', 'int%', 'inteelt%', 'f %',
    ],
}

# ── DMS Deens Min-Liste formaat ───────────────────────────────────────────────
# Kolomvolgorde (na Dyr. Nr.):
#   0: Lakt. værdi   1: Lakt. nr.   2: Antal ins.   3: Dg.e.kælv.
#   4: Dg.e.Drægt.  5: Kg.i         6: S.12 mdr.    7: Fedt    8: Prot.
#   9+: Morfar (naam)

_DMS_DETECT = re.compile(r'dms\s+min|antal\s+dyr\s*:|dyr\.\s*nr\.|besætning', re.I)
_DMS_DATA_ROW = re.compile(
    r'^(DK[\d\s]{6,16}|\d{5,15})\s+'   # Dier-ID
    r'(-?\d+)\s+'                        # Lakt. værdi
    r'(\d+)\s+'                          # Lakt. nr.
    r'(\d+)\s+'                          # Antal ins.
    r'(\d+)\s+'                          # Dg. e. kælv.
    r'(-|\d+)\s+'                        # Dg. e. Drægt.
    r'(\d+)\s+'                          # Kg. i
    r'(-|\d+)\s+'                        # S.12 mdr. (celgetal)
    r'([\d.,]+)\s+'                      # Fedt %
    r'([\d.,]+)'                         # Prot. %
)


def _parse_dms_format(lines: list[str]) -> pd.DataFrame:
    """
    Parser voor Deens DMS 'Min Liste' formaat.

    Kolommen na Dyr. Nr.:
      Lakt. værdi | Lakt. nr. | Antal ins. | Dg.kælv. | Dg.Drægt. |
      Kg.i | S.12 mdr. | Fedt | Prot. | Morfar
    """
    text_block = '\n'.join(lines[:40])
    if not _DMS_DETECT.search(text_block):
        return pd.DataFrame()

    rows = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        m = _DMS_DATA_ROW.match(stripped)
        if not m:
            continue

        raw_id = m.group(1).strip()
        # Compacteer dier-ID (verwijder interne spaties)
        animal_id = re.sub(r'\s+', '', raw_id)

        lakt_val = _to_float(m.group(2))
        lakt_nr = _to_float(m.group(3))
        antal_ins = _to_float(m.group(4))
        # groep 5 = Dg. e. kælv. (niet nodig voor advies)
        dg_draegt = _to_float(m.group(6))   # > 0 = drachtig
        kg_i = _to_float(m.group(7))
        s12_mdr = _to_float(m.group(8))     # celgetal 12 mnd gemiddelde
        fedt = _to_float(m.group(9).replace(',', '.'))
        prot = _to_float(m.group(10).replace(',', '.'))

        pregnant = dg_draegt is not None and dg_draegt > 0

        rows.append({
            'animal_id': animal_id,
            'lactation_value': lakt_val,
            'lactation_number': lakt_nr,
            'inseminations': antal_ins,
            'cell_count': s12_mdr,
            'milk_yield': kg_i,
            'fat': fedt,
            'protein': prot,
            'pregnant': pregnant,
            'animal_name': '',
            'sire_name': '',
            'aaa_code': '',
            'pfw': '',
            'inbreeding_coefficient': None,
            'advisor_note': '',
        })

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df = df[df['animal_id'].notna() & (df['animal_id'] != '')].reset_index(drop=True)
    return df


def _to_float(val) -> float | None:
    if val is None or str(val).strip() in ('-', '', 'nan', 'None'):
        return None
    try:
        return float(str(val).replace(',', '.'))
    except (ValueError, TypeError):
        return None


# ── Tabelextractie ────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    if not text:
        return ''
    return re.sub(r'\s+', ' ', str(text).lower().strip())


def _detect_column_mapping(headers: list) -> dict:
    mapping = {}
    normalized_headers = {_normalize(h): h for h in headers if h}
    for std_field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if _normalize(alias) in normalized_headers:
                mapping[std_field] = normalized_headers[_normalize(alias)]
                break
    return mapping


def _extract_tables_from_pdf(pdf_file) -> list:
    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)
    tables = []
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                for tbl in page.extract_tables():
                    if not tbl or len(tbl) < 2:
                        continue
                    try:
                        header = [str(c or '') for c in tbl[0]]
                        rows = [[str(c or '') for c in row] for row in tbl[1:]]
                        df = pd.DataFrame(rows, columns=header)
                        df = df.dropna(how='all')
                        df = df[df.apply(lambda r: r.str.strip().ne('').any(), axis=1)]
                        if len(df) >= 1:
                            tables.append(df)
                    except Exception:
                        continue
    except Exception:
        pass
    return tables


def _extract_text_lines_from_pdf(pdf_file) -> list[str]:
    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)
    lines = []
    try:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    lines.extend(text.split('\n'))
    except Exception:
        pass
    return lines


def _parse_text_as_table(lines: list[str]) -> pd.DataFrame:
    """Generieke tekst-tabel parser voor overige formaten."""
    header_idx = -1
    for i, line in enumerate(lines):
        ln = line.lower().strip()
        if re.search(r'(lakt|lactat|lw|lac\.)', ln) and re.search(r'(cel|scc|ins)', ln):
            header_idx = i
            break
    if header_idx < 0:
        return pd.DataFrame()

    header_parts = lines[header_idx].split()
    if len(header_parts) < 3:
        return pd.DataFrame()

    rows = []
    for line in lines[header_idx + 1:]:
        stripped = line.strip()
        if not stripped or len(stripped) < 10:
            continue
        if re.match(r'^(totaal|gemiddeld|gem\.|total|average)', stripped.lower()):
            break
        parts = stripped.split()
        if len(parts) >= 3:
            rows.append(parts)

    if not rows:
        return pd.DataFrame()

    max_cols = max(len(r) for r in rows)
    n_header = len(header_parts)
    n_cols = max(n_header, max_cols)
    padded_rows = [r + [''] * (n_cols - len(r)) for r in rows]
    padded_header = header_parts + [f'col_{i}' for i in range(n_cols - n_header)]
    return pd.DataFrame(padded_rows, columns=padded_header)


# ── Gemeenschappelijke helpers ────────────────────────────────────────────────

def _clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(',', '.').str.extract(r'(-?[\d.]+)')[0],
        errors='coerce',
    )


def _apply_mapping(df: pd.DataFrame, mapping: dict) -> pd.DataFrame:
    result = pd.DataFrame()
    for std_field, orig_col in mapping.items():
        if orig_col in df.columns:
            result[std_field] = df[orig_col]

    numeric_fields = [
        'lactation_number', 'lactation_value', 'inseminations',
        'milk_yield', 'cell_count', 'protein', 'fat', 'urea',
        'inbreeding_coefficient',
    ]
    for field in numeric_fields:
        if field in result.columns:
            result[field] = _clean_numeric(result[field])

    if 'animal_id' in result.columns:
        result['animal_id'] = result['animal_id'].astype(str).str.strip()
        result = result[result['animal_id'].str.len() > 0]
        result = result[~result['animal_id'].isin(['nan', 'None', ''])]

    result = result.reset_index(drop=True)

    defaults = {
        'animal_name': '', 'lactation_number': None, 'lactation_value': None,
        'inseminations': None, 'cell_count': None, 'pregnant': False,
        'milk_yield': None, 'protein': None, 'fat': None, 'urea': None,
        'pfw': '', 'aaa_code': '', 'breed': 'Holstein', 'sire_name': '',
        'sire_code': '', 'inbreeding_coefficient': None, 'advisor_note': '',
    }
    for col, default in defaults.items():
        if col not in result.columns:
            result[col] = default
    return result


def _positional_mapping_fallback(headers: list) -> dict:
    mapping = {}
    field_order = [
        'animal_id', 'animal_name', 'lactation_number', 'lactation_value',
        'inseminations', 'cell_count', 'milk_yield', 'protein', 'fat',
    ]
    for i, field in enumerate(field_order):
        if i < len(headers) and headers[i]:
            mapping[field] = headers[i]
    return mapping


# ── Hoofdfunctie ──────────────────────────────────────────────────────────────

def parse_pdf_and_detect_columns(pdf_file):
    """
    Parse melkcontrole PDF. Probeert drie methoden:
      1. pdfplumber tabel-extractie
      2. DMS Deens Min-Liste formaat (tekst-gebaseerd)
      3. Generieke tekst-tabel fallback

    Returns:
        Tuple (animals_df | None, column_mapping: dict, parse_info: dict)
    """
    parse_info = {'method': None, 'rows_found': 0, 'columns_found': [], 'error': None}

    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)

    # ── Methode 1: tabel-extractie ────────────────────────────────────────────
    tables = _extract_tables_from_pdf(pdf_file)
    if tables:
        tables_sorted = sorted(tables, key=len, reverse=True)
        raw_df = tables_sorted[0]
        for tbl in tables_sorted[1:]:
            if set(tbl.columns) == set(raw_df.columns):
                raw_df = pd.concat([raw_df, tbl], ignore_index=True)

        headers = [str(c) for c in raw_df.columns]
        mapping = _detect_column_mapping(headers) or _positional_mapping_fallback(headers)

        if mapping and 'animal_id' in mapping:
            animals_df = _apply_mapping(raw_df, mapping)
            if len(animals_df) > 0:
                parse_info.update(method='tabel', rows_found=len(animals_df),
                                  columns_found=list(mapping.keys()))
                return animals_df, mapping, parse_info

    # ── Methode 2: DMS Deens formaat ─────────────────────────────────────────
    if hasattr(pdf_file, 'seek'):
        pdf_file.seek(0)

    lines = _extract_text_lines_from_pdf(pdf_file)

    dms_df = _parse_dms_format(lines)
    if not dms_df.empty:
        parse_info.update(method='DMS-Deens', rows_found=len(dms_df),
                          columns_found=['animal_id', 'lactation_value', 'lactation_number',
                                         'inseminations', 'cell_count', 'milk_yield',
                                         'fat', 'protein'])
        mapping = {f: f for f in parse_info['columns_found']}
        return dms_df, mapping, parse_info

    # ── Methode 3: generieke tekst-tabel ─────────────────────────────────────
    if lines:
        raw_df = _parse_text_as_table(lines)
        if not raw_df.empty:
            headers = [str(c) for c in raw_df.columns]
            mapping = _detect_column_mapping(headers) or _positional_mapping_fallback(headers)
            if mapping and 'animal_id' in mapping:
                animals_df = _apply_mapping(raw_df, mapping)
                if len(animals_df) > 0:
                    parse_info.update(method='tekst', rows_found=len(animals_df),
                                      columns_found=list(mapping.keys()))
                    return animals_df, mapping, parse_info

    # ── Alle methoden mislukt ────────────────────────────────────────────────
    raw_text_preview = '\n'.join(lines[:30]) if lines else '(geen tekst gevonden)'
    tbl_cols = [str(c) for c in (tables[0].columns if tables else [])]
    parse_info['error'] = (
        f'Kon geen dierendata vinden in de PDF.\n'
        f'Gevonden kolommen in PDF: {tbl_cols}.\n'
        f'Eerste regels:\n{raw_text_preview[:500]}'
    )
    return None, {}, parse_info


def _create_demo_dataframe() -> pd.DataFrame:
    """Demo-DataFrame voor tests."""
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
        'urea': [24.0, 28.0, 22.0, 26.0],
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
