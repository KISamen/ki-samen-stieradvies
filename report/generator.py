"""
PDF-rapportgenerator voor stieradvies met ReportLab.
"""
import io
import os
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)


BRAND_GREEN = colors.HexColor('#1a7a4a')
BRAND_LIGHT = colors.HexColor('#e8f5ee')
BRAND_DARK = colors.HexColor('#0d3d25')
HEADER_GRAY = colors.HexColor('#f0f0f0')
ACCENT_RED = colors.HexColor('#c0392b')
ACCENT_BLUE = colors.HexColor('#2980b9')


class ReportGenerator:
    def __init__(self, company_name, animals_df, advice_result, report_settings, default_settings=None):
        self.company_name = company_name
        self.animals_df = animals_df
        self.advice_result = advice_result
        self.settings = report_settings
        self.default_settings = default_settings or {}
        self.styles = getSampleStyleSheet()
        self._setup_styles()

    def _setup_styles(self):
        """Definieer custom stijlen."""
        self.title_style = ParagraphStyle(
            'KISamenTitle',
            parent=self.styles['Heading1'],
            fontSize=22,
            textColor=BRAND_DARK,
            spaceAfter=0.3 * cm,
            fontName='Helvetica-Bold',
        )
        self.heading2_style = ParagraphStyle(
            'KISamenH2',
            parent=self.styles['Heading2'],
            fontSize=14,
            textColor=BRAND_GREEN,
            spaceAfter=0.2 * cm,
            spaceBefore=0.5 * cm,
            fontName='Helvetica-Bold',
        )
        self.normal_style = ParagraphStyle(
            'KISamenNormal',
            parent=self.styles['Normal'],
            fontSize=9,
            leading=14,
        )
        self.caption_style = ParagraphStyle(
            'KISamenCaption',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.gray,
        )

    def generate_pdf_bytes(self):
        """Genereer PDF en retourneer als bytes-object."""
        buffer = io.BytesIO()
        self._build_pdf(buffer)
        buffer.seek(0)
        return buffer.read()

    def generate_pdf(self, output_path='rapport.pdf'):
        """Genereer PDF naar bestand."""
        with open(output_path, 'wb') as f:
            f.write(self.generate_pdf_bytes())

    def _build_pdf(self, buffer):
        """Bouw de volledige PDF op."""
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=1.5 * cm,
            leftMargin=1.5 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
        )

        elements = []

        # TITELPAGINA
        elements += self._build_title_page()

        # SAMENVATTING
        elements.append(Spacer(1, 0.5 * cm))
        elements += self._build_summary()

        # GEBRUIKTE REGELS
        elements += self._build_rules_section()

        # ADVIESLIJST
        elements += self._build_advice_table()

        # AANDACHTSPUNTEN
        elements += self._build_attention_points()

        # DISCLAIMER
        elements.append(PageBreak())
        elements += self._build_disclaimer()

        doc.build(elements)

    def _build_title_page(self):
        elements = []

        # Logo (indien beschikbaar)
        logo_path = self.settings.get('logo_path')
        if logo_path and os.path.exists(logo_path):
            try:
                logo = Image(logo_path, width=4 * cm, height=4 * cm)
                elements.append(logo)
                elements.append(Spacer(1, 0.5 * cm))
            except Exception:
                pass

        # Groene header balk
        header_data = [[f'  KI Samen Stieradvies']]
        header_table = Table(header_data, colWidths=[18 * cm])
        header_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BRAND_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 16),
            ('TOPPADDING', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 0.3 * cm))

        elements.append(Paragraph(self.company_name, self.title_style))
        report_title = self.settings.get('title', 'Stieradvies')
        elements.append(Paragraph(report_title, self.heading2_style))
        elements.append(Paragraph(
            f'Datum: {datetime.now().strftime("%d %B %Y")}',
            self.normal_style,
        ))
        elements.append(Spacer(1, 0.3 * cm))

        return elements

    def _build_summary(self):
        elements = [Paragraph('Samenvatting', self.heading2_style)]

        total = len(self.animals_df) if self.animals_df is not None else 0
        bwb = sum(1 for a in self.advice_result.values() if a.get('advice_type') == 'belgian_witblauw')
        milk = sum(1 for a in self.advice_result.values() if a.get('advice_type') == 'milking_sire')
        genetic = sum(1 for a in self.advice_result.values() if a.get('advice_type') == 'genetic_merit')
        skipped = sum(1 for a in self.advice_result.values() if a.get('advice_type') == 'overgeslagen')

        summary_data = [
            ['Aantal geanalyseerde dieren', str(total)],
            ['Belgisch Witblauw advies', str(bwb)],
            ['Melkstier advies', str(milk)],
            ['Genetische verdienste advies', str(genetic)],
            ['Overgeslagen', str(skipped)],
        ]

        table = Table(summary_data, colWidths=[10 * cm, 4 * cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), BRAND_LIGHT),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.white, HEADER_GRAY]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

        return elements

    def _build_rules_section(self):
        elements = [Paragraph('Gebruikte Drempels & Regels', self.heading2_style)]

        s = self.default_settings
        rules_data = [
            ['Regel', 'Drempel', 'Advies'],
            ['Vaars lactatiewaarde', f'< {s.get("vaars_lactation_threshold", 92)}', 'Belgisch Witblauw'],
            ['Koe lactatiewaarde', f'< {s.get("koe_lactation_threshold", 98)}', 'Belgisch Witblauw'],
            ['Inseminaties', f'>= {s.get("insemination_threshold", 3)}', 'Belgisch Witblauw'],
            ['Celgetal', f'> {s.get("cell_count_threshold", 300)}', 'Belgisch Witblauw'],
            ['Inteelt %', f'> {s.get("inbreeding_threshold", 12.5)}%', 'Belgisch Witblauw'],
        ]

        table = Table(rules_data, colWidths=[8 * cm, 4 * cm, 6 * cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ]))
        elements.append(table)

        custom = s.get('custom_requests', '')
        if custom:
            elements.append(Spacer(1, 0.2 * cm))
            elements.append(Paragraph(f'<b>Speciale verzoeken:</b> {custom}', self.normal_style))

        return elements

    def _build_advice_table(self):
        elements = [Paragraph('Advies per Dier', self.heading2_style)]

        if self.animals_df is None or self.animals_df.empty:
            elements.append(Paragraph('Geen diergegevens beschikbaar.', self.normal_style))
            return elements

        header = ['Dier-ID', 'Naam', 'Lakt.\nnr.', 'Lakt.\nwrd.', 'Cel\ngetal', 'Ins.', 'Advies', 'Stier', 'Score', 'Reden']
        rows = [header]

        for _, row in self.animals_df.iterrows():
            animal_id = str(row.get('animal_id', '-'))
            advice = self.advice_result.get(animal_id, {})

            advice_type = advice.get('advice_type', '-')
            advice_labels = {
                'belgian_witblauw': 'BWB',
                'milking_sire': 'Melk',
                'genetic_merit': 'Gen.',
                'overgeslagen': 'Skip',
            }

            lakt_nr = row.get('lactation_number', '-')
            lakt_wrd = row.get('lactation_value', '-')
            cell = row.get('cell_count', '-')
            ins = row.get('inseminations', '-')

            try:
                lakt_wrd = f'{float(lakt_wrd):.1f}'
            except (TypeError, ValueError):
                lakt_wrd = str(lakt_wrd)

            explanation = advice.get('explanation', '-')
            if len(explanation) > 35:
                explanation = explanation[:33] + '...'

            rows.append([
                animal_id[:12],
                str(row.get('animal_name', '-'))[:10],
                str(lakt_nr),
                lakt_wrd,
                str(cell),
                str(ins),
                advice_labels.get(advice_type, advice_type[:4]),
                str(advice.get('recommended_bull', '-'))[:10],
                f'{advice.get("confidence_score", 0):.2f}',
                explanation,
            ])

        col_widths = [2.2*cm, 1.8*cm, 1*cm, 1.1*cm, 1*cm, 0.8*cm, 1.2*cm, 2*cm, 1*cm, 5.2*cm]

        table = Table(rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.lightgrey),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (2, 0), (8, -1), 'CENTER'),
            ('WORDWRAP', (0, 0), (-1, -1), True),
        ]))
        elements.append(table)

        return elements

    def _build_attention_points(self):
        elements = [Paragraph('Aandachtspunten', self.heading2_style)]

        points = []

        # Hoog celgetal
        if self.animals_df is not None and 'cell_count' in self.animals_df.columns:
            cell_threshold = self.default_settings.get('cell_count_threshold', 300)
            high_cell = self.animals_df[
                pd.to_numeric(self.animals_df['cell_count'], errors='coerce') > cell_threshold
            ]
            if not high_cell.empty:
                ids = ', '.join(high_cell['animal_id'].astype(str).head(5).tolist())
                points.append(f'• {len(high_cell)} dier(en) met hoog celgetal (> {cell_threshold}): {ids}')

        # Uitgesloten stieren
        # (wordt doorgegeven via report_settings indien relevant)

        # Overgeslagen dieren
        skipped = [aid for aid, adv in self.advice_result.items()
                  if adv.get('advice_type') == 'overgeslagen']
        if skipped:
            points.append(f'• {len(skipped)} dier(en) overgeslagen: {", ".join(skipped[:5])}')

        if not points:
            points.append('• Geen bijzonderheden.')

        for point in points:
            elements.append(Paragraph(point, self.normal_style))

        return elements

    def _build_disclaimer(self):
        elements = [Paragraph('Disclaimer', self.heading2_style)]

        footer_text = self.settings.get('footer_text', '')
        disclaimer_text = (
            'Dit stieradvies is gegenereerd op basis van melkcontrolegegevens en vooraf ingestelde '
            'criteria. Het advies is bedoeld als ondersteuning en vervangt geen persoonlijke '
            'fokbegeleiding door een erkende fokadviseur. KI Samen is niet aansprakelijk voor '
            'beslissingen die op basis van dit rapport worden genomen.'
        )
        if footer_text:
            disclaimer_text += f'\n\n{footer_text}'

        elements.append(Paragraph(disclaimer_text, self.normal_style))
        elements.append(Spacer(1, 0.5 * cm))
        elements.append(Paragraph(
            f'Gegenereerd op {datetime.now().strftime("%d-%m-%Y om %H:%M")} | KI Samen Stieradvies App',
            self.caption_style,
        ))

        return elements
