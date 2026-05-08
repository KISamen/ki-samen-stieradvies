"""
Stieren laden en filteren uit de PIM CSV-database.
"""
import glob
import os

import pandas as pd

_CACHED_BULLS: pd.DataFrame | None = None
_CSV_MTIME: float | None = None


def _find_csv() -> str | None:
    """Vind het meest recente CSV-bestand in de data map."""
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    files = glob.glob(os.path.join(data_dir, '*.csv'))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def load_bulls_from_csv(force_reload: bool = False) -> pd.DataFrame:
    """Laad en cache stieren uit de PIM CSV-database. Retourneert alleen ACTIVE stieren."""
    global _CACHED_BULLS, _CSV_MTIME

    csv_path = _find_csv()
    if csv_path is None:
        return pd.DataFrame()

    mtime = os.path.getmtime(csv_path)
    if not force_reload and _CACHED_BULLS is not None and mtime == _CSV_MTIME:
        return _CACHED_BULLS

    try:
        df = pd.read_csv(csv_path, sep=';', encoding='utf-8', on_bad_lines='skip')
    except Exception:
        return pd.DataFrame()

    if 'Status' in df.columns:
        df = df[df['Status'] == 'ACTIVE'].copy()

    result = _map_columns(df)
    _CACHED_BULLS = result
    _CSV_MTIME = mtime
    return result


def _get_col(df: pd.DataFrame, name: str, default=None) -> pd.Series:
    return df[name] if name in df.columns else pd.Series([default] * len(df))


def _map_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Map CSV-kolommen naar intern standaardformaat."""
    r = pd.DataFrame()

    r['id'] = _get_col(df, 'ID')
    r['name'] = _get_col(df, 'Naam stier')
    r['short_name'] = _get_col(df, 'Afkorting stier (zoeknaam)')
    r['stier_code'] = pd.to_numeric(_get_col(df, 'Stiercode NL / KI code'), errors='coerce')
    r['levensnummer'] = _get_col(df, 'Levensnummer')
    r['breed_code'] = pd.to_numeric(_get_col(df, 'Rascode'), errors='coerce')
    r['breed_name'] = _get_col(df, 'Ras K.I. SAMEN - Nederlands')

    # Type kolommen voor advieslogica
    r['fokstier_type'] = _get_col(df, 'Toekomststier / fokstier')   # 'Fokstier' / 'Toekomststier'
    r['bwb_type'] = _get_col(df, 'BwB: gebruikskruising en/of zuiver')  # 'zuiver' / 'gebruikskruising' / NaN

    pinkenstier = pd.to_numeric(_get_col(df, 'Pinkenstier'), errors='coerce').fillna(0)
    r['suitable_for_heifers'] = pinkenstier == 2

    r['price'] = pd.to_numeric(_get_col(df, 'Prijs'), errors='coerce')
    r['kappa_casein'] = _get_col(df, 'Kappa-caseine')
    r['beta_casein'] = _get_col(df, 'Betacasine')
    r['nvi'] = pd.to_numeric(
        _get_col(df, 'Official Production Evaluation in this Country NVI'), errors='coerce'
    )
    # Geboortegemak-index: 10000 = rasgemiddeld, hoger = makkelijker
    r['calf_ease'] = pd.to_numeric(
        _get_col(df, 'OFFICIAL CALVING EASE EVALUATION IN THIS COUNTRY geboortegemak'),
        errors='coerce',
    ).fillna(9800)

    r['category'] = r.apply(_determine_category, axis=1)
    r['available'] = True

    r = r[r['name'].notna() & (r['name'].str.strip() != '')].reset_index(drop=True)
    return r


def _determine_category(row) -> str:
    """Bepaal advies-categorie: belgian_witblauw / milking_sire / genetic_merit."""
    bwb = row.get('bwb_type')
    fokstier = row.get('fokstier_type')
    if pd.notna(bwb) and str(bwb).strip():
        return 'belgian_witblauw'
    if fokstier == 'Fokstier':
        return 'milking_sire'
    return 'genetic_merit'


# ── Hulpfuncties voor UI ──────────────────────────────────────────────────────

def get_all_bull_names() -> list[str]:
    """Gesorteerde lijst van alle actieve stierennamen."""
    bulls = load_bulls_from_csv()
    if bulls.empty:
        return []
    return sorted(bulls['name'].dropna().unique().tolist())


def get_fokstieren() -> pd.DataFrame:
    """Alle actieve fokstieren (melkvee)."""
    bulls = load_bulls_from_csv()
    if bulls.empty:
        return pd.DataFrame()
    return bulls[bulls['fokstier_type'] == 'Fokstier'].copy()


def get_bwb_bulls() -> pd.DataFrame:
    """Alle actieve BWB / beef-on-dairy stieren."""
    bulls = load_bulls_from_csv()
    if bulls.empty:
        return pd.DataFrame()
    mask = bulls['bwb_type'].notna() & (bulls['bwb_type'].str.strip() != '')
    return bulls[mask].copy()


def filter_bulls_by_names(bulls_df: pd.DataFrame, selected_names: list[str]) -> pd.DataFrame:
    """Filter op naam of afkorting. Lege selectie = alle stieren."""
    if not selected_names:
        return bulls_df
    mask = bulls_df['name'].isin(selected_names) | bulls_df['short_name'].isin(selected_names)
    return bulls_df[mask].copy()
