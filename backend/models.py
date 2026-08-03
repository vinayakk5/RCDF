from sqlalchemy import (Column, Integer, String, Numeric, Boolean, Date,
                        DateTime, Text, Enum, JSON, ForeignKey, func,
                        Computed, UniqueConstraint, Index)
from sqlalchemy.orm import relationship
from database import Base
import enum

# ── Enums ──────────────────────────────────────────────────────────────────

class TenderStatus(str, enum.Enum):
    pending      = "pending"
    active       = "active"
    at_risk      = "at_risk"
    penalty_risk = "penalty_risk"
    complete     = "complete"
    cancelled    = "cancelled"

class DealStatus(str, enum.Enum):
    active    = "active"
    partial   = "partial"
    complete  = "complete"
    cancelled = "cancelled"

class BillStatus(str, enum.Enum):
    pending  = "pending"
    flagged  = "flagged"
    approved = "approved"
    linked   = "linked"
    rejected = "rejected"

class BillSource(str, enum.Enum):
    telegram = "telegram"
    whatsapp = "whatsapp"
    web      = "web"
    email    = "email"
    manual   = "manual"

class OcrSource(str, enum.Enum):
    paddle  = "paddle"
    gemini  = "gemini"
    manual  = "manual"

class DispatchStatus(str, enum.Enum):
    in_transit = "in_transit"
    arrived    = "arrived"
    accepted   = "accepted"
    rejected   = "rejected"
    partial    = "partial"

class PurchaseBillStatus(str, enum.Enum):
    draft     = "draft"
    confirmed = "confirmed"
    paid      = "paid"
    cancelled = "cancelled"

class SalesBillStatus(str, enum.Enum):
    draft     = "draft"
    sent      = "sent"
    paid      = "paid"
    overdue   = "overdue"
    cancelled = "cancelled"

class PurchaseOrderStatus(str, enum.Enum):
    draft     = "draft"
    approved  = "approved"
    cancelled = "cancelled"

class PaymentStatus(str, enum.Enum):
    pending   = "pending"
    processed = "processed"
    failed    = "failed"

class IngestStatus(str, enum.Enum):
    pending   = "pending"
    approved  = "approved"
    rejected  = "rejected"
    processed = "processed"

class IngestSource(str, enum.Enum):
    web      = "web"
    whatsapp = "whatsapp"
    telegram = "telegram"
    email    = "email"
    manual   = "manual"

class DocumentType(str, enum.Enum):
    purchase_bill    = "purchase_bill"
    tender_notice    = "tender_notice"
    purchase_order   = "purchase_order"
    rejection_notice = "rejection_notice"
    plant_unloading  = "plant_unloading"
    not_classified   = "not_classified"

# ── Reference tables ───────────────────────────────────────────────────────

class Plant(Base):
    __tablename__ = "plants"
    id        = Column(Integer, primary_key=True, index=True)
    name      = Column(String(100), nullable=False, unique=True)
    code      = Column(String(20),  nullable=False, unique=True)
    is_active = Column(Boolean, default=True)
    created_at= Column(DateTime, default=func.now())

class Material(Base):
    __tablename__ = "materials"
    id        = Column(Integer, primary_key=True, index=True)
    name      = Column(String(100), nullable=False, unique=True)
    code      = Column(String(20),  nullable=False, unique=True)
    unit      = Column(String(10),  default="MT")
    is_active = Column(Boolean, default=True)

class Broker(Base):
    __tablename__ = "brokers"
    id               = Column(Integer, primary_key=True, index=True)
    name             = Column(String(200), nullable=False)
    phone            = Column(String(20))
    telegram_chat_id = Column(String(50))
    gstin            = Column(String(20))
    address          = Column(Text)
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=func.now())
    deals            = relationship("Deal", back_populates="broker")


class Company(Base):
    __tablename__ = "companies"
    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String(200), nullable=False, unique=True)
    code       = Column(String(50), nullable=True, unique=True)
    is_active  = Column(Boolean, default=True)
    created_at = Column(DateTime, default=func.now())


