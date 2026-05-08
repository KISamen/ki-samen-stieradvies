"""
Chat-interpreter: verwerkt gebruikersberichten en past sessie-state aan.
"""
import json
import re

import streamlit as st


SYSTEM_PROMPT = """Je bent een fokadviseur-assistent voor melkveebedrijven. Je helpt boeren met stieradvies.

De gebruiker kan vragen stellen over:
- Waarom dier X stier Y krijgt (leg de regels uit)
- Regelaanpassingen (bv. "verhoog celgetaldrempel naar 350")
- Stieren uitsluiten (bv. "gebruik stier X niet meer")
- Dieren overslaan (bv. "sla koe 123 over")
- Rapportaanpassingen

Jouw taak:
1. Beantwoord de vraag vriendelijk en als expert in het Nederlands
2. Als een wijziging nodig is, voeg dan ALTIJD een JSON-blok toe aan je antwoord
3. Wees duidelijk en transparant over waarom een dier een bepaald advies krijgt
4. Gebruik eenvoudige taal, geen vakjargon

JSON-formaten voor wijzigingen (gebruik ```json ... ```):
- Drempel aanpassen: {"type": "threshold", "field": "cell_count_threshold", "value": 350}
- Stier uitsluiten: {"type": "exclude_bull", "bull_name": "StierNaam"}
- Dier overslaan: {"type": "skip_animal", "animal_id": "NL123456789"}
- Rapport titel: {"type": "report_setting", "setting": "title", "value": "Mijn Rapport"}
- Herbereken: {"type": "recalculate"}

Velden voor threshold:
- cell_count_threshold (celgetal)
- insemination_threshold (inseminaties)
- vaars_lactation_threshold (vaarzen lactatiewaarde)
- koe_lactation_threshold (koeien lactatiewaarde)
- inbreeding_threshold (inteelt %)

Antwoord ALTIJD in het Nederlands. Wees vriendelijk en bondig."""


class ChatInterpreter:
    def __init__(self, client, animals_df, advice_result, session_state):
        self.client = client
        self.animals_df = animals_df
        self.advice_result = advice_result
        self.session_state = session_state

    def process_user_message(self, user_message):
        """
        Verwerk een gebruikersbericht.

        Returns:
            Tuple (response_text: str, changes: list)
        """
        context = self._build_context()

        messages = []

        # Voeg laatste 8 berichten uit history toe (context)
        history = self.session_state.get('chat_history', [])
        for msg in history[-8:]:
            if msg['role'] in ('user', 'assistant'):
                messages.append({'role': msg['role'], 'content': msg['content']})

        # Voeg context toe als system-bericht variant
        full_user_message = f"""CONTEXT:
{context}

GEBRUIKERSVRAAG: {user_message}"""

        messages.append({'role': 'user', 'content': full_user_message})

        try:
            response = self.client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=600,
                system=SYSTEM_PROMPT,
                messages=messages,
            )
            assistant_text = response.content[0].text
        except Exception as e:
            assistant_text = f"Er is een fout opgetreden bij het verwerken van je vraag: {str(e)}"
            return assistant_text, []

        # Extraheer en pas wijzigingen toe
        changes = self._extract_changes(assistant_text)

        for change in changes:
            self._apply_change(change)

        return assistant_text, changes

    def _build_context(self):
        """Bouw context op voor de AI."""
        settings = self.session_state.get('default_settings', {})
        overrides = self.session_state.get('overrides', {})

        context_parts = [
            f"INSTELLINGEN:",
            f"- Vaars lactatiewaarde < {settings.get('vaars_lactation_threshold', 92)} = BWB",
            f"- Koe lactatiewaarde < {settings.get('koe_lactation_threshold', 98)} = BWB",
            f"- Inseminaties >= {settings.get('insemination_threshold', 3)} = BWB",
            f"- Celgetal > {settings.get('cell_count_threshold', 300)} = BWB",
            f"- Inteelt > {settings.get('inbreeding_threshold', 12.5)}% = BWB",
        ]

        if settings.get('custom_requests'):
            context_parts.append(f"- Speciale verzoeken: {settings['custom_requests']}")

        if self.animals_df is not None and not self.animals_df.empty:
            # Compact overzicht van dieren (max 20)
            display_cols = ['animal_id', 'animal_name', 'lactation_number',
                          'lactation_value', 'inseminations', 'cell_count']
            available_cols = [c for c in display_cols if c in self.animals_df.columns]
            context_parts.append(f"\nDIEREN ({len(self.animals_df)} totaal):")
            context_parts.append(self.animals_df[available_cols].head(20).to_string(index=False))

        if self.advice_result:
            context_parts.append(f"\nHUIDIGE ADVIEZEN ({len(self.advice_result)} dieren):")
            for animal_id, advice in list(self.advice_result.items())[:10]:
                context_parts.append(
                    f"- Dier {animal_id}: {advice.get('advice_type', '?')} "
                    f"(stier: {advice.get('recommended_bull', '?')}, "
                    f"reden: {advice.get('explanation', '?')})"
                )

        excluded = overrides.get('excluded_bulls', set())
        if excluded:
            context_parts.append(f"\nUITGESLOTEN STIEREN: {', '.join(excluded)}")

        return '\n'.join(context_parts)

    def _extract_changes(self, text):
        """Zoek JSON-blokken in de tekst."""
        pattern = r'```json\s*(.*?)\s*```'
        matches = re.findall(pattern, text, re.DOTALL)
        changes = []
        for match in matches:
            try:
                changes.append(json.loads(match))
            except json.JSONDecodeError:
                pass
        return changes

    def _apply_change(self, change):
        """Voer een wijziging uit op session_state."""
        change_type = change.get('type')

        if change_type == 'threshold':
            field = change.get('field', '')
            value = change.get('value')
            if field and value is not None:
                if 'default_settings' in self.session_state:
                    if field in self.session_state['default_settings']:
                        self.session_state['default_settings'][field] = value

        elif change_type == 'exclude_bull':
            bull_name = change.get('bull_name', '')
            if bull_name and 'overrides' in self.session_state:
                excluded = self.session_state['overrides'].get('excluded_bulls', set())
                excluded.add(bull_name)
                self.session_state['overrides']['excluded_bulls'] = excluded

        elif change_type == 'skip_animal':
            animal_id = str(change.get('animal_id', ''))
            if animal_id and 'overrides' in self.session_state:
                skipped = self.session_state['overrides'].get('skip_animals', set())
                skipped.add(animal_id)
                self.session_state['overrides']['skip_animals'] = skipped

        elif change_type == 'report_setting':
            setting = change.get('setting', '')
            value = change.get('value', '')
            if setting and 'report_settings' in self.session_state:
                self.session_state['report_settings'][setting] = value
