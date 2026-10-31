"""Offline test of the form filler against tests/form_fixture.html (needs: pip install playwright && playwright install chromium).
Run:  python tests/test_formfiller.py"""
import sys, pathlib, json
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from jobbot.formfiller import Filler
from jobbot import profile as P

prof = json.loads((ROOT / "examples/profile.example.json").read_text())
prof.update(P.DEFAULT_PROFILE | {k: v for k, v in prof.items()})
crit = json.loads((ROOT / "examples/criteria.example.json").read_text())
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page(); pg.goto((ROOT / "tests/form_fixture.html").as_uri())
    f = Filler(prof, crit, interactive=False, motivation={"en": "Hello {company}, I applied for {title}. {full_name}"})
    f.ctx = {"title": "Account Manager", "company": "ACME", "lang": "en"}
    n = f.fill(pg.locator("div[role=dialog]"))
    vals = pg.evaluate("[a.value, b.value, c.value, s1.checked, s2.checked, d.value, e.value, m.value]")
    print("fields filled:", n, vals)
    assert vals[0] == "Alex" and vals[1] == "400000000" and vals[2] == "3" and vals[4] is True and vals[5] == "Professional" and vals[6] == "48000"
    assert "ACME" in vals[7] and "Alex Martin" in vals[7]
    print("OK")
