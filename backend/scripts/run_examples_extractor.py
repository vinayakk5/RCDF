"""Run OCR router `extract_bill` on all files in `uploads/examples` and print JSON results.

This is a diagnostic script; adapters may error if API keys or native libs are missing.
"""
import asyncio
import json
import sys
from pathlib import Path

# ensure backend package importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from services.ocr_service import extract_bill
except Exception as e:
    print("IMPORT_ERROR", e)
    raise

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / 'uploads' / 'examples'

files = sorted([p for p in EXAMPLES_DIR.iterdir() if p.is_file()])
if not files:
    print("No example files found in", EXAMPLES_DIR)
    sys.exit(1)

for f in files:
    print("---FILE---", f.name)
    try:
        res = asyncio.run(extract_bill(str(f)))
        print(json.dumps(res, indent=2, ensure_ascii=False))
    except Exception as e:
        print("ERROR while processing", f.name)
        print(type(e).__name__, str(e))
        continue

print("Done")
