"""Run the whole test suite:  python tests/run_all.py   (add --fast to skip the browser tests)"""
import sys, unittest, pathlib
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
mods = ["tests.test_unit", "tests.test_cli", "tests.test_gui", "tests.test_answerer", "tests.test_labels"] + ([] if "--fast" in sys.argv else ["tests.test_e2e"])
suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(m) for m in mods)
res = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if res.wasSuccessful() else 1)
