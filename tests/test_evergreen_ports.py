import unittest
from datetime import date
from pathlib import Path

from bs4 import BeautifulSoup
from etd_sync.evergreen import extract_etd


class EvergreenPortsTests(unittest.TestCase):
    def setUp(self):
        self.html = (Path(__file__).parent / 'fixtures' / 'evergreen_ports.html').read_text()

    def test_ports_and_etd_from_same_basic_table(self):
        result = extract_etd(self.html)
        self.assertEqual(result['etd'], date(2026, 11, 21))
        self.assertEqual(result['raw'], 'NOV-21-2026')
        self.assertEqual((result['pol'], result['pod']), ('SHANGHAI', 'LAEM CHABANG'))
        self.assertEqual((result['pol_raw'], result['pod_raw']), ('SHANGHAI (CN)', 'LAEM CHABANG (TH)'))
        self.assertEqual(result['warnings'], [])

    def test_missing_or_empty_ports_return_none_and_warning(self):
        for field in ('pol', 'pod'):
            name = 'SHANGHAI (CN)' if field == 'pol' else 'LAEM CHABANG (TH)'
            with self.subTest(field=field):
                result = extract_etd(self.html.replace(name, ''))
                self.assertIsNone(result[field])
                self.assertEqual(len(result['warnings']), 1)
                self.assertEqual(result['etd'], date(2026, 11, 21))
        soup = BeautifulSoup(self.html, 'html.parser')
        soup.select_one('#basic').find(string='Port of Discharge').find_parent('tr').decompose()
        result = extract_etd(str(soup))
        self.assertIsNone(result['pod'])
        self.assertIsNone(result['pod_raw'])
        self.assertEqual(len(result['warnings']), 1)
        self.assertNotEqual(result['pod'], 'UNRELATED PORT')

    def test_country_suffix_only_and_whitespace_normalization(self):
        html = self.html.replace('SHANGHAI (CN)', '  PORT (INNER)  (CN)  ').replace('LAEM CHABANG (TH)', 'LAEM\n CHABANG （TH）')
        result = extract_etd(html)
        self.assertEqual(result['pol'], 'PORT (INNER)')
        self.assertEqual(result['pod'], 'LAEM CHABANG')
        result = extract_etd(self.html.replace('LAEM CHABANG (TH)', 'PORT (EAST)'))
        self.assertEqual(result['pod'], 'PORT (EAST)')

    def test_real_discharge_name_spans_blank_columns_without_covering_dates(self):
        result = extract_etd(self.html.replace('SHANGHAI (CN)', 'QINGDAO, CHINA (CN)'))
        self.assertEqual(result['pol'], 'QINGDAO')
        self.assertEqual(result['pol_raw'], 'QINGDAO, CHINA (CN)')
        result = extract_etd(self.html.replace('LAEM CHABANG (TH)', 'PASIR GUDANG, MALAYSIA (MY)'))
        self.assertEqual(result['pod'], 'PASIR GUDANG')
        # A port name merged over the arrival date remains unsafe even at correct total width.
        invalid = self.html.replace('colspan="4">LAEM CHABANG', 'colspan="5">LAEM CHABANG').replace(
            '<td>NOV-29-2026</td>', '')
        with self.assertRaises(ValueError):
            extract_etd(invalid)

    def test_duplicate_loading_or_unloading_rows_fail_even_when_identical(self):
        for label in ('Port of Loading', 'Port of Discharge'):
            soup = BeautifulSoup(self.html, 'html.parser')
            row = soup.select_one('#basic').find(string=label).find_parent('tr')
            row.insert_after(BeautifulSoup(str(row), 'html.parser').tr)
            with self.subTest(label=label), self.assertRaises(ValueError):
                extract_etd(str(soup))

    def test_etd_header_ambiguity_empty_or_invalid_date_fails(self):
        for html in (
            self.html.replace('Estimated On Board Date', 'Estimated Departure Date'),
            self.html.replace('Estimated Departure Date', 'Other Date'),
            self.html.replace('NOV-21-2026', ''),
            self.html.replace('NOV-21-2026', '2026-02-30'),
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                extract_etd(html)

    def test_port_merge_and_wrong_width_fail(self):
        for html in (
            self.html.replace('<td colspan="4">LAEM CHABANG', '<td colspan="4" rowspan="2">LAEM CHABANG'),
            self.html.replace('<td colspan="4">LAEM CHABANG', '<td colspan="2">LAEM CHABANG'),
            self.html.replace('<td colspan="4">LAEM CHABANG', '<td colspan="3">LAEM CHABANG'),
            self.html.replace('<td>SHANGHAI', '<td colspan="0">SHANGHAI'),
            self.html.replace('<td>SHANGHAI', '<td colspan="bad">SHANGHAI'),
        ):
            with self.subTest(html=html), self.assertRaises(ValueError):
                extract_etd(html)

    def test_labels_accept_case_and_linebreaks(self):
        html = self.html.replace('Port of Loading', ' port OF\n loading ').replace(
            'Port of Discharge', ' PORT of Discharge ').replace('Estimated Departure Date', 'Estimated\nDeparture Date')
        self.assertEqual(extract_etd(html)['pod'], 'LAEM CHABANG')
