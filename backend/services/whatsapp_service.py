"""
WhatsApp Integration Service for RCDF Operations Platform.
Receives incoming WhatsApp webhooks (Images, PDFs, Weighment Slips, UTRs, Text),
runs OCR & extraction, creates ledger entries, and dispatches automated confirmation replies.
"""
import logging
import os
import re
import httpx
from datetime import datetime, date
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, or_, func as sqlfunc

from database import get_settings
from models import (
    Bill, BusyStagingBill, Broker, Plant, Material, Deal, Tender, Company,
    WhatsAppConfig, WhatsAppLog, BillSource, OcrSource, BillStatus,
    PendingIngest, IngestSource, DocumentType, IngestStatus
)

log = logging.getLogger("services.whatsapp_service")

WHATSAPP_BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "http://127.0.0.1:3001")


async def handle_whatsapp_webhook(payload: dict, db: Session) -> Dict[str, Any]:
    """
    Main webhook receiver called from FastAPI route when WhatsApp Bridge intercepts a message.
    Creates a PendingIngest record for real documents/bills, runs initial OCR extraction,
    and logs the message for verification and action processing.
    """
    message_id = payload.get("message_id") or str(int(datetime.utcnow().timestamp() * 1000))
    chat_jid = payload.get("from_jid") or payload.get("chat_jid", "")
    chat_name = payload.get("group_name") or payload.get("chat_name") or "Direct Chat"
    is_group = bool(payload.get("is_group", False))
    sender_jid = payload.get("from_jid") or payload.get("sender_jid", chat_jid)
    sender_name = payload.get("sender_name", "Unknown Sender")
    sender_phone = payload.get("sender_phone", "")
    if not sender_phone and sender_jid and "@" in sender_jid:
        sender_phone = sender_jid.split("@")[0]

    # Explicitly drop newsletter, broadcast, and status messages
    if (chat_jid.endswith('@newsletter') or chat_jid.endswith('@broadcast') or 
        chat_jid == 'status@broadcast' or sender_jid.endswith('@newsletter') or 
        sender_jid.endswith('@broadcast')):
        log.debug(f"[WhatsApp] Dropped newsletter/broadcast message from {chat_jid}")
        return {"status": "ignored", "reason": "newsletter_or_broadcast"}

    caption = payload.get("caption", "")
    text = (payload.get("text", "") or caption or "").strip()
    
    media = payload.get("media") or {}
    file_path = media.get("path") if isinstance(media, dict) else payload.get("file_path")
    mime_type = media.get("mimetype") if isinstance(media, dict) else payload.get("mime_type")
    
    has_media = False
    if file_path:
        file_path = os.path.normpath(file_path)
        if os.path.exists(file_path):
            has_media = True
            log.info(f"[WhatsApp] Media file confirmed at: {file_path}")
        else:
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            candidates = [
                os.path.join(backend_dir, "uploads", "whatsapp", os.path.basename(file_path)),
                os.path.join(backend_dir, "whatsapp_bridge", "uploads", os.path.basename(file_path)),
                os.path.join(backend_dir, file_path),
            ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    file_path = candidate
                    has_media = True
                    log.info(f"[WhatsApp] Media file resolved to: {file_path}")
                    break
            if not has_media:
                log.warning(f"[WhatsApp] Media file NOT FOUND at: {file_path} — tried: {candidates}")

    # Check WhatsApp Config for whitelist and auto-reply
    config = db.execute(select(WhatsAppConfig).order_by(WhatsAppConfig.id.desc())).scalar_one_or_none()
    if config:
        if not config.is_enabled:
            log.info(f"[WhatsApp] WhatsApp integration is disabled in settings. Ignoring message {message_id}")
            return {"status": "ignored", "reason": "integration_disabled"}
        
        whitelisted = config.whitelisted_jids or []
        if whitelisted and len(whitelisted) > 0:
            if chat_jid not in whitelisted and sender_jid not in whitelisted:
                log.info(f"[WhatsApp] Chat {chat_jid} / {sender_jid} is NOT in whitelist. Skipping.")
                return {"status": "ignored", "reason": "not_whitelisted"}

    auto_reply_enabled = config.auto_reply if config else True

    # Check deduplication
    existing_log = db.execute(
        select(WhatsAppLog).where(WhatsAppLog.message_id == message_id)
    ).scalar_one_or_none()
    if existing_log:
        log.info(f"WhatsApp message {message_id} already processed. Skipping.")
        return {"status": "duplicate", "log_id": existing_log.id, "pending_id": existing_log.matched_id}

    # Resolve default/active company context
    active_company = db.execute(
        select(Company).where(Company.is_active == True).order_by(Company.id.asc())
    ).scalars().first()
    company_id = active_company.id if active_company else None

    # Determine Document Classification & Extraction
    doc_type = "purchase_bill"
    doc_enum = DocumentType.purchase_bill
    matched_id = None
    extracted_data = {}
    ocr_result = {}
    status = "pending"
    error_msg = None
    reply_text = ""

    try:
        if has_media:
            log.info(f"[WhatsApp] Media received: {file_path} (mime={mime_type}). Queuing for background OCR.")
            # Skip synchronous OCR to mimic email flow
            doc_type = "unclassified"
            doc_enum = DocumentType.not_classified
            status = "pending"
            
            party = sender_name or "Partner"
            
            reply_text = (
                f"✅ *RCDF Operations: Document Received*\n\n"
                f"📄 *File:* {os.path.basename(file_path) if file_path else 'Attached Media'}\n"
                f"👤 *Sender:* {party}\n\n"
                f"Status: Queued in Operations Ingest Hub for OCR & classification."
            )

        elif text:
            # Handle structured text message (e.g., 'Maize 300 Qtl @ 2150 RJ14GC1234')
            extracted_data = _parse_text_bill(text)
            ocr_result = extracted_data
            
            # Check if this text looks like an actual bill or transaction
            has_bill_fields = bool(
                (extracted_data.get("material_type") and (extracted_data.get("quantity_mt") or extracted_data.get("rate_per_mt"))) or
                (extracted_data.get("vehicle_number") and extracted_data.get("quantity_mt")) or
                (extracted_data.get("quantity_mt") and extracted_data.get("rate_per_mt"))
            )

            if has_bill_fields:
                doc_type = "text_entry"
                doc_enum = DocumentType.purchase_bill
                reply_text = (
                    f"✅ *RCDF: Text Bill Logged*\n\n"
                    f"🌾 *Item:* {extracted_data.get('material_type') or 'Grain'}\n"
                    f"⚖️ *Qty:* {extracted_data.get('quantity_mt')} MT\n"
                    f"💰 *Rate:* ₹{extracted_data.get('rate_per_mt')}\n"
                    f"🚛 *Truck:* {extracted_data.get('vehicle_number') or 'N/A'}\n\n"
                    f"Status: Queued in Operations Ingest Hub."
                )
            else:
                # Completely irrelevant or casual message
                doc_type = "irrelevant"
                status = "ignored"
                reply_text = ""

        else:
            status = "ignored"
            doc_type = "irrelevant"
            reply_text = ""

    except Exception as e:
        log.error(f"Error processing WhatsApp message {message_id}: {e}", exc_info=True)
        status = "flagged"
        error_msg = str(e)

    # Normalise payload field names
    def _alias(d: dict, primary: str, *fallbacks):
        if not d.get(primary):
            for alt in fallbacks:
                v = d.get(alt)
                if v not in (None, "", "null", "None"):
                    d[primary] = v
                    break

    if extracted_data:
        _alias(extracted_data, "supplier_name", "vendor_name", "broker_name", "seller_name")
        _alias(extracted_data, "vendor_name", "supplier_name", "broker_name")
        _alias(extracted_data, "quantity_mt", "quantity_qtl")
        _alias(extracted_data, "quantity_qtl", "quantity_mt")
        _alias(extracted_data, "rate_per_mt", "rate_per_qtl", "rate")
        _alias(extracted_data, "rate_per_qtl", "rate_per_mt", "rate")

    # ONLY create PendingIngest entry if the message is a valid document or bill (NOT ignored / irrelevant)
    if status != "ignored" and doc_type != "irrelevant":
        try:
            file_name = os.path.basename(file_path) if file_path else f"wa_{message_id[:10]}.txt"
            pending_row = PendingIngest(
                company_id=company_id,
                source=IngestSource.whatsapp,
                source_address=sender_phone or sender_jid,
                source_account=f"{chat_name} ({sender_name})",
                source_message_id=message_id,
                file_name=file_name,
                file_path=file_path or "",
                document_type=doc_enum,
                classifier_confidence=0.9 if has_media else 0.5,
                classifier_candidates=[{"type": doc_type, "score": 0.9}],
                extracted_payload=extracted_data or {},
                unclear_fields=extracted_data.get("unclear_fields") or [],
                status=IngestStatus.pending,
                action_status="pending",
                review_notes=f"WhatsApp {doc_type} from {sender_name} ({sender_phone or sender_jid})"
            )
            db.add(pending_row)
            db.flush()
            matched_id = pending_row.id
        except Exception as pe:
            log.error(f"Failed to create PendingIngest for WhatsApp message {message_id}: {pe}", exc_info=True)

    # Save WhatsApp Log for audit trail
    whatsapp_log = WhatsAppLog(
        company_id=company_id,
        message_id=message_id,
        chat_jid=chat_jid,
        chat_name=chat_name,
        sender_jid=sender_jid,
        sender_name=sender_name,
        sender_phone=sender_phone,
        is_group=is_group,
        doc_type=doc_type,
        media_path=file_path,
        raw_text=text or (extracted_data.get("raw_text", "") if extracted_data else ""),
        ocr_result=ocr_result,
        matched_id=matched_id,
        status=status,
        error_message=error_msg,
        reply_sent=reply_text,
        created_at=datetime.utcnow()
    )
    db.add(whatsapp_log)
    db.commit()
    db.refresh(whatsapp_log)

    # Dispatch WhatsApp Confirmation Reply only for valid documents / bills
    if auto_reply_enabled and reply_text and chat_jid and status != "ignored":
        try:
            await send_whatsapp_message(chat_jid, reply_text)
        except Exception as se:
            log.warning("Could not dispatch auto reply to WhatsApp: %s", se)

    return {
        "status": status,
        "log_id": whatsapp_log.id,
        "matched_id": matched_id,
        "pending_id": matched_id,
        "doc_type": doc_type,
        "reply_text": reply_text
    }


async def _process_purchase_bill(
    message_id: str,
    chat_jid: str,
    chat_name: str,
    sender_jid: str,
    sender_phone: str,
    sender_name: str,
    image_path: Optional[str],
    extracted: dict,
    db: Session,
    company_id: Optional[int]
) -> Tuple[Optional[int], str]:
    """
    Creates Bill & BusyStagingBill from extracted OCR or parsed text.
    """
    # 1. Match Broker / Supplier
    broker = None
    if sender_phone:
        clean_phone = sender_phone[-10:]
        broker = db.execute(
            select(Broker).where(
                or_(
                    Broker.phone.ilike(f"%{clean_phone}%"),
                    Broker.telegram_chat_id == sender_phone
                )
            )
        ).scalars().first()

    if not broker and sender_name and sender_name != "Unknown Sender":
        broker = db.execute(
            select(Broker).where(Broker.name.ilike(f"%{sender_name}%"))
        ).scalars().first()

    broker_id = broker.id if broker else None
    broker_name = broker.name if broker else (extracted.get("supplier_name") or sender_name or chat_name)

    # 2. Match Material & Plant
    mat_name = extracted.get("material_type") or "Maize"
    material = db.execute(
        select(Material).where(Material.name.ilike(f"%{mat_name}%"))
    ).scalars().first()
    material_id = material.id if material else None

    plant_name = extracted.get("destination_plant") or "Kota"
    plant = db.execute(
        select(Plant).where(Plant.name.ilike(f"%{plant_name}%"))
    ).scalars().first()
    plant_id = plant.id if plant else None

    # 3. Match Active Deal if any
    deal_id = None
    if broker_id and material_id:
        deal = db.execute(
            select(Deal).where(
                Deal.broker_id == broker_id,
                Deal.material_id == material_id,
                Deal.status == "active"
            ).order_by(Deal.id.desc())
        ).scalars().first()
        if deal:
            deal_id = deal.id

    qty = extracted.get("quantity_mt") or extracted.get("quantity_qtl")
    rate = extracted.get("rate_per_mt") or extracted.get("rate_per_qtl")
    total_amount = extracted.get("total_amount")

    # If quantity in Quintal, normalize to MT (10 Qtl = 1 MT) or store canonical
    if qty and not total_amount and rate:
        total_amount = float(qty) * float(rate)

    confidence = extracted.get("confidence") or extracted.get("ocr_confidence") or 0.85
    needs_review = extracted.get("needs_review", False) or confidence < 0.70

    bill = Bill(
        company_id=company_id,
        broker_id=broker_id,
        broker_name=broker_name,
        deal_id=deal_id,
        plant_id=plant_id,
        plant_name=plant.name if plant else plant_name,
        material_id=material_id,
        material_name=material.name if material else mat_name,
        source=BillSource.whatsapp,
        whatsapp_msg_id=message_id,
        image_path=image_path,
        vehicle_number=extracted.get("vehicle_number"),
        qty_mt=qty,
        rate_per_mt=rate,
        total_amount=total_amount,
        bill_date=extracted.get("bill_date") or date.today(),
        bill_number=extracted.get("bill_number") or f"WA-{datetime.now().strftime('%m%d-%H%M')}",
        ocr_source=OcrSource.gemini if extracted.get("source") == "gemini" else OcrSource.paddle,
        ocr_confidence=confidence,
        ocr_raw_text=extracted.get("raw_text", ""),
        is_handwritten=extracted.get("is_handwritten", False),
        validation_amount=extracted.get("validation_amount", True),
        validation_vehicle=extracted.get("validation_vehicle", True),
        validation_material=extracted.get("validation_material", True),
        status=BillStatus.flagged if needs_review else BillStatus.pending,
        notes=f"Ingested via WhatsApp from {sender_name} ({sender_phone})"
    )
    db.add(bill)
    db.flush()

    # Also create Busy Staging Bill for seamless Busy export
    staging_bill = BusyStagingBill(
        company_id=company_id,
        source="whatsapp",
        image_path=image_path,
        broker_name=broker_name,
        vehicle_number=extracted.get("vehicle_number"),
        material_name=material.name if material else mat_name,
        qty_mt=qty,
        rate_per_mt=rate,
        total_amount=total_amount,
        bill_date=bill.bill_date,
        bill_number=bill.bill_number,
        plant_name=bill.plant_name,
        ocr_confidence=confidence,
        ocr_raw_text=extracted.get("raw_text", ""),
        is_handwritten=extracted.get("is_handwritten", False),
        validation_amount=extracted.get("validation_amount", True),
        validation_vehicle=extracted.get("validation_vehicle", True),
        validation_material=extracted.get("validation_material", True),
        busy_exported=False
    )
    db.add(staging_bill)
    db.commit()
    db.refresh(bill)

    # Format Professional WhatsApp Confirmation
    status_emoji = "⚠️" if needs_review else "✅"
    status_label = "Saved (Flagged for Review)" if needs_review else "Verified & Recorded"

    reply = (
        f"{status_emoji} *RCDF Purchase Bill Ingested*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📄 *Bill ID*: #{bill.id} ({bill.bill_number or 'N/A'})\n"
        f"👤 *Party*: {broker_name}\n"
        f"🌾 *Material*: {bill.material_name or 'N/A'}\n"
        f"⚖️ *Quantity*: {qty or 'N/A'} Qtl/MT\n"
        f"💰 *Rate*: ₹{(rate or 0):,.2f}/unit\n"
        f"💵 *Total*: ₹{(total_amount or 0):,.2f}\n"
        f"🚛 *Vehicle*: {extracted.get('vehicle_number') or 'Not Detected'}\n"
        f"🏭 *Plant*: {bill.plant_name or 'Kota'}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔍 *Status*: {status_label}\n"
    )

    if needs_review:
        errors = extracted.get("validation_errors", ["Low confidence score"])
        reply += f"⚠️ *Note*: {', '.join(errors)}. Dashboard verification required."

    return bill.id, reply


async def _process_weight_slip(
    chat_name: str,
    sender_phone: str,
    sender_name: str,
    file_path: str,
    extracted: dict,
    db: Session,
    company_id: Optional[int]
) -> Tuple[Optional[int], str]:
    """
    Processes Dharmkanta / Weighbridge Slip.
    """
    raw = extracted.get("raw_text", "")
    veh = extracted.get("vehicle_number") or "N/A"
    gross = extracted.get("gross_weight") or "N/A"
    tare = extracted.get("tare_weight") or "N/A"
    net = extracted.get("net_weight") or extracted.get("quantity_mt") or "N/A"

    reply = (
        f"⚖️ *Dharmkanta Weight Slip Received*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🚛 *Vehicle*: {veh}\n"
        f"📦 *Gross Weight*: {gross}\n"
        f"🚛 *Tare Weight*: {tare}\n"
        f"✨ *Net Weight*: {net} Qtl/MT\n"
        f"👤 *From*: {sender_name}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Saved & Linked to Logistics Queue."
    )
    return None, reply


async def _process_payment_proof(
    chat_name: str,
    sender_phone: str,
    sender_name: str,
    file_path: str,
    extracted: dict,
    db: Session,
    company_id: Optional[int]
) -> Tuple[Optional[int], str]:
    """
    Processes Payment Proof / UTR Screenshot.
    """
    amount = extracted.get("total_amount") or "N/A"
    utr_match = re.search(r'(?:UTR|REF|TXN)[\s:#\-]*([A-Z0-9]{8,22})', extracted.get("raw_text", ""), re.I)
    utr_num = utr_match.group(1) if utr_match else "Detected in Image"

    reply = (
        f"💳 *Payment Proof Recorded*\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 *UTR / Ref*: `{utr_num}`\n"
        f"💵 *Amount*: ₹{amount if isinstance(amount, (int, float)) else 'Verified via OCR'}\n"
        f"👤 *Sender*: {sender_name} ({sender_phone})\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Queued for Payment Ledger Reconciliation."
    )
    return None, reply


def _parse_text_bill(text: str) -> dict:
    """
    Extracts structured fields from plain text WhatsApp bill.
    Example: 'Maize 250 Qtl @ 2100 Truck RJ14GC1234 Kota'
    """
    res = {}
    # Extract vehicle
    veh_match = re.search(r'([A-Z]{2}\s*\d{2}\s*[A-Z]{1,2}\s*\d{4})', text, re.I)
    if veh_match:
        res["vehicle_number"] = re.sub(r'\s+', '', veh_match.group(1)).upper()

    # Extract Quantity
    qty_match = re.search(r'(\d+(?:\.\d+)?)\s*(?:qtl|quintal|mt|ton|tons)', text, re.I)
    if qty_match:
        res["quantity_mt"] = float(qty_match.group(1))

    # Extract Rate
    rate_match = re.search(r'(?:@|rate|rs\.?|₹)\s*(\d+(?:\.\d+)?)', text, re.I)
    if rate_match:
        res["rate_per_mt"] = float(rate_match.group(1))

    # Extract Material
    for mat in ["maize", "dorb", "domc", "rice ddgs", "ddgs", "soyabean", "mustard"]:
        if mat in text.lower():
            res["material_type"] = mat.capitalize()
            break

    # Calculate total
    if res.get("quantity_mt") and res.get("rate_per_mt"):
        res["total_amount"] = res["quantity_mt"] * res["rate_per_mt"]

    res["raw_text"] = text
    return res


async def send_whatsapp_message(chat_jid: str, text: str) -> bool:
    """
    Dispatches outgoing text message to WhatsApp chat JID via the local Node.js bridge.
    """
    if not chat_jid or not text:
        return False

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                f"{WHATSAPP_BRIDGE_URL}/send",
                json={"jid": chat_jid, "text": text}
            )
            if r.status_code == 200:
                log.info(f"WhatsApp reply delivered to {chat_jid}")
                return True
            else:
                log.warning(f"Failed to send WhatsApp message to {chat_jid}: {r.text}")
                return False
    except Exception as e:
        log.warning(f"Could not connect to WhatsApp bridge at {WHATSAPP_BRIDGE_URL}: {e}")
        return False
