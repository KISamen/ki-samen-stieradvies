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
from engine.parser import parse_pdf_and_detect_columns
from engine.session_config import init_session_state
from report.generator import ReportGenerator

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
        with st.spinner("PDF inlezen en kolommen detecteren..."):
            try:
                animals_df, column_mapping = parse_pdf_and_detect_columns(uploaded_pdf)
                st.session_state.animals_df = animals_df
                st.session_state.column_mapping = column_mapping
                st.session_state.advice_result = {}
                st.success(f"✅ {len(animals_df)} dieren ingelezen")
                if column_mapping:
                    st.caption(f"Gedetecteerde kolommen: {len(column_mapping)}")
            except Exception as e:
                st.error(f"Fout bij PDF-parsing: {e}")

    elif use_demo and st.session_state.animals_df is None:
        from engine.parser import _create_demo_dataframe
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
    tab1, tab2, tab3 = st.tabs(["🐄 Dieren", "🎯 Adviezen", "💬 Chat"])

    # ── TAB 1: DIEREN ─────────────────────────────────────────────────────────
    with tab1:
        st.markdown("### Geëxtraheerde Dieren")
        st.info("Controleer de data en pas waar nodig aan voordat je adviezen genereert.")

        display_cols = [
            'animal_id', 'animal_name', 'lactation_number', 'lactation_value',
            'inseminations', 'cell_count', 'milk_yield', 'protein', 'fat',
            'inbreeding_coefficient', 'advisor_note',
        ]
        available_cols = [c for c in display_cols if c in st.session_state.animals_df.columns]

        edited_df = st.data_editor(
            st.session_state.animals_df[available_cols],
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
                }
                st.rerun()

    # ── TAB 2: ADVIEZEN ───────────────────────────────────────────────────────
    with tab2:
        st.markdown("### Adviezen per Dier")

        if not st.session_state.advice_result:
            st.info("Geen adviezen gegenereerd. Ga naar de tab 'Dieren' en klik 'Genereer Adviezen'.")
        else:
            # Samenvatting
            advice_vals = list(st.session_state.advice_result.values())
            bwb_n = sum(1 for a in advice_vals if a.get('advice_type') == 'belgian_witblauw')
            milk_n = sum(1 for a in advice_vals if a.get('advice_type') == 'milking_sire')
            gen_n = sum(1 for a in advice_vals if a.get('advice_type') == 'genetic_merit')
            skip_n = sum(1 for a in advice_vals if a.get('advice_type') == 'overgeslagen')

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("🔴 Belgisch Witblauw", bwb_n)
            m2.metric("🔵 Melkstier", milk_n)
            m3.metric("🟢 Gen. Verdienste", gen_n)
            m4.metric("⚪ Overgeslagen", skip_n)

            st.markdown("---")

            # Advies tabel
            rows = []
            for _, animal in st.session_state.animals_df.iterrows():
                animal_id = str(animal.get('animal_id', ''))
                advice = st.session_state.advice_result.get(animal_id, {})

                advice_labels = {
                    'belgian_witblauw': '🔴 Belgisch Witblauw',
                    'milking_sire': '🔵 Melkstier',
                    'genetic_merit': '🟢 Gen. Verdienste',
                    'overgeslagen': '⚪ Overgeslagen',
                }

                rows.append({
                    'Dier-ID': animal_id,
                    'Naam': str(animal.get('animal_name', '-')),
                    'Lakt.nr.': animal.get('lactation_number', '-'),
                    'Lakt.wrd.': animal.get('lactation_value', '-'),
                    'Celgetal': animal.get('cell_count', '-'),
                    'Insem.': animal.get('inseminations', '-'),
                    'Advies': advice_labels.get(advice.get('advice_type', ''), advice.get('advice_type', '-')),
                    'Aanbevolen Stier': advice.get('recommended_bull', '-') or '-',
                    'Score': f"{advice.get('confidence_score', 0):.2f}",
                    'Reden': advice.get('explanation', '-'),
                })

            advice_df = pd.DataFrame(rows)
            st.dataframe(advice_df, use_container_width=True, hide_index=True)

            # Uitgesloten stieren tonen
            excluded = st.session_state.overrides.get('excluded_bulls', set())
            if excluded:
                st.warning(f"⚠️ Uitgesloten stieren: {', '.join(excluded)}")

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

    # ── TAB 3: CHAT ───────────────────────────────────────────────────────────
    with tab3:
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
            from engine.parser import _create_demo_dataframe
            st.session_state.animals_df = _create_demo_dataframe()
            st.session_state.default_settings['set_at'] = datetime.now().isoformat()
            st.rerun()