class MainTender(Base):
    __tablename__ = "main_tenders"
    __table_args__ = (
        UniqueConstraint("company_id", "tender_code", name="uq_main_tenders_company_code"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    company_id  = Column(Integer, ForeignKey("companies.id"), nullable=False)
    tender_code = Column(String(100), nullable=False)
    title       = Column(String(200))
    notes       = Column(Text)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=func.now())
    updated_at  = Column(DateTime, default=func.now(), onupdate=func.now())

    company     = relationship("Company")
    tenders     = relationship("Tender", back_populates="main_tender")

# ── Core operations ────────────────────────────────────────────────────────

class SproxxCycle(Base):
    __tablename__ = "sproxx_cycles"
    id          = Column(Integer, primary_key=True, index=True)
    company_id  = Column(Integer, ForeignKey("companies.id"), nullable=True)
    name        = Column(String(100), nullable=False)
    cycle_start = Column(Date, nullable=False)
    cycle_end   = Column(Date, nullable=False)
    week1_end   = Column(Date, nullable=False)
    week2_end   = Column(Date, nullable=False)
    is_active   = Column(Boolean, default=False)
    created_at  = Column(DateTime, default=func.now())
    company     = relationship("Company")
    tenders     = relationship("Tender", back_populates="cycle")

class Tender(Base):
    __tablename__ = "tenders"
    id              = Column(Integer, primary_key=True, index=True)
    company_id      = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id  = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    cycle_id        = Column(Integer, ForeignKey("sproxx_cycles.id"), nullable=False)
    tender_number   = Column(String(50), nullable=False, unique=True)
    plant_id        = Column(Integer, ForeignKey("plants.id"), nullable=False)
    material_id     = Column(Integer, ForeignKey("materials.id"), nullable=False)
    tender_mt       = Column(Numeric(10, 2), nullable=False)
    fulfilled_qty_mt = Column(Numeric(12, 3), default=0)
    week1_target_mt = Column(Numeric(10, 2), nullable=False)
    week1_deadline  = Column(Date, nullable=False)
    week2_deadline  = Column(Date, nullable=False)
    penalty_pct     = Column(Numeric(5, 2), default=20.00)
    status          = Column(Enum(TenderStatus), default=TenderStatus.pending)
    notes           = Column(Text)
    created_at      = Column(DateTime, default=func.now())
    updated_at      = Column(DateTime, default=func.now(), onupdate=func.now())
    company         = relationship("Company")
    main_tender     = relationship("MainTender", back_populates="tenders")
    cycle           = relationship("SproxxCycle", back_populates="tenders")
    plant           = relationship("Plant")
    material        = relationship("Material")
    deals           = relationship("Deal", back_populates="tender")

class Deal(Base):
    __tablename__ = "deals"
    id            = Column(Integer, primary_key=True, index=True)
    company_id    = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id= Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id     = Column(Integer, ForeignKey("tenders.id"), nullable=False)
    broker_id     = Column(Integer, ForeignKey("brokers.id"), nullable=False)
    deal_number   = Column(String(50), nullable=False, unique=True)
    material_id   = Column(Integer, ForeignKey("materials.id"), nullable=False)
    deal_mt       = Column(Numeric(10, 2), nullable=False)
    rate_per_mt   = Column(Numeric(10, 2), nullable=False)
    dispatched_mt = Column(Numeric(10, 2), default=0)
    accepted_mt   = Column(Numeric(10, 2), default=0)
    rejected_mt   = Column(Numeric(10, 2), default=0)
    status        = Column(Enum(DealStatus), default=DealStatus.active)
    notes         = Column(Text)
    created_at    = Column(DateTime, default=func.now())
    updated_at    = Column(DateTime, default=func.now(), onupdate=func.now())
    company       = relationship("Company")
    main_tender   = relationship("MainTender")
    tender        = relationship("Tender", back_populates="deals")
    broker        = relationship("Broker", back_populates="deals")
    material      = relationship("Material")
    bills         = relationship("Bill", back_populates="deal")

class Bill(Base):
    __tablename__ = "bills"
    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id   = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id        = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    unloading_match_entry_id = Column(Integer, nullable=True)
    unloading_match_master_id = Column(Integer, nullable=True)
    unloading_match_method = Column(String(40), nullable=True)
    deal_id          = Column(Integer, ForeignKey("deals.id"), nullable=True)
    broker_id        = Column(Integer, ForeignKey("brokers.id"), nullable=True)
    broker_name      = Column(String(200))
    source           = Column(Enum(BillSource), default=BillSource.telegram)
    telegram_msg_id  = Column(String(50))
    whatsapp_msg_id  = Column(String(100))
    image_path       = Column(String(500))
    vehicle_number   = Column(String(20))
    material_id      = Column(Integer, ForeignKey("materials.id"), nullable=True)
    material_name    = Column(String(100))
    qty_mt           = Column(Numeric(10, 2))
    rate_per_mt      = Column(Numeric(10, 2))
    total_amount     = Column(Numeric(14, 2))
    bill_date        = Column(Date)
    bill_number      = Column(String(100))
    plant_id         = Column(Integer, ForeignKey("plants.id"), nullable=True)
    plant_name       = Column(String(100))
    ocr_source       = Column(Enum(OcrSource), default=OcrSource.paddle)
    ocr_confidence   = Column(Numeric(4, 3))
    ocr_raw_text     = Column(Text)
    is_handwritten   = Column(Boolean, default=False)
    validation_amount   = Column(Boolean, default=False)
    validation_vehicle  = Column(Boolean, default=False)
    validation_material = Column(Boolean, default=False)
    status           = Column(Enum(BillStatus), default=BillStatus.pending)
    reviewed_by      = Column(String(100))
    reviewed_at      = Column(DateTime)
    notes            = Column(Text)
    created_at       = Column(DateTime, default=func.now())
    updated_at       = Column(DateTime, default=func.now(), onupdate=func.now())
    company          = relationship("Company")
    main_tender      = relationship("MainTender")
    tender           = relationship("Tender", foreign_keys=[tender_id])
    deal             = relationship("Deal", back_populates="bills")
    broker           = relationship("Broker", foreign_keys=[broker_id])
    material         = relationship("Material", foreign_keys=[material_id])
    plant            = relationship("Plant", foreign_keys=[plant_id])


class BusyStagingBill(Base):
    __tablename__ = "busy_staging_bills"
    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    source           = Column(String(20), default="web")
    image_path       = Column(String(500))
    file_hash        = Column(String(64))
    broker_name      = Column(String(200))
    vehicle_number   = Column(String(20))
    material_name    = Column(String(100))
    qty_mt           = Column(Numeric(10, 2))
    rate_per_mt      = Column(Numeric(10, 2))
    total_amount     = Column(Numeric(14, 2))
    bill_date        = Column(Date)
    bill_number      = Column(String(100))
    plant_name       = Column(String(100))
    ocr_source       = Column(Enum(OcrSource), default=OcrSource.paddle)
    ocr_confidence   = Column(Numeric(4, 3))
    ocr_raw_text     = Column(Text)
    is_handwritten   = Column(Boolean, default=False)
    validation_amount   = Column(Boolean, default=False)
    validation_vehicle  = Column(Boolean, default=False)
    validation_material = Column(Boolean, default=False)
    busy_exported    = Column(Boolean, default=False)
    busy_exported_at = Column(DateTime)
    created_at       = Column(DateTime, default=func.now())
    updated_at       = Column(DateTime, default=func.now(), onupdate=func.now())
    company          = relationship("Company")

class Dispatch(Base):
    __tablename__ = "dispatches"
    id             = Column(Integer, primary_key=True, index=True)
    company_id     = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id      = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    bill_id        = Column(Integer, ForeignKey("bills.id"), nullable=True)
    deal_id        = Column(Integer, ForeignKey("deals.id"), nullable=False)
    material_id    = Column(Integer, ForeignKey("materials.id"), nullable=True)
    material_name  = Column(String(100))
    vehicle_number = Column(String(20), nullable=False)
    dispatch_date  = Column(Date, nullable=False)
    qty_mt         = Column(Numeric(10, 2), nullable=False)
    consumed_qty_qtl = Column(Numeric(10, 2), default=0)
    plant_id       = Column(Integer, ForeignKey("plants.id"), nullable=False)
    driver_name    = Column(String(100))
    driver_phone   = Column(String(20))
    status         = Column(Enum(DispatchStatus), default=DispatchStatus.in_transit)
    notes          = Column(Text)
    created_at     = Column(DateTime, default=func.now())
    updated_at     = Column(DateTime, default=func.now(), onupdate=func.now())
    is_deleted     = Column(Boolean, default=False)
    deleted_at     = Column(DateTime)
    company        = relationship("Company")
    main_tender    = relationship("MainTender")
    tender         = relationship("Tender", foreign_keys=[tender_id])
    plant          = relationship("Plant")
    material       = relationship("Material", foreign_keys=[material_id])
    receipt        = relationship("PlantReceipt", back_populates="dispatch", uselist=False, foreign_keys="PlantReceipt.dispatch_id")

class PlantReceipt(Base):
    __tablename__ = "plant_receipts"
    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id   = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id        = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    dispatch_id      = Column(Integer, ForeignKey("dispatches.id"), nullable=True)
    matched_dispatch_id = Column(Integer, ForeignKey("dispatches.id"), nullable=True)
    material_id      = Column(Integer, ForeignKey("materials.id"), nullable=True)
    material_name    = Column(String(100))
    vehicle_number   = Column(String(20), nullable=False)
    plant_id         = Column(Integer, ForeignKey("plants.id"), nullable=False)
    receipt_date     = Column(Date, nullable=False)
    accepted_mt      = Column(Numeric(10, 2), default=0)
    rejected_mt      = Column(Numeric(10, 2), default=0)
    received_qty_qtl = Column(Numeric(10, 2))
    matched_qty_qtl  = Column(Numeric(10, 2), default=0)
    match_status     = Column(String(20), default="unmatched")
    match_reason     = Column(Text)
    match_applied_at = Column(DateTime)
    rm_number        = Column(String(100))
    party_name       = Column(String(200))
    po_number        = Column(String(100))
    rejection_reason = Column(Text)
    source           = Column(String(20), default="manual")
    email_raw        = Column(Text)
    created_at       = Column(DateTime, default=func.now())
    company          = relationship("Company")
    main_tender      = relationship("MainTender")
    tender           = relationship("Tender", foreign_keys=[tender_id])
    plant            = relationship("Plant")
    dispatch         = relationship("Dispatch", back_populates="receipt", foreign_keys=[dispatch_id])
    matched_dispatch = relationship("Dispatch", foreign_keys=[matched_dispatch_id])
    material         = relationship("Material", foreign_keys=[material_id])
    is_deleted       = Column(Boolean, default=False)
    deleted_at       = Column(DateTime)


class PlantUnloadingMaster(Base):
    __tablename__ = "plant_unloading_masters"
    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id   = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id        = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    rm_number        = Column(String(100), nullable=False)
    rm_number_norm   = Column(String(100))
    rm_number_base   = Column(String(100))
    item_name        = Column(String(100), nullable=False)
    party_name       = Column(String(200), nullable=False)
    plant_id         = Column(Integer, ForeignKey("plants.id"), nullable=True)
    plant_name       = Column(String(100))
    assignment_status = Column(String(30), default="pending")
    assignment_reason = Column(Text)
    assignment_confidence = Column(Numeric(4, 3))
    mapping_source   = Column(String(30))
    requires_manual_assignment = Column(Boolean, default=False)
    is_manual_override = Column(Boolean, default=False)
    manual_assigned_by = Column(String(100))
    manual_assigned_at = Column(DateTime)
    po_number        = Column(String(100))
    notes            = Column(Text)
    created_at       = Column(DateTime, default=func.now())
    updated_at       = Column(DateTime, default=func.now(), onupdate=func.now())

    company          = relationship("Company")
    main_tender      = relationship("MainTender")
    tender           = relationship("Tender", foreign_keys=[tender_id])
    plant            = relationship("Plant")
    entries          = relationship("PlantUnloadingEntry", back_populates="master")


class PlantUnloadingEntry(Base):
    __tablename__ = "plant_unloading_entries"
    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id   = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id        = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    master_id        = Column(Integer, ForeignKey("plant_unloading_masters.id"), nullable=False)
    image_path       = Column(String(500))
    source           = Column(String(20), default="web")
    ws_no            = Column(String(50))
    entry_date       = Column(Date, nullable=False)
    truck_number     = Column(String(30), nullable=False)
    no_of_bags       = Column(Integer)
    received_qty_mt  = Column(Numeric(10, 3))
    net_qty_mt       = Column(Numeric(10, 3), nullable=False)
    total_qty_mt     = Column(Numeric(12, 3))
    item_name        = Column(String(100))
    status           = Column(Enum(BillStatus), default=BillStatus.pending)
    reviewed_by      = Column(String(100))
    reviewed_at      = Column(DateTime)
    receipt_id       = Column(Integer, ForeignKey("plant_receipts.id"), nullable=True)
    receipt_created  = Column(Boolean, default=False)
    dedupe_key       = Column(String(255), nullable=False, unique=True)
    ocr_source       = Column(Enum(OcrSource), default=OcrSource.paddle)
    ocr_confidence   = Column(Numeric(4, 3))
    ocr_raw_json     = Column(Text)
    notes            = Column(Text)
    created_at       = Column(DateTime, default=func.now())
    updated_at       = Column(DateTime, default=func.now(), onupdate=func.now())

    company          = relationship("Company")
    main_tender      = relationship("MainTender")
    tender           = relationship("Tender", foreign_keys=[tender_id])
    master           = relationship("PlantUnloadingMaster", back_populates="entries")
    receipt          = relationship("PlantReceipt")


class PendingIngest(Base):
    __tablename__ = "pending_ingests"

    id                    = Column(Integer, primary_key=True, index=True)
    company_id            = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id        = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id             = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    source                = Column(Enum(IngestSource), default=IngestSource.web)
    source_address        = Column(String(200))
    source_account        = Column(String(200))
    source_message_id     = Column(String(100))
    file_name             = Column(String(255), nullable=False)
    file_path             = Column(String(500), nullable=False)
    file_hash             = Column(String(64), index=True)
    document_type         = Column(Enum(DocumentType), nullable=False)
    classifier_confidence = Column(Numeric(4, 3))
    classifier_candidates = Column(JSON)
    extracted_payload     = Column(JSON)
    unclear_fields        = Column(JSON)
    status                = Column(Enum(IngestStatus), default=IngestStatus.pending)
    assigned_company_id   = Column(Integer, ForeignKey("companies.id"), nullable=True)
    assigned_main_tender_id = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    assigned_tender_id    = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    review_notes          = Column(Text)
    reviewed_by           = Column(String(100))
    reviewed_at           = Column(DateTime)
    action_status         = Column(String(30), default="pending")
    action_error          = Column(Text)
    action_payload        = Column(JSON)
    created_at            = Column(DateTime, default=func.now())
    updated_at            = Column(DateTime, default=func.now(), onupdate=func.now())

    company               = relationship("Company", foreign_keys=[company_id])
    main_tender           = relationship("MainTender", foreign_keys=[main_tender_id])
    tender                = relationship("Tender", foreign_keys=[tender_id])
    assigned_company      = relationship("Company", foreign_keys=[assigned_company_id])
    assigned_main_tender  = relationship("MainTender", foreign_keys=[assigned_main_tender_id])
    assigned_tender       = relationship("Tender", foreign_keys=[assigned_tender_id])


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id                  = Column(Integer, primary_key=True, index=True)
    company_id          = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id      = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id           = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    po_number           = Column(String(100), nullable=False)
    po_date             = Column(Date)
    seller_name         = Column(String(200))
    buyer_name          = Column(String(200))
    buyer_email         = Column(String(200))
    plant_id            = Column(Integer, ForeignKey("plants.id"), nullable=True)
    plant_name          = Column(String(100))
    total_amount        = Column(Numeric(14, 2))
    line_items          = Column(JSON)
    status              = Column(Enum(PurchaseOrderStatus), default=PurchaseOrderStatus.draft)
    source              = Column(String(20), default="ingest")
    source_doc_path     = Column(String(500))
    source_pending_id   = Column(Integer, ForeignKey("pending_ingests.id"), nullable=True, unique=True)
    notes               = Column(Text)
    created_at          = Column(DateTime, default=func.now())
    updated_at          = Column(DateTime, default=func.now(), onupdate=func.now())

    company             = relationship("Company", foreign_keys=[company_id])
    main_tender         = relationship("MainTender", foreign_keys=[main_tender_id])
    tender              = relationship("Tender", foreign_keys=[tender_id])
    plant               = relationship("Plant", foreign_keys=[plant_id])
    source_pending      = relationship("PendingIngest")

class PurchaseBill(Base):
    __tablename__ = "purchase_bills"
    id             = Column(Integer, primary_key=True, index=True)
    company_id     = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id      = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    bill_id        = Column(Integer, ForeignKey("bills.id"), nullable=False, unique=True)
    deal_id        = Column(Integer, ForeignKey("deals.id"), nullable=False)
    broker_id      = Column(Integer, ForeignKey("brokers.id"), nullable=False)
    pb_number      = Column(String(50), unique=True)
    qty_mt         = Column(Numeric(10, 2), nullable=False)
    rate_per_mt    = Column(Numeric(10, 2), nullable=False)
    total_amount   = Column(Numeric(14, 2), nullable=False)
    bill_date      = Column(Date, nullable=False)
    due_date       = Column(Date)
    status         = Column(Enum(PurchaseBillStatus), default=PurchaseBillStatus.draft)
    busy_exported  = Column(Boolean, default=False)
    busy_export_at = Column(DateTime)
    created_at     = Column(DateTime, default=func.now())
    company        = relationship("Company")
    main_tender    = relationship("MainTender")
    tender         = relationship("Tender", foreign_keys=[tender_id])
    broker         = relationship("Broker")

class SalesBill(Base):
    __tablename__ = "sales_bills"
    id             = Column(Integer, primary_key=True, index=True)
    company_id     = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id      = Column(Integer, ForeignKey("tenders.id"), nullable=False)
    plant_id       = Column(Integer, ForeignKey("plants.id"), nullable=False)
    sb_number      = Column(String(50), unique=True)
    qty_mt         = Column(Numeric(10, 2), nullable=False)
    rate_per_mt    = Column(Numeric(10, 2), nullable=False)
    total_amount   = Column(Numeric(14, 2), nullable=False)
    bill_date      = Column(Date, nullable=False)
    due_date       = Column(Date)
    status         = Column(Enum(SalesBillStatus), default=SalesBillStatus.draft)
    busy_exported  = Column(Boolean, default=False)
    busy_export_at = Column(DateTime)
    paid_at        = Column(DateTime)
    created_at     = Column(DateTime, default=func.now())
    company        = relationship("Company")
    main_tender    = relationship("MainTender")
    plant          = relationship("Plant")
    tender         = relationship("Tender")

class Payment(Base):
    __tablename__ = "payments"
    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id   = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    tender_id        = Column(Integer, ForeignKey("tenders.id"), nullable=True)
    purchase_bill_id = Column(Integer, ForeignKey("purchase_bills.id"), nullable=False)
    broker_id        = Column(Integer, ForeignKey("brokers.id"), nullable=False)
    voucher_number   = Column(String(50))
    amount           = Column(Numeric(14, 2), nullable=False)
    payment_date     = Column(Date)
    payment_mode     = Column(String(20), default="neft")
    reference_no     = Column(String(100))
    status           = Column(Enum(PaymentStatus), default=PaymentStatus.pending)
    busy_exported    = Column(Boolean, default=False)
    busy_export_at   = Column(DateTime)
    notes            = Column(Text)
    created_at       = Column(DateTime, default=func.now())
    company          = relationship("Company")
    main_tender      = relationship("MainTender")
    tender           = relationship("Tender", foreign_keys=[tender_id])
    broker           = relationship("Broker")
    purchase_bill    = relationship("PurchaseBill")

class MarketPrice(Base):
    __tablename__ = "market_prices"
    id           = Column(Integer, primary_key=True, index=True)
    company_id   = Column(Integer, ForeignKey("companies.id"), nullable=True)
    material_id  = Column(Integer, ForeignKey("materials.id"), nullable=False)
    price_date   = Column(Date, nullable=False)
    price_per_mt = Column(Numeric(10, 2), nullable=False)
    market       = Column(String(100))
    source       = Column(String(20), default="manual")
    notes        = Column(Text)
    created_at   = Column(DateTime, default=func.now())
    company      = relationship("Company")
    material     = relationship("Material")

class BusyExport(Base):
    __tablename__ = "busy_exports"
    id          = Column(Integer, primary_key=True, index=True)
    company_id  = Column(Integer, ForeignKey("companies.id"), nullable=True)
    main_tender_id = Column(Integer, ForeignKey("main_tenders.id"), nullable=True)
    export_type = Column(String(50))
    record_ids  = Column(JSON)
    file_path   = Column(String(500))
    created_at  = Column(DateTime, default=func.now())
    company     = relationship("Company")
    main_tender = relationship("MainTender")


class BusyPartyMapping(Base):
    __tablename__ = "busy_party_mappings"
    __table_args__ = (
        UniqueConstraint("company_id", "source_party_name", name="uq_busy_party_map_company_source"),
    )

    id                      = Column(Integer, primary_key=True, index=True)
    company_id              = Column(Integer, ForeignKey("companies.id"), nullable=False)
    source_party_name       = Column(String(200), nullable=False)
    busy_party_name         = Column(String(200), nullable=False)
    sale_purc_type_override = Column(String(30), nullable=True)
    notes                   = Column(Text)
    created_at              = Column(DateTime, default=func.now())
    updated_at              = Column(DateTime, default=func.now(), onupdate=func.now())

    company                 = relationship("Company")


class BusyPartyMaster(Base):
    __tablename__ = "busy_party_master"
    __table_args__ = (
        Index("idx_busy_party_master_scope", "company_id", "is_active"),
        Index("idx_busy_party_master_name", "name_normalized"),
        Index("idx_busy_party_master_gstin", "gstin"),
    )

    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    busy_party_name  = Column(String(220), nullable=False)
    alias            = Column(String(220), nullable=True)
    parent_group     = Column(String(150), nullable=True)
    dealer_type      = Column(String(80), nullable=True)
    gstin            = Column(String(20), nullable=True)
    filing_frequency = Column(String(40), nullable=True)
    state_code       = Column(String(2), nullable=True)
    state_name       = Column(String(100), nullable=True)
    station          = Column(String(120), nullable=True)
    name_normalized  = Column(String(260), nullable=False)
    source_file      = Column(String(255), nullable=True)
    is_active        = Column(Boolean, default=True)
    created_at       = Column(DateTime, default=func.now())
    updated_at       = Column(DateTime, default=func.now(), onupdate=func.now())

    company          = relationship("Company")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id         = Column(Integer, primary_key=True, index=True)
    entity     = Column(String(100), nullable=False)
    entity_id  = Column(Integer, nullable=False)
    action     = Column(String(50), nullable=False)
    payload    = Column(JSON)
    created_at = Column(DateTime, default=func.now())


class WhatsAppConfig(Base):
    __tablename__ = "whatsapp_configs"
    id               = Column(Integer, primary_key=True, index=True)
    company_id       = Column(Integer, ForeignKey("companies.id"), nullable=True)
    is_enabled       = Column(Boolean, default=True)
    auto_reply       = Column(Boolean, default=True)
    whitelisted_jids = Column(JSON, default=list)  # list of strings [ "120363...@g.us", "9198...@s.whatsapp.net" ]
    monitored_groups = Column(JSON, default=list)  # list of objects [{ "jid": "...", "name": "...", "is_active": True }]
    created_at       = Column(DateTime, default=func.now())
    updated_at       = Column(DateTime, default=func.now(), onupdate=func.now())

    company          = relationship("Company")


class WhatsAppLog(Base):
    __tablename__ = "whatsapp_logs"
    id             = Column(Integer, primary_key=True, index=True)
    company_id     = Column(Integer, ForeignKey("companies.id"), nullable=True)
    message_id     = Column(String(100), index=True)
    chat_jid       = Column(String(120), index=True)
    chat_name      = Column(String(200))
    sender_jid     = Column(String(120))
    sender_name    = Column(String(200))
    sender_phone   = Column(String(30))
    is_group       = Column(Boolean, default=False)
    doc_type       = Column(String(50), default="purchase_bill")
    media_path     = Column(String(500))
    raw_text       = Column(Text)
    ocr_result     = Column(JSON)
    matched_id     = Column(Integer)  # Bill ID or Receipt ID
    status         = Column(String(30), default="processed")  # processed, flagged, ignored, failed
    error_message  = Column(Text)
    reply_sent     = Column(Text)
    created_at     = Column(DateTime, default=func.now())

    company        = relationship("Company")

