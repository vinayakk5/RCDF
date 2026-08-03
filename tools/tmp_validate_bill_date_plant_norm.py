import sys, json
from pathlib import Path
sys.path.insert(0, str(Path("backend").resolve()))
from services.ocr_service import _normalize_bill_date_text, _normalize_bill_destination_plant
from main import _parse_optional_date

samples = ["01/04/2026", "01-04-26", "01 Apr 2026", "01-Apr-26", "Bill Date: 31.03.26", "date- 2026-04-01"]
plant_samples = ["KALADERA", "CFP NADBAI", "Kekri", "Jodhpur", None]

out = {
    "bill_date_normalization": {s: _normalize_bill_date_text(s) for s in samples},
    "db_date_parse": {s: str(_parse_optional_date(s)) if _parse_optional_date(s) else None for s in samples},
    "plant_normalization": {str(s): _normalize_bill_destination_plant(s) for s in plant_samples},
}
print(json.dumps(out, indent=2))
