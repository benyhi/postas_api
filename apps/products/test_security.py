from django.test import SimpleTestCase

from apps.products.views import _spreadsheet_safe


class SpreadsheetSafetyTests(SimpleTestCase):
    def test_formula_prefixes_are_neutralized(self):
        for value in ('=cmd()', '+SUM(A1:A2)', '-1+2', '@IMPORT', '  =cmd()'):
            with self.subTest(value=value):
                self.assertTrue(_spreadsheet_safe(value).startswith(chr(39)))

    def test_normal_text_is_preserved(self):
        self.assertEqual(_spreadsheet_safe('Yerba mate'), 'Yerba mate')
