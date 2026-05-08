"""
PDF-rapportgenerator voor KI Samen Stieradvies.
Huisstijl: donkergroen (#1a7a4a), wit, lichtgroen accent.
"""
import io
import os
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

BRAND_GREEN = colors.HexColor('#1a7a4a')
BRAND_LIGHT = colors.HexColor('#e8f5ee')
BRAND_DARK  = colors.HexColor('#0d3d25')
GRAY_ROW    = colors.HexColor('#f7f7f7')
RED_BWB     = colors.HexColor('#c0392b')
GREEN_FOK   = colors.HexColor('#1a7a4a')
ORANGE_WARN = colors.HexColor('#e67e22')

_ADVICE_LABELS = {
    'belgian_witblauw': 'BWB',
    'fokstier':         'Fokstier',
    'geen_advies':      'Geen advies',
    'onvoldoende_data': 'Data?',
    'overgeslagen':     'Overgeslagen',
    'milking_sire':     'Fokstier',
    'genetic_merit':    'Fokstier',
}
_ADVICE_COLORS = {
    'BWB':       RED_BWB,
    'Fokstier':  GREEN_FOK,
}


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
        self.title_style = ParagraphStyle(
            'KISamenTitle',
            parent=self.styles['Heading1'],
            fontSize=20,
            textColor=colors.white,
            spaceAfter=0,
            fontName='Helvetica-Bold',
        )
        self.h2 = ParagraphStyle(
            'KISamenH2',
            parent=self.styles['Heading2'],
            fontSize=11,
            textColor=BRAND_GREEN,
            spaceAfter=0.2 * cm,
            spaceBefore=0.4 * cm,
            fontName='Helvetica-Bold',
        )
        self.normal = ParagraphStyle(
            'KISamenNormal',
            parent=self.styles['Normal'],
            fontSize=8.5,
            leading=13,
        )
        self.caption = ParagraphStyle(
            'KISamenCaption',
            parent=self.styles['Normal'],
            fontSize=7.5,
            textColor=colors.gray,
        )
        self.small = ParagraphStyle(
            'KISamenSmall',
            parent=self.styles['Normal'],
            fontSize=7,
            leading=10,
        )

    def generate_pdf_bytes(self) -> bytes:
        buffer = io.BytesIO()
        self._build_pdf(buffer)
        buffer.seek(0)
        return buffer.read()

    def _build_pdf(self, buffer):
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=1.5 * cm,
            leftMargin=1.5 * cm,
            topMargin=1.5 * cm,
            bottomMargin=1.5 * cm,
            title=f"KI Samen Stieradvies – {self.company_name}",
            author="KI Samen",
        )

        elements = []
        elements += self._header_block()
        elements.append(Spacer(1, 0.3 * cm))
        elements += self._summary_block()
        elements += self._rules_block()
        elements += self._advice_table()
        elements += self._attention_block()
        elements.append(Spacer(1, 0.5 * cm))
        elements += self._footer_block()

        doc.build(elements)

    # ── Onderdelen ────────────────────────────────────────────────────────────

    def _header_block(self):
        """Groene titelbalk met bedrijfsnaam en datum."""
        datum = datetime.now().strftime('%d %B %Y')
        titel = self.settings.get('title', 'Stieradvies')

        header_data = [[
            Paragraph(f'KI Samen Stieradvies', self.title_style),
            Paragraph(
                f'<font color="white"><b>{self.company_name}</b> — {titel}<br/>'
                f'<font size="8">{datum}</font></font>',
                ParagraphStyle('hdr_right', parent=self.styles['Normal'],
                               fontSize=10, textColor=colors.white, alignment=2),
            ),
        ]]
        t = Table(header_data, colWidths=[12 * cm, 15 * cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BRAND_GREEN),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('LEFTPADDING', (0, 0), (0, -1), 12),
            ('RIGHTPADDING', (-1, 0), (-1, -1), 12),
        ]))
        return [t]

    def _summary_block(self):
        vals = list(self.advice_result.values())
        total = len(self.animals_df) if self.animals_df is not None else 0
        bwb   = sum(1 for a in vals if _ADVICE_LABELS.get(a.get('advice_type', ''), '') == 'BWB')
        fok   = sum(1 for a in vals if _ADVICE_LABELS.get(a.get('advice_type', ''), '') == 'Fokstier')
        geen  = sum(1 for a in vals if a.get('advice_type') in ('geen_advies', 'overgeslagen'))
        warn  = sum(1 for a in vals if a.get('advice_type') == 'onvoldoende_data')
        no_bull = sum(1 for a in vals if not a.get('recommended_bull')
                      and a.get('advice_type') not in ('geen_advies', 'overgeslagen', 'onvoldoende_data'))

        data = [
            ['Totaal dieren', str(total),
             'Belgisch Witblauw', str(bwb),
             'Fokstier', str(fok),
             'Geen/overgeslagen', str(geen),
             'Data ontbreekt', str(warn),
             'Geen stier gevonden', str(no_bull)],
        ]
        col_w = [3.5 * cm, 1.2 * cm] * 6
        t = Table(data, colWidths=col_w)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (1, 0), BRAND_DARK),
            ('BACKGROUND', (2, 0), (3, 0), RED_BWB),
            ('BACKGROUND', (4, 0), (5, 0), GREEN_FOK),
            ('BACKGROUND', (6, 0), (-1, 0), colors.HexColor('#7f8c8d')),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.white),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8.5),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('GRID', (0, 0), (-1, -1), 0.3, colors.white),
            ('ROUNDEDCORNERS', [3]),
        ]))
        return [t, Spacer(1, 0.15 * cm)]

    def _rules_block(self):
        s = self.default_settings
        rules = [
            f"Vaars LW < {s.get('vaars_lactation_threshold', 92)} → BWB",
            f"Koe LW < {s.get('koe_lactation_threshold', 98)} → BWB",
            f"Ins. ≥ {s.get('insemination_threshold', 3)} → BWB",
            f"Celgetal > {s.get('cell_count_threshold', 300)} → BWB",
            f"Inteelt > {s.get('inbreeding_threshold', 12.5)}% → BWB",
        ]
        custom = s.get('custom_requests', '').strip()
        if custom:
            rules.append(f"Speciale wensen: {custom[:80]}")

        rule_text = '   |   '.join(rules)
        t = Table([[Paragraph(f'<b>Gebruikte drempels:</b>  {rule_text}', self.caption)]],
                  colWidths=[27 * cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), BRAND_LIGHT),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ]))
        return [t, Spacer(1, 0.2 * cm)]

    def _advice_table(self):
        elements = [Paragraph('Stieradvies per dier', self.h2)]

        if self.animals_df is None or self.animals_df.empty:
            return elements + [Paragraph('Geen diergegevens.', self.normal)]

        header = ['Dier-ID', 'Lakt.\nnr.', 'LW', 'Ins.', 'Cel\ngetal',
                  'Advies', 'Aanbevolen stier', 'Redenen']
        rows = [header]

        for _, row in self.animals_df.iterrows():
            aid = str(row.get('animal_id', '—'))
            adv = self.advice_result.get(aid, {})
            adv_type = adv.get('advice_type', '')
            label = _ADVICE_LABELS.get(adv_type, adv_type or '—')
            bull  = adv.get('recommended_bull') or '—'
            reasons = adv.get('reasons', [])
            reason_text = '; '.join(r for r in reasons if r)[:90]
            warnings = adv.get('warnings', [])
            if warnings and not adv.get('recommended_bull'):
                reason_text = (warnings[0] if warnings else '')[:90]

            lw  = _safe_fmt(row.get('lactation_value'), '.1f')
            ins = _safe_fmt(row.get('inseminations'))
            cel = _safe_fmt(row.get('cell_count'))
            lnr = _safe_fmt(row.get('lactation_number'))

            rows.append([aid[:14], lnr, lw, ins, cel, label, bull[:22], reason_text])

        # Kleur advies-kolom per type
        col_w = [3.2*cm, 1*cm, 1.2*cm, 1*cm, 1.2*cm, 1.8*cm, 4.5*cm, 12.1*cm]
        t = Table(rows, colWidths=col_w, repeatRows=1)

        style = [
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 7.5),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.HexColor('#cccccc')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, GRAY_ROW]),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (4, -1), 'CENTER'),
            ('ALIGN', (5, 0), (5, -1), 'CENTER'),
            ('WORDWRAP', (7, 0), (7, -1), True),
        ]
        # Kleur BWB-rijen rood, fokstier-rijen groen
        for i, data_row in enumerate(rows[1:], start=1):
            lbl = data_row[5]
            if lbl == 'BWB':
                style.append(('TEXTCOLOR', (5, i), (5, i), RED_BWB))
                style.append(('FONTNAME', (5, i), (5, i), 'Helvetica-Bold'))
            elif lbl == 'Fokstier':
                style.append(('TEXTCOLOR', (5, i), (5, i), GREEN_FOK))
                style.append(('FONTNAME', (5, i), (5, i), 'Helvetica-Bold'))

        t.setStyle(TableStyle(style))
        elements.append(t)
        return elements

    def _attention_block(self):
        elements = [Spacer(1, 0.3 * cm), Paragraph('Aandachtspunten', self.h2)]
        points = []

        if self.animals_df is not None and 'cell_count' in self.animals_df.columns:
            cell_thr = self.default_settings.get('cell_count_threshold', 300)
            high_cell = self.animals_df[
                pd.to_numeric(self.animals_df['cell_count'], errors='coerce') > cell_thr
            ]
            if not high_cell.empty:
                ids = ', '.join(high_cell['animal_id'].astype(str).head(8).tolist())
                points.append(f'• {len(high_cell)} dier(en) met celgetal > {cell_thr}: {ids}')

        no_bull = [(aid, adv) for aid, adv in self.advice_result.items()
                   if not adv.get('recommended_bull')
                   and adv.get('advice_type') not in ('geen_advies', 'overgeslagen', 'onvoldoende_data')]
        if no_bull:
            ids = ', '.join(aid for aid, _ in no_bull[:6])
            points.append(f'• {len(no_bull)} dier(en) zonder stieradvies (selectie heeft geen geschikte stier): {ids}')

        skipped = [aid for aid, adv in self.advice_result.items()
                   if adv.get('advice_type') in ('geen_advies', 'overgeslagen')]
        if skipped:
            points.append(f'• {len(skipped)} dier(en) overgeslagen (drachtig of handmatig): {", ".join(skipped[:6])}')

        if not points:
            points.append('• Geen bijzonderheden.')

        for p in points:
            elements.append(Paragraph(p, self.normal))
        return elements

    def _footer_block(self):
        footer = self.settings.get('footer_text', '')
        disclaimer = (
            'Dit stieradvies is gegenereerd op basis van melkcontrolegegevens en vooraf ingestelde criteria. '
            'Het advies ondersteunt maar vervangt geen persoonlijke fokbegeleiding. '
            'KI Samen is niet aansprakelijk voor beslissingen op basis van dit rapport.'
        )
        if footer:
            disclaimer += f'  |  {footer}'
        ts = datetime.now().strftime('%d-%m-%Y %H:%M')
        return [
            Paragraph(disclaimer, self.caption),
            Paragraph(f'Gegenereerd: {ts} | KI Samen Stieradvies', self.caption),
        ]


def _safe_fmt(val, fmt: str = '') -> str:
    if val is None:
        return '—'
    try:
        import math
        f = float(val)
        if math.isnan(f):
            return '—'
        if fmt:
            return f'{f:{fmt}}'
        return str(int(f)) if f == int(f) else str(f)
    except (TypeError, ValueError):
        s = str(val)
        return '—' if s in ('None', 'nan', '') else s
