"""Classify and extract mixed example documents using doc-type routing."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.ocr_service import classify_document_type, extract_document_by_type

EXAMPLES_DIR = Path(__file__).resolve().parents[1] / "uploads" / "examples"


async def _main() -> None:
    files = sorted([p for p in EXAMPLES_DIR.iterdir() if p.is_file()])
    if not files:
        print("No example files found")
        return

    for f in files:
        doc_type, conf, candidates = classify_document_type(str(f), f.name)
        print(f"---FILE--- {f.name}")
        print(json.dumps({"doc_type": doc_type, "classifier_confidence": conf, "candidates": candidates}, ensure_ascii=False))
        result = await extract_document_by_type(str(f), doc_type)
        preview = {
            "document_type": result.get("document_type"),
            "source": result.get("source"),
            "high_confidence": result.get("high_confidence"),
            "confidence": result.get("confidence"),
            "error": result.get("error"),
            "unclear_fields": result.get("unclear_fields"),
        }
        print(json.dumps(preview, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(_main())
