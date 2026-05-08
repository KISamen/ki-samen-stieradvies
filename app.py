"""
KI Samen Stieradvies - Streamlit applicatie
"""
import os
from datetime import datetime

import pandas as pd
import streamlit as st
from anthropic import Anthropic

from chat.interpreter import ChatInterpreter
from engine.advisor import evaluate_animals
from engine.bulls_loader import get_bwb_bulls, get_fokstieren, load_bulls_from_csv
from engine.parser import _create_demo_dataframe, parse_pdf_and_detect_columns
from engine.session_config import init_session_state
from report.generator import ReportGenerator

def _fmt(val, fmt: str = '') -> str:
    """Formatteer een waarde voor weergave; None/nan → '—'."""
    if val is None:
        return '—'
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return '—'
        if fmt:
            return f'{float(val):{fmt}}'
        return str(int(val)) if float(val) == int(float(val)) else str(val)
    except (TypeError, ValueError):
        s = str(val)
        return '—' if s in ('None', 'nan', '') else s


# ── Pagina-config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="KI Samen Stieradvies",
    page_icon="🐄",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sessie initialiseren ─────────────────────────────────────────────────────
init_session_state()

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #1a7a4a 0%, #0d3d25 100%);
        padding: 1rem 1.5rem;
        border-radius: 8px;
        color: white;
        margin-bottom: 1rem;
    }
    .main-header h1 { color: white; margin: 0; font-size: 1.8rem; }
    .main-header p { color: #a8d5b5; margin: 0.2rem 0 0 0; font-size: 0.9rem; }
    .info-box {
        background: #f0f7f4;
        border-left: 4px solid #1a7a4a;
        padding: 0.8rem 1rem;
        border-radius: 4px;
        margin: 0.5rem 0;
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { height: 40px; border-radius: 6px 6px 0 0; }
</style>
""", unsafe_allow_html=True)

# ── SIDEBAR ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## ⚙️ Stieradvies Instellingen")

    with st.form("default_settings_form"):
        st.markdown("### 📋 Drempelwaarden BWB")

        vaars_threshold = st.number_input(
            "Vaars: Lactatiewaarde < → BWB",
            min_value=70,
            max_value=100,
            value=int(st.session_state.default_settings['vaars_lactation_threshold']),
            step=1,
            help="Vaarzen (1e lactatie) met lagere waarde krijgen Belgisch Witblauw",
        )

        koe_threshold = st.number_input(
            "Koe: Lactatiewaarde < → BWB",
            min_value=85,
            max_value=115,
            value=int(st.session_state.default_settings['koe_lactation_threshold']),
            step=1,
            help="Oudere koeien met lagere waarde krijgen Belgisch Witblauw",
        )

        insemination_threshold = st.number_input(
            "Inseminaties ≥ → BWB",
            min_value=1,
            max_value=10,
            value=int(st.session_state.default_settings['insemination_threshold']),
            step=1,
            help="Dieren met dit aantal of meer inseminaties krijgen BWB",
        )

        cell_count_threshold = st.number_input(
            "Celgetal > → BWB",
            min_value=100,
            max_value=600,
            value=int(st.session_state.default_settings['cell_count_threshold']),
            step=10,
            help="Dieren met hoger celgetal krijgen Belgisch Witblauw",
        )

        inbreeding_threshold = st.number_input(
            "Inteelt % > → BWB",
            min_value=5.0,
            max_value=25.0,
            value=float(st.session_state.default_settings['inbreeding_threshold']),
            step=0.5,
            help="Dieren met hogere inteelt krijgen Belgisch Witblauw",
        )

        st.markdown("### 💬 Speciale Wensen")
        custom_requests = st.text_area(
            "Jouw specifieke verzoeken",
            value=st.session_state.default_settings.get('custom_requests', ''),
            placeholder="Bv:\n• Gebruik geen stier X\n• Nadruk op uiergezondheid\n• Voorkeur Jersey-stammen",
            height=90,
            help="Vrije tekst - wordt meegestuurd aan de AI als context",
        )

        submitted = st.form_submit_button("✅ Instellingen Opslaan", use_container_width=True)

        if submitted:
            st.session_state.default_settings = {
                'vaars_lactation_threshold': vaars_threshold,
                'koe_lactation_threshold': koe_threshold,
                'insemination_threshold': insemination_threshold,
                'cell_count_threshold': cell_count_threshold,
                'inbreeding_threshold': inbreeding_threshold,
                'custom_requests': custom_requests,
                'set_at': datetime.now().isoformat(),
            }
            st.success("✅ Instellingen opgeslagen!")

    # Huidige instellingen tonen
    if st.session_state.default_settings.get('set_at'):
        st.markdown("---")
        st.markdown("### 📊 Actieve Drempels")
        s = st.session_state.default_settings
        col_a, col_b = st.columns(2)
        with col_a:
            st.metric("Vaars <", s['vaars_lactation_threshold'])
            st.metric("Koe <", s['koe_lactation_threshold'])
        with col_b:
            st.metric("Insem. ≥", s['insemination_threshold'])
            st.metric("Celgetal >", s['cell_count_threshold'])

    # ── Stieren Selectie ────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 🐂 Stieren Selectie")

    all_bulls_df = load_bulls_from_csv()
    bwb_count = int(all_bulls_df['category'].eq('belgian_witblauw').sum()) if not all_bulls_df.empty else 0
    fokstier_count = int(all_bulls_df['category'].eq('milking_sire').sum()) if not all_bulls_df.empty else 0

    if all_bulls_df.empty:
        st.warning("Geen stierendatabase gevonden. Zorg dat er een CSV-bestand in de 'data' map staat.")
    else:
        st.caption(f"Database: {len(all_bulls_df)} actieve stieren ({bwb_count} BWB · {fokstier_count} fokstier)")

    bull_mode = st.radio(
        "Stieren selectie",
        options=['Alle stieren', 'Eigen selectie'],
        index=0 if st.session_state.overrides.get('bull_selection_mode', 'all') == 'all' else 1,
        horizontal=True,
        label_visibility='collapsed',
        key='bull_mode_radio',
    )
    st.session_state.overrides['bull_selection_mode'] = 'all' if bull_mode == 'Alle stieren' else 'eigen'

    if bull_mode == 'Eigen selectie' and not all_bulls_df.empty:
        all_names = sorted(all_bulls_df['name'].dropna().unique().tolist())

        selected = st.multiselect(
            "Selecteer stieren",
            options=all_names,
            default=st.session_state.overrides.get('selected_bulls', []),
            placeholder="Zoek en selecteer stieren...",
            key='bull_multiselect',
            help="Kies de stieren die je wilt inzetten. Zowel BWB als fokstieren kunnen worden geselecteerd.",
        )
        st.session_state.overrides['selected_bulls'] = selected

        # Toon verdeling van de selectie
        if selected:
            sel_df = all_bulls_df[all_bulls_df['name'].isin(selected)]
            sel_bwb = int(sel_df['category'].eq('belgian_witblauw').sum())
            sel_fok = int(sel_df['category'].eq('milking_sire').sum())
            st.caption(f"Selectie: {len(selected)} stieren — {sel_bwb} BWB · {sel_fok} fokstier")
        else:
            st.info("Geen stieren geselecteerd — alle actieve stieren worden gebruikt.")
    else:
        st.session_state.overrides['selected_bulls'] = []

    st.markdown("---")
    st.markdown("### 📤 PDF Uploaden")

    uploaded_pdf = st.file_uploader(
        "Melkcontrole PDF",
        type=["pdf"],
        help="Upload een melkcontrole PDF (NL, DK, DE, BE formaten ondersteund)",
    )

    use_demo = st.checkbox(
        "Demo-data gebruiken (geen PDF nodig)",
        value=st.session_state.animals_df is not None,
        help="Laad voorbeelddieren voor demo",
    )

    if uploaded_pdf is not None:
        with st.spinner("PDF inlezen..."):
            try:
                animals_df, column_mapping, parse_info = parse_pdf_and_detect_columns(uploaded_pdf)
                if animals_df is not None and len(animals_df) > 0:
                    st.session_state.animals_df = animals_df
                    st.session_state.column_mapping = column_mapping
                    st.session_state.advice_result = {}
                    method = parse_info.get('method', '?')
                    st.success(
                        f"✅ {len(animals_df)} dieren ingelezen "
                        f"({len(column_mapping)} kolommen, methode: {method})"
                    )
                else:
                    err = parse_info.get('error', 'Onbekende fout')
                    st.error(f"Kon dieren niet uitlezen uit PDF.")
                    with st.expander("Diagnose-informatie"):
                        st.code(err)
                    st.info(
                        "Tips: controleer of de PDF tekst bevat (geen scan), "
                        "of gebruik de Demo-data knop om te testen."
                    )
            except Exception as e:
                st.error(f"Fout bij PDF-parsing: {e}")

    elif use_demo and st.session_state.animals_df is None:
        st.session_state.animals_df = _create_demo_dataframe()
        st.session_state.advice_result = {}
        st.info("Demo-data geladen (4 voorbeelddieren)")

    st.markdown("---")
    st.caption(f"Sessie: {st.session_state.session_id[:8]}...")

# ── MAIN AREA ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="main-header">
    <h1>🐄 KI Samen Stieradvies</h1>
    <p>Automatisch stieradvies op basis van melkcontroledata</p>
</div>
""", unsafe_allow_html=True)

# Bedrijfsnaam
col_name, col_info = st.columns([3, 1])
with col_name:
    company_name = st.text_input(
        "Bedrijfsnaam",
        value=st.session_state.get('company_name', 'Mijn Bedrijf'),
        key="company_name_input",
        placeholder="Voer bedrijfsnaam in...",
    )
    st.session_state.company_name = company_name

with col_info:
    if st.session_state.animals_df is not None:
        st.metric("Dieren", len(st.session_state.animals_df))
    if st.session_state.advice_result:
        bwb_count = sum(
            1 for a in st.session_state.advice_result.values()
            if a.get('advice_type') == 'belgian_witblauw'
        )
        st.metric("BWB advies", bwb_count)

# ── Tabs ──────────────────────────────────────────────────────────────────────
if st.session_state.animals_df is not None:
    tab1, tab2, tab3, tab4 = st.tabs(["🐄 Dieren", "🎯 Adviezen", "🐂 Stieren", "💬 Chat"])

    # ── TAB 1: DIEREN ─────────────────────────────────────────────────────────
    with tab1:
        # ── Advies-overzichtstabel (bovenaan, als adviezen beschikbaar zijn) ──
        if st.session_state.advice_result:
            _adv_labels = {
                'belgian_witblauw': '🔴 BWB',
                'fokstier': '🟢 Fokstier',
                'geen_advies': '⚪ Geen advies',
                'onvoldoende_data': '⚠️ Data ontbreekt',
                'overgeslagen': '⚪ Overgeslagen',
                'milking_sire': '🟢 Fokstier',
                'genetic_merit': '🟢 Fokstier',
            }
            overview_rows = []
            for _, animal in st.session_state.animals_df.iterrows():
                aid = str(animal.get('animal_id', ''))
                adv = st.session_state.advice_result.get(aid, {})
                adv_type = adv.get('advice_type', '')
                bull = adv.get('recommended_bull') or '—'
                has_warn = bool(adv.get('warnings'))
                overview_rows.append({
                    'Dier-ID': aid,
                    'Lakt.nr.': _fmt(animal.get('lactation_number')),
                    'LW': _fmt(animal.get('lactation_value'), '.1f'),
                    'Ins.': _fmt(animal.get('inseminations')),
                    'Celgetal': _fmt(animal.get('cell_count')),
                    'Advies': _adv_labels.get(adv_type, adv_type or '—'),
                    'Aanbevolen stier': bull,
                    '⚠️': '⚠️' if has_warn else '',
                })
            st.dataframe(
                pd.DataFrame(overview_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    'Dier-ID': st.column_config.TextColumn(width='medium'),
                    'Lakt.nr.': st.column_config.TextColumn(width='small'),
                    'LW': st.column_config.TextColumn(width='small'),
                    'Ins.': st.column_config.TextColumn(width='small'),
                    'Celgetal': st.column_config.TextColumn(width='small'),
                    'Advies': st.column_config.TextColumn(width='small'),
                    'Aanbevolen stier': st.column_config.TextColumn(width='large'),
                    '⚠️': st.column_config.TextColumn(width='small'),
                },
            )
            st.markdown("---")

        st.markdown("### Diergegevens (bewerkbaar)")
        st.caption("Controleer en corrigeer de data voordat je adviezen genereert.")

        display_cols = [
            'animal_id', 'animal_name', 'lactation_number', 'lactation_value',
            'inseminations', 'cell_count', 'milk_yield', 'protein', 'fat',
            'inbreeding_coefficient', 'advisor_note',
        ]
        available_cols = [c for c in display_cols if c in st.session_state.animals_df.columns]

        # Vervang None door pd.NA voor betere weergave
        edit_df = st.session_state.animals_df[available_cols].copy()
        for col in edit_df.columns:
            if edit_df[col].dtype == object:
                edit_df[col] = edit_df[col].fillna('')
            else:
                edit_df[col] = edit_df[col].where(edit_df[col].notna(), other=None)

        edited_df = st.data_editor(
            edit_df,
            use_container_width=True,
            num_rows="dynamic",
            key='animals_editor',
            column_config={
                'animal_id': st.column_config.TextColumn('Dier-ID', width='medium'),
                'animal_name': st.column_config.TextColumn('Naam', width='small'),
                'lactation_number': st.column_config.NumberColumn('Lakt.nr.', min_value=1, max_value=20, width='small'),
                'lactation_value': st.column_config.NumberColumn('Lakt.wrd.', format='%.1f', width='small'),
                'inseminations': st.column_config.NumberColumn('Insem.', min_value=0, max_value=20, width='small'),
                'cell_count': st.column_config.NumberColumn('Celgetal', min_value=0, width='small'),
                'milk_yield': st.column_config.NumberColumn('Melk (kg)', format='%.0f', width='small'),
                'protein': st.column_config.NumberColumn('Eiwit %', format='%.2f', width='small'),
                'fat': st.column_config.NumberColumn('Vet %', format='%.2f', width='small'),
                'inbreeding_coefficient': st.column_config.NumberColumn('Inteelt %', format='%.1f', width='small'),
                'advisor_note': st.column_config.TextColumn('Notitie', width='large'),
            },
        )

        # Update session_state met gecorrigeerde data
        for col in available_cols:
            if col in st.session_state.animals_df.columns:
                st.session_state.animals_df[col] = edited_df[col]

        col_btn1, col_btn2, _ = st.columns([2, 2, 4])
        with col_btn1:
            if st.button("🎯 Genereer Adviezen", type="primary", use_container_width=True):
                with st.spinner("Adviezen aan het genereren..."):
                    try:
                        advice_result = evaluate_animals(
                            st.session_state.animals_df,
                            st.session_state.default_settings,
                            st.session_state.overrides,
                        )
                        st.session_state.advice_result = advice_result
                        st.success(f"✅ {len(advice_result)} adviezen gegenereerd!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Fout bij genereren adviezen: {e}")

        with col_btn2:
            if st.button("🔄 Reset Adviezen", use_container_width=True):
                st.session_state.advice_result = {}
                st.session_state.overrides = {
                    'skip_animals': set(),
                    'force_bulls': {},
                    'excluded_bulls': set(),
                    'excluded_breeders': set(),
                    'threshold_adjustments': {},
                    'selected_bulls': st.session_state.overrides.get('selected_bulls', []),
                    'bull_selection_mode': st.session_state.overrides.get('bull_selection_mode', 'all'),
                }
                st.rerun()

    # ── TAB 2: ADVIEZEN ───────────────────────────────────────────────────────
    with tab2:
        st.markdown("### Stieradvies")

        if not st.session_state.advice_result:
            st.info("Klik op 'Genereer Adviezen' in de tab Dieren om adviezen te maken.")
        else:
            advice_vals = list(st.session_state.advice_result.values())
            bwb_n = sum(1 for a in advice_vals if a.get('advice_type') == 'belgian_witblauw')
            fok_n = sum(1 for a in advice_vals if a.get('advice_type') == 'fokstier')
            skip_n = sum(1 for a in advice_vals if a.get('advice_type') in ('geen_advies', 'overgeslagen'))
            warn_n = sum(1 for a in advice_vals if a.get('advice_type') == 'onvoldoende_data')

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🔴 Belgisch Witblauw", bwb_n)
            m2.metric("🟢 Fokstier", fok_n)
            m3.metric("⚪ Geen advies", skip_n)
            m4.metric("⚠️ Dataproblemen", warn_n)

            st.markdown("---")

            # ── Overzichtstabel ───────────────────────────────────────────────
            advice_type_label = {
                'belgian_witblauw': 'BWB',
                'fokstier': 'Fokstier',
                'geen_advies': 'Geen advies',
                'onvoldoende_data': '⚠️ Data ontbreekt',
                'overgeslagen': 'Overgeslagen',
                'milking_sire': 'Fokstier',
                'genetic_merit': 'Fokstier',
            }

            rows = []
            for _, animal in st.session_state.animals_df.iterrows():
                animal_id = str(animal.get('animal_id', ''))
                adv = st.session_state.advice_result.get(animal_id, {})
                adv_type = adv.get('advice_type', '')
                bull = adv.get('recommended_bull') or '— geen stier gevonden —'
                has_warn = bool(adv.get('warnings'))
                rows.append({
                    'Dier-ID': animal_id,
                    'Naam': str(animal.get('animal_name', '') or ''),
                    'Lakt.nr.': animal.get('lactation_number', ''),
                    'LW': animal.get('lactation_value', ''),
                    'Ins.': animal.get('inseminations', ''),
                    'Celgetal': animal.get('cell_count', ''),
                    'Advies type': advice_type_label.get(adv_type, adv_type),
                    'Aanbevolen stier': bull,
                    '⚠️': '⚠️' if has_warn else '',
                })

            st.dataframe(
                pd.DataFrame(rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    'Dier-ID': st.column_config.TextColumn(width='medium'),
                    'Naam': st.column_config.TextColumn(width='small'),
                    'Lakt.nr.': st.column_config.NumberColumn(width='small'),
                    'LW': st.column_config.NumberColumn(format='%.1f', width='small'),
                    'Ins.': st.column_config.NumberColumn(width='small'),
                    'Celgetal': st.column_config.NumberColumn(width='small'),
                    'Advies type': st.column_config.TextColumn(width='small'),
                    'Aanbevolen stier': st.column_config.TextColumn(width='large'),
                    '⚠️': st.column_config.TextColumn(width='small'),
                },
            )

            # ── Detail per dier ───────────────────────────────────────────────
            st.markdown("---")
            st.markdown("#### Toelichting per dier")
            for _, animal in st.session_state.animals_df.iterrows():
                animal_id = str(animal.get('animal_id', ''))
                adv = st.session_state.advice_result.get(animal_id, {})
                if not adv:
                    continue

                adv_type = adv.get('advice_type', '')
                bull = adv.get('recommended_bull') or 'Geen stier gevonden'
                type_lbl = advice_type_label.get(adv_type, adv_type)
                naam = str(animal.get('animal_name', '') or animal_id)
                header = f"{type_lbl} | {naam} ({animal_id}) → {bull}"

                with st.expander(header, expanded=False):
                    reasons = adv.get('reasons', [])
                    warnings = adv.get('warnings', [])

                    if reasons:
                        st.markdown("**Redenen:**")
                        for r in reasons:
                            st.markdown(f"- {r}")

                    for w in warnings:
                        st.warning(w)

                    excl = adv.get('excluded_bulls_detail', {})
                    if excl:
                        st.markdown("**Uitgesloten stieren:**")
                        for bn, reason in list(excl.items())[:8]:
                            st.caption(f"• {bn}: {reason}")

                    bull_scores = adv.get('bull_scores', {})
                    if bull_scores:
                        st.markdown("**Top stieren (score):**")
                        score_rows = [
                            {'Stier': k, 'Score': v}
                            for k, v in sorted(bull_scores.items(), key=lambda x: -x[1])[:5]
                        ]
                        st.dataframe(pd.DataFrame(score_rows), hide_index=True, use_container_width=True)

            excluded = st.session_state.overrides.get('excluded_bulls', set())
            if excluded:
                st.warning(f"Uitgesloten stieren deze sessie: {', '.join(excluded)}")

            st.markdown("---")
            st.markdown("### 📥 PDF Rapport Downloaden")

            col_pdf1, col_pdf2 = st.columns([3, 1])
            with col_pdf1:
                report_title = st.text_input(
                    "Rapport titel",
                    value=st.session_state.report_settings.get('title', 'Stieradvies'),
                )
                st.session_state.report_settings['title'] = report_title

                footer_text = st.text_input(
                    "Footer tekst (optioneel)",
                    value=st.session_state.report_settings.get('footer_text', ''),
                )
                st.session_state.report_settings['footer_text'] = footer_text

            with col_pdf2:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("📄 Genereer PDF", type="primary", use_container_width=True):
                    with st.spinner("PDF aan het genereren..."):
                        try:
                            report_gen = ReportGenerator(
                                company_name=st.session_state.company_name,
                                animals_df=st.session_state.animals_df,
                                advice_result=st.session_state.advice_result,
                                report_settings=st.session_state.report_settings,
                                default_settings=st.session_state.default_settings,
                            )
                            pdf_bytes = report_gen.generate_pdf_bytes()
                            datum = datetime.now().strftime('%Y%m%d')
                            bedrijf = st.session_state.company_name.replace(' ', '_')

                            st.download_button(
                                label="⬇️ Download PDF Rapport",
                                data=pdf_bytes,
                                file_name=f"stieradvies_{bedrijf}_{datum}.pdf",
                                mime="application/pdf",
                                use_container_width=True,
                            )
                        except Exception as e:
                            st.error(f"Fout bij PDF generatie: {e}")

    # ── TAB 3: STIEREN ────────────────────────────────────────────────────────
    with tab3:
        st.markdown("### Stierendatabase")

        bulls_df = load_bulls_from_csv()

        if bulls_df.empty:
            st.warning("Geen stierendatabase beschikbaar. Zorg dat er een CSV-bestand in de 'data' map staat.")
        else:
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                show_filter = st.selectbox(
                    "Filter op type",
                    options=['Alle stieren', 'Fokstieren', 'BWB / Beef-on-dairy'],
                    key='bulls_tab_filter',
                )
            with col_f2:
                search_term = st.text_input(
                    "Zoek stier",
                    placeholder="Naam of afkorting...",
                    key='bulls_tab_search',
                )
            with col_f3:
                show_heifers_only = st.checkbox("Alleen pinkenstieren", key='bulls_heifer_filter')

            view_df = bulls_df.copy()
            if show_filter == 'Fokstieren':
                view_df = view_df[view_df['fokstier_type'] == 'Fokstier']
            elif show_filter == 'BWB / Beef-on-dairy':
                view_df = view_df[view_df['bwb_type'].notna() & (view_df['bwb_type'].str.strip() != '')]
            if search_term:
                mask = (
                    view_df['name'].str.contains(search_term, case=False, na=False) |
                    view_df['short_name'].str.contains(search_term, case=False, na=False)
                )
                view_df = view_df[mask]
            if show_heifers_only:
                view_df = view_df[view_df['suitable_for_heifers'] == True]

            st.caption(f"{len(view_df)} stieren weergegeven")

            display_cols = ['name', 'short_name', 'breed_name', 'fokstier_type', 'bwb_type',
                            'suitable_for_heifers', 'kappa_casein', 'beta_casein', 'nvi',
                            'calf_ease', 'price']
            available = [c for c in display_cols if c in view_df.columns]

            st.dataframe(
                view_df[available].reset_index(drop=True),
                use_container_width=True,
                hide_index=True,
                column_config={
                    'name': st.column_config.TextColumn('Naam stier', width='large'),
                    'short_name': st.column_config.TextColumn('Afkorting', width='medium'),
                    'breed_name': st.column_config.TextColumn('Ras', width='medium'),
                    'fokstier_type': st.column_config.TextColumn('Type', width='small'),
                    'bwb_type': st.column_config.TextColumn('BWB type', width='small'),
                    'suitable_for_heifers': st.column_config.CheckboxColumn('Pinkenstier', width='small'),
                    'kappa_casein': st.column_config.TextColumn('Kappa', width='small'),
                    'beta_casein': st.column_config.TextColumn('Beta', width='small'),
                    'nvi': st.column_config.NumberColumn('NVI', format='%.0f', width='small'),
                    'calf_ease': st.column_config.NumberColumn('Geboortegemak', format='%.0f', width='small'),
                    'price': st.column_config.NumberColumn('Prijs €', format='%.2f', width='small'),
                },
            )

            st.markdown("---")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Totaal actief", len(bulls_df))
            m2.metric("Fokstieren", int((bulls_df['fokstier_type'] == 'Fokstier').sum()))
            m3.metric("BWB / BoD", int(bulls_df['bwb_type'].notna().sum()))
            m4.metric("Pinkenstieren", int(bulls_df['suitable_for_heifers'].sum()))

    # ── TAB 4: CHAT ───────────────────────────────────────────────────────────
    with tab4:
        st.markdown("### 💬 Vragen & Aanpassingen")
        st.info(
            "Stel vragen over de adviezen of vraag om aanpassingen. "
            "Voorbeelden: 'Waarom krijgt koe 123 BWB?', 'Zet celgetal op 250', 'Gebruik stier X niet meer'"
        )

        # Chat history weergeven
        chat_container = st.container()
        with chat_container:
            for msg in st.session_state.chat_history:
                if msg['role'] == 'user':
                    with st.chat_message("user"):
                        st.write(msg['content'])
                else:
                    with st.chat_message("assistant"):
                        st.write(msg['content'])

        # Chat input
        user_input = st.chat_input("Stel een vraag of vraag om aanpassingen...")

        if user_input:
            # Voeg toe aan history
            st.session_state.chat_history.append({'role': 'user', 'content': user_input})

            # Haal API key op
            api_key = None
            try:
                api_key = st.secrets.get('ANTHROPIC_API_KEY')
            except Exception:
                pass

            if not api_key:
                api_key = os.environ.get('ANTHROPIC_API_KEY')

            if not api_key:
                response_text = (
                    "⚠️ Geen API sleutel ingesteld. Voeg ANTHROPIC_API_KEY toe aan "
                    ".streamlit/secrets.toml om de chat te gebruiken."
                )
                changes = []
            else:
                try:
                    client = Anthropic(api_key=api_key)
                    interpreter = ChatInterpreter(
                        client=client,
                        animals_df=st.session_state.animals_df,
                        advice_result=st.session_state.advice_result,
                        session_state=dict(st.session_state),
                    )
                    response_text, changes = interpreter.process_user_message(user_input)

                    # Pas wijzigingen toe op echte session_state
                    for change in changes:
                        change_type = change.get('type')
                        if change_type == 'threshold':
                            field = change.get('field', '')
                            value = change.get('value')
                            if field and value is not None and field in st.session_state.default_settings:
                                st.session_state.default_settings[field] = value
                        elif change_type == 'exclude_bull':
                            bull_name = change.get('bull_name', '')
                            if bull_name:
                                st.session_state.overrides['excluded_bulls'].add(bull_name)
                        elif change_type == 'skip_animal':
                            animal_id = str(change.get('animal_id', ''))
                            if animal_id:
                                st.session_state.overrides['skip_animals'].add(animal_id)
                        elif change_type == 'report_setting':
                            setting = change.get('setting', '')
                            val = change.get('value', '')
                            if setting:
                                st.session_state.report_settings[setting] = val
                        elif change_type == 'recalculate':
                            # Herbereken adviezen
                            new_advice = evaluate_animals(
                                st.session_state.animals_df,
                                st.session_state.default_settings,
                                st.session_state.overrides,
                            )
                            st.session_state.advice_result = new_advice

                except Exception as e:
                    response_text = f"Er is een fout opgetreden: {str(e)}"
                    changes = []

            # Voeg toe aan history
            st.session_state.chat_history.append({'role': 'assistant', 'content': response_text})

            # Notificatie bij wijzigingen
            if changes:
                change_types = [c.get('type', '?') for c in changes]
                needs_recalc = any(
                    c in ('threshold', 'exclude_bull', 'skip_animal', 'recalculate')
                    for c in change_types
                )
                if needs_recalc and st.session_state.animals_df is not None:
                    new_advice = evaluate_animals(
                        st.session_state.animals_df,
                        st.session_state.default_settings,
                        st.session_state.overrides,
                    )
                    st.session_state.advice_result = new_advice

            st.rerun()

else:
    # Geen data geladen
    st.markdown("""
    <div class="info-box">
        <strong>🚀 Aan de slag</strong><br>
        1. Stel je drempelwaarden in het linker menu in<br>
        2. Upload een melkcontrole PDF <em>of</em> vink 'Demo-data gebruiken' aan<br>
        3. Controleer de diergegevens en genereer adviezen<br>
        4. Download een PDF-rapport of stel vragen via de chat
    </div>
    """, unsafe_allow_html=True)

    col_demo, _ = st.columns([2, 4])
    with col_demo:
        if st.button("🐄 Demo starten", type="primary", use_container_width=True):
            st.session_state.animals_df = _create_demo_dataframe()
            st.session_state.default_settings['set_at'] = datetime.now().isoformat()
            st.rerun()
