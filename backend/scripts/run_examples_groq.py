"""Run Groq extractor `extract_with_groq` on all files in `uploads/examples` and print JSON results.

Uses backend/venv Python environment.
"""
import asyncio
import json
import sys
from pathlib import Path

# ensure backend package importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from services.ocr_service import extract_with_groq, _convert_pdf_first_page_to_image
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
        input_path = str(f)
        converted = None
        if f.suffix.lower() == '.pdf':
            try:
                converted = _convert_pdf_first_page_to_image(str(f))
                if converted:
                    input_path = converted
                else:
                    print("PDF conversion to image failed for", f.name)
            except Exception as e:
                print("PDF conversion error:", e)

        res = asyncio.run(extract_with_groq(input_path))
        print(json.dumps(res, indent=2, ensure_ascii=False))
        # cleanup converted image
        if converted:
            try:
                Path(converted).unlink(missing_ok=True)
            except Exception:
                pass
    except Exception as e:
        print("ERROR while processing", f.name)
        print(type(e).__name__, str(e))
        continue

print("Done")
