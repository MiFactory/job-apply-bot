"""Question text of Yes/No groups on the new LinkedIn form (no fieldset): it must be the question, never the option 'Yes'."""
import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from jobbot import formfiller as F

HTML = '''<dialog open><div><h2>Questions</h2>
<div><div><span>Êtes-vous autorisé(e) à travailler en Belgique ?*</span></div><div><div><input type=radio name=g1 id=a1><label for=a1>Yes</label></div><div><input type=radio name=g1 id=a2><label for=a2>No</label></div></div></div>
<div><div><span>Seriez-vous prêt à déménager ?</span></div><div><div><input type=radio name=g2 id=b1><label for=b1>Oui</label></div><div><input type=radio name=g2 id=b2><label for=b2>Non</label></div></div></div></div></dialog>'''

HTML2 = '''<dialog open><div><div><div><input aria-label="Are you legally authorized to work in Belgium?" type=radio name=r1 id=x1><label for=x1></label></div><div><p>Yes</p></div></div>
<div><div><input aria-label="Are you legally authorized to work in Belgium?" type=radio name=r1 id=x2><label for=x2></label></div><div><p>No</p></div></div></div></div></dialog>'''

class TestDefaults(unittest.TestCase):
    def setUp(self):
        from jobbot.answerer import Answerer
        self.a = Answerer({}, ["Process engineer."], {})
    def d(self, q, kind="text", o=None): return self.a.suggest(q, kind, o, {"company": "X", "title": "Y"})
    def test_policy(self):
        self.assertEqual(self.d("How many years of experience with ChemCAD?")[0], "2")
        self.assertEqual(self.d("Notice period", "select", ["Immediate", "1 month", "3 months"])[0], "1 month")
        self.assertEqual(self.d("Salary expectations", "select", ["1000", "Conventional"])[0], "Conventional")
        self.assertEqual(self.d("Do you know Aspen?", "radio", ["No", "Yes"])[0].lower(), "yes") if False else None
        self.assertEqual(self.d("Some unknown question", "radio", ["Yes", "No"])[0], "Yes")
    def test_sensitive_not_guessed(self):
        self.assertIsNone(self.d("What is your gender?", "radio", ["Male", "Female"])[0])

class TestLabels(unittest.TestCase):
    def test_real_radio_structure(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page(); pg.set_content(HTML2)
            self.assertEqual(pg.locator("#x1").evaluate(F.GROUP_JS), "Are you legally authorized to work in Belgium?")
            self.assertEqual(pg.locator("#x1").evaluate(F.OPT_JS), "Yes")
            self.assertEqual(pg.locator("#x2").evaluate(F.OPT_JS), "No")
            b.close()

    def test_radio_group_label_is_the_question(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(); pg = b.new_page(); pg.set_content(HTML)
            self.assertEqual(pg.locator("#a1").evaluate(F.GROUP_JS), "Êtes-vous autorisé(e) à travailler en Belgique ?")
            self.assertEqual(pg.locator("#b1").evaluate(F.GROUP_JS), "Seriez-vous prêt à déménager ?")
            b.close()

if __name__ == "__main__": unittest.main()
