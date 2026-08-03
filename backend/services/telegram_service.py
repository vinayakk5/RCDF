"""
Telegram bot webhook handler.
Receives bill photos from brokers, runs OCR, saves to DB, confirms back.
"""
import logging, os, httpx
from pathlib import Path
from datetime import date

log = logging.getLogger(__name__)

async def handle_telegram_update(payload: dict, db) -> None:
    """Main entry point called from FastAPI webhook route."""
    msg = payload.get("message") or payload.get("channel_post")
    if not msg:
        return

    chat_id   = str(msg["chat"]["id"])
    chat_name = msg["chat"].get("title") or msg["chat"].get("first_name", "Unknown")

    from database import get_settings
    settings = get_settings()

    if msg.get("photo"):
        file_id = msg["photo"][-1]["file_id"]   # largest resolution
        await process_image(chat_id, chat_name, file_id, "image", db, settings)

    elif msg.get("document"):
        doc = msg["document"]
        if doc.get("mime_type") == "application/pdf":
            await process_image(chat_id, chat_name, doc["file_id"], "pdf", db, settings)
        else:
            await send_tg_message(chat_id, "Please send bill as a photo or PDF.", settings.telegram_token)

    elif msg.get("text", "").strip().upper() == "STATUS":
        await send_status(chat_id, chat_name, db, settings)


async def download_tg_file(file_id: str, token: str, dest_dir: str) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}")
        file_path = r.json()["result"]["file_path"]
        url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        img_r = await client.get(url)
        ext = Path(file_path).suffix or ".jpg"
        dest = Path(dest_dir) / f"tg_{file_id}{ext}"
        dest.write_bytes(img_r.content)
        return str(dest)


async def process_image(chat_id, chat_name, file_id, ftype, db, settings):
    from services.ocr_service import extract_bill
    from models import Bill, Broker, BillSource, OcrSource, BillStatus
    from sqlalchemy import select

    await send_tg_message(chat_id, "Processing your bill... please wait.", settings.telegram_token)

    try:
        # Download image
        dest_dir = os.path.join(settings.upload_dir, "bills")
        image_path = await download_tg_file(file_id, settings.telegram_token, dest_dir)

        # Run OCR
        extracted = await extract_bill(image_path)

        # Find broker by telegram chat ID
        broker = db.execute(
            select(Broker).where(Broker.telegram_chat_id == chat_id)
        ).scalar_one_or_none()

        # Create bill record
        bill = Bill(
            broker_id        = broker.id if broker else None,
            broker_name      = broker.name if broker else chat_name,
            source           = BillSource.telegram,
            telegram_msg_id  = file_id,
            image_path       = image_path,
            vehicle_number   = extracted.get("vehicle_number"),
            material_name    = extracted.get("material_type"),
            qty_mt           = extracted.get("quantity_mt"),
            rate_per_mt      = extracted.get("rate_per_mt"),
            total_amount     = extracted.get("total_amount"),
            bill_date        = extracted.get("bill_date"),
            bill_number      = extracted.get("bill_number"),
            plant_name       = extracted.get("destination_plant"),
            ocr_source       = OcrSource.gemini if extracted.get("source") == "gemini" else OcrSource.paddle,
            ocr_confidence   = extracted.get("confidence") or extracted.get("ocr_confidence"),
            ocr_raw_text     = extracted.get("raw_text", ""),
            is_handwritten   = extracted.get("is_handwritten", False),
            validation_amount   = extracted.get("validation_amount", False),
            validation_vehicle  = extracted.get("validation_vehicle", False),
            validation_material = extracted.get("validation_material", False),
            status           = BillStatus.flagged if extracted.get("needs_review") else BillStatus.pending,
        )
        db.add(bill)
        db.commit()
        db.refresh(bill)

        # Confirmation message
        if extracted.get("needs_review"):
            reply = (
                f"Bill received (ID: {bill.id}) — needs review.\n"
                f"Some fields unclear or validation failed.\n"
                f"Errors: {', '.join(extracted.get('validation_errors', ['low confidence']))}\n"
                f"Our team will verify in the dashboard."
            )
        else:
            qty   = extracted.get('quantity_mt', '?')
            rate  = extracted.get('rate_per_mt', '?')
            veh   = extracted.get('vehicle_number', '?')
            mat   = extracted.get('material_type', '?')
            total = extracted.get('total_amount', '?')
            reply = (
                f"Bill saved (ID: {bill.id})\n\n"
                f"Material: {mat}\n"
                f"Qty: {qty} MT\n"
                f"Rate: ₹{rate}/MT\n"
                f"Vehicle: {veh}\n"
                f"Total: ₹{total:,.0f}\n\n"
                f"Reply CORRECT if anything looks wrong."
            )

        await send_tg_message(chat_id, reply, settings.telegram_token)

    except Exception as e:
        log.error(f"Error processing Telegram bill: {e}", exc_info=True)
        await send_tg_message(
            chat_id,
            "Sorry, we could not process this bill. Please try again or upload via the web dashboard.",
            settings.telegram_token
        )


async def send_tg_message(chat_id: str, text: str, token: str) -> None:
    if not token:
        log.warning("Telegram token not set — skipping message send")
        return
    async with httpx.AsyncClient() as client:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text}
        )


async def send_status(chat_id, chat_name, db, settings):
    from models import Bill
    from sqlalchemy import select, func as sqlfunc
    total = db.execute(select(sqlfunc.count(Bill.id)).where(Bill.broker_name == chat_name)).scalar()
    await send_tg_message(chat_id, f"You have submitted {total} bills this cycle.", settings.telegram_token)
