-- ============================================================
-- RCDF Supply Operations — Full Database Schema
-- MySQL 8.0+
-- ============================================================

CREATE DATABASE IF NOT EXISTS rcdf_supply CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE rcdf_supply;

-- ============================================================
-- REFERENCE DATA
-- ============================================================

CREATE TABLE plants (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(100) NOT NULL UNIQUE,
  code        VARCHAR(20)  NOT NULL UNIQUE,
  is_active   BOOLEAN DEFAULT TRUE,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO plants (name, code) VALUES
  ('Ajmer',    'AJM'),
  ('Jodhpur',  'JDH'),
  ('Kaladers', 'KLD'),
  ('Nadbai',   'NDB'),
  ('Bikaner',  'BKN'),
  ('Pali',     'PLI'),
  ('Lambiyan', 'LMB');

CREATE TABLE materials (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(100) NOT NULL UNIQUE,
  code        VARCHAR(20)  NOT NULL UNIQUE,
  unit        VARCHAR(10)  DEFAULT 'MT',
  is_active   BOOLEAN DEFAULT TRUE
);

INSERT INTO materials (name, code) VALUES
  ('Maize',     'MZ'),
  ('Dorb',      'DB'),
  ('Domc',      'DM'),
  ('Rice DDGS', 'RD');

CREATE TABLE brokers (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  name         VARCHAR(200) NOT NULL,
  phone        VARCHAR(20),
  telegram_chat_id VARCHAR(50),
  gstin        VARCHAR(20),
  address      TEXT,
  is_active    BOOLEAN DEFAULT TRUE,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- SPROXX CYCLES
-- ============================================================

CREATE TABLE sproxx_cycles (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  name         VARCHAR(100) NOT NULL,           -- e.g. "Mar 18–31 2026"
  cycle_start  DATE NOT NULL,
  cycle_end    DATE NOT NULL,
  week1_end    DATE NOT NULL,
  week2_end    DATE NOT NULL,
  is_active    BOOLEAN DEFAULT FALSE,
  created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================
-- TENDERS
-- ============================================================

CREATE TABLE tenders (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  cycle_id        INT NOT NULL,
  tender_number   VARCHAR(50) NOT NULL UNIQUE,
  plant_id        INT NOT NULL,
  material_id     INT NOT NULL,
  tender_mt       DECIMAL(10,2) NOT NULL,
  week1_target_mt DECIMAL(10,2) NOT NULL,       -- usually 50% of tender_mt
  week1_deadline  DATE NOT NULL,
  week2_deadline  DATE NOT NULL,
  penalty_pct     DECIMAL(5,2) DEFAULT 20.00,   -- 20% penalty
  status          ENUM('pending','active','at_risk','penalty_risk','complete','cancelled') DEFAULT 'pending',
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (cycle_id)   REFERENCES sproxx_cycles(id),
  FOREIGN KEY (plant_id)   REFERENCES plants(id),
  FOREIGN KEY (material_id) REFERENCES materials(id)
);

-- ============================================================
-- DEALS (broker purchase agreements per tender)
-- ============================================================

CREATE TABLE deals (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  tender_id       INT NOT NULL,
  broker_id       INT NOT NULL,
  deal_number     VARCHAR(50) NOT NULL UNIQUE,
  material_id     INT NOT NULL,
  deal_mt         DECIMAL(10,2) NOT NULL,
  rate_per_mt     DECIMAL(10,2) NOT NULL,
  total_value     DECIMAL(14,2) GENERATED ALWAYS AS (deal_mt * rate_per_mt) STORED,
  dispatched_mt   DECIMAL(10,2) DEFAULT 0,
  accepted_mt     DECIMAL(10,2) DEFAULT 0,
  rejected_mt     DECIMAL(10,2) DEFAULT 0,
  status          ENUM('active','partial','complete','cancelled') DEFAULT 'active',
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (tender_id)   REFERENCES tenders(id),
  FOREIGN KEY (broker_id)   REFERENCES brokers(id),
  FOREIGN KEY (material_id) REFERENCES materials(id)
);

-- ============================================================
-- BILLS (incoming from brokers via Telegram / web / email)
-- ============================================================

CREATE TABLE bills (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  deal_id         INT,                           -- nullable until linked
  broker_id       INT,
  broker_name     VARCHAR(200),                  -- fallback if broker not in system
  source          ENUM('telegram','web','email','manual') NOT NULL DEFAULT 'telegram',
  telegram_msg_id VARCHAR(50),
  image_path      VARCHAR(500),
  vehicle_number  VARCHAR(20),
  material_id     INT,
  material_name   VARCHAR(100),
  qty_mt          DECIMAL(10,2),
  rate_per_mt     DECIMAL(10,2),
  total_amount    DECIMAL(14,2),
  bill_date       DATE,
  bill_number     VARCHAR(100),
  plant_id        INT,
  plant_name      VARCHAR(100),
  -- OCR metadata
  ocr_source      ENUM('paddle','gemini','manual') DEFAULT 'paddle',
  ocr_confidence  DECIMAL(4,3),
  ocr_raw_text    TEXT,
  is_handwritten  BOOLEAN DEFAULT FALSE,
  -- Validation flags
  validation_amount   BOOLEAN DEFAULT FALSE,
  validation_vehicle  BOOLEAN DEFAULT FALSE,
  validation_material BOOLEAN DEFAULT FALSE,
  -- Workflow status
  status          ENUM('pending','flagged','approved','linked','rejected') DEFAULT 'pending',
  reviewed_by     VARCHAR(100),
  reviewed_at     DATETIME,
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (deal_id)     REFERENCES deals(id) ON DELETE SET NULL,
  FOREIGN KEY (broker_id)   REFERENCES brokers(id) ON DELETE SET NULL,
  FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL,
  FOREIGN KEY (plant_id)    REFERENCES plants(id) ON DELETE SET NULL
);

-- ============================================================
-- DISPATCHES (trucks sent to plant)
-- ============================================================

CREATE TABLE dispatches (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  bill_id         INT NOT NULL,
  deal_id         INT NOT NULL,
  material_id     INT,
  material_name   VARCHAR(100),
  vehicle_number  VARCHAR(20) NOT NULL,
  dispatch_date   DATE NOT NULL,
  qty_mt          DECIMAL(10,2) NOT NULL,
  consumed_qty_qtl DECIMAL(10,2) DEFAULT 0,
  plant_id        INT NOT NULL,
  driver_name     VARCHAR(100),
  driver_phone    VARCHAR(20),
  status          ENUM('in_transit','arrived','accepted','rejected','partial') DEFAULT 'in_transit',
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  FOREIGN KEY (bill_id)  REFERENCES bills(id),
  FOREIGN KEY (deal_id)  REFERENCES deals(id),
  FOREIGN KEY (material_id) REFERENCES materials(id),
  FOREIGN KEY (plant_id) REFERENCES plants(id)
);

-- ============================================================
-- PLANT RECEIPTS (what the plant actually accepted/rejected)
-- ============================================================

CREATE TABLE plant_receipts (
  id                INT AUTO_INCREMENT PRIMARY KEY,
  dispatch_id       INT,
  matched_dispatch_id INT,
  material_id       INT,
  material_name     VARCHAR(100),
  vehicle_number    VARCHAR(20) NOT NULL,
  plant_id          INT NOT NULL,
  receipt_date      DATE NOT NULL,
  accepted_mt       DECIMAL(10,2) DEFAULT 0,
  rejected_mt       DECIMAL(10,2) DEFAULT 0,
  received_qty_qtl  DECIMAL(10,2),
  matched_qty_qtl   DECIMAL(10,2) DEFAULT 0,
  match_status      VARCHAR(20) DEFAULT 'unmatched',
  match_reason      TEXT,
  match_applied_at  DATETIME,
  rm_number         VARCHAR(100),
  party_name        VARCHAR(200),
  po_number         VARCHAR(100),
  rejection_reason  TEXT,
  source            ENUM('email','manual','portal') DEFAULT 'email',
  email_raw         TEXT,
  created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (dispatch_id) REFERENCES dispatches(id) ON DELETE SET NULL,
  FOREIGN KEY (matched_dispatch_id) REFERENCES dispatches(id) ON DELETE SET NULL,
  FOREIGN KEY (material_id) REFERENCES materials(id) ON DELETE SET NULL,
  FOREIGN KEY (plant_id)    REFERENCES plants(id)
);

-- ============================================================
-- PLANT UNLOADING REGISTERS (uploaded sheet + incremental rows)
-- ============================================================

CREATE TABLE plant_unloading_masters (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  rm_number       VARCHAR(100) NOT NULL,
  item_name       VARCHAR(100) NOT NULL,
  party_name      VARCHAR(200) NOT NULL,
  plant_id        INT,
  plant_name      VARCHAR(100),
  po_number       VARCHAR(100),
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_pum_key (rm_number, item_name, party_name),
  FOREIGN KEY (plant_id) REFERENCES plants(id) ON DELETE SET NULL
);

CREATE TABLE plant_unloading_entries (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  master_id       INT NOT NULL,
  image_path      VARCHAR(500),
  source          VARCHAR(20) DEFAULT 'web',
  ws_no           VARCHAR(50),
  entry_date      DATE NOT NULL,
  truck_number    VARCHAR(30) NOT NULL,
  no_of_bags      INT,
  received_qty_mt DECIMAL(10,3),
  net_qty_mt      DECIMAL(10,3) NOT NULL,
  total_qty_mt    DECIMAL(12,3),
  item_name       VARCHAR(100),
  status          ENUM('pending','flagged','approved','linked','rejected') DEFAULT 'pending',
  reviewed_by     VARCHAR(100),
  reviewed_at     DATETIME,
  receipt_id      INT,
  receipt_created BOOLEAN DEFAULT FALSE,
  dedupe_key      VARCHAR(255) NOT NULL,
  ocr_source      ENUM('paddle','gemini','manual') DEFAULT 'paddle',
  ocr_confidence  DECIMAL(4,3),
  ocr_raw_json    TEXT,
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_pue_dedupe (dedupe_key),
  INDEX idx_pue_master (master_id),
  INDEX idx_pue_status (status),
  FOREIGN KEY (master_id) REFERENCES plant_unloading_masters(id) ON DELETE CASCADE,
  FOREIGN KEY (receipt_id) REFERENCES plant_receipts(id) ON DELETE SET NULL
);

-- ============================================================
-- PURCHASE BILLS (what we owe brokers — generated from bills)
-- ============================================================

CREATE TABLE purchase_bills (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  bill_id         INT NOT NULL UNIQUE,
  deal_id         INT NOT NULL,
  broker_id       INT NOT NULL,
  pb_number       VARCHAR(50) UNIQUE,            -- our internal purchase bill number
  qty_mt          DECIMAL(10,2) NOT NULL,        -- accepted qty only
  rate_per_mt     DECIMAL(10,2) NOT NULL,
  total_amount    DECIMAL(14,2) NOT NULL,
  bill_date       DATE NOT NULL,
  due_date        DATE,
  status          ENUM('draft','confirmed','paid','cancelled') DEFAULT 'draft',
  busy_exported   BOOLEAN DEFAULT FALSE,
  busy_export_at  DATETIME,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (bill_id)   REFERENCES bills(id),
  FOREIGN KEY (deal_id)   REFERENCES deals(id),
  FOREIGN KEY (broker_id) REFERENCES brokers(id)
);

-- ============================================================
-- SALES BILLS (what RCDF owes us — generated per plant delivery)
-- ============================================================

CREATE TABLE sales_bills (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  tender_id       INT NOT NULL,
  plant_id        INT NOT NULL,
  sb_number       VARCHAR(50) UNIQUE,
  qty_mt          DECIMAL(10,2) NOT NULL,
  rate_per_mt     DECIMAL(10,2) NOT NULL,
  total_amount    DECIMAL(14,2) NOT NULL,
  bill_date       DATE NOT NULL,
  due_date        DATE,
  status          ENUM('draft','sent','paid','overdue','cancelled') DEFAULT 'draft',
  busy_exported   BOOLEAN DEFAULT FALSE,
  busy_export_at  DATETIME,
  paid_at         DATETIME,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (tender_id) REFERENCES tenders(id),
  FOREIGN KEY (plant_id)  REFERENCES plants(id)
);

-- ============================================================
-- PAYMENTS (to brokers)
-- ============================================================

CREATE TABLE payments (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  purchase_bill_id INT NOT NULL,
  broker_id       INT NOT NULL,
  voucher_number  VARCHAR(50),
  amount          DECIMAL(14,2) NOT NULL,
  payment_date    DATE,
  payment_mode    ENUM('neft','rtgs','cheque','cash','upi') DEFAULT 'neft',
  reference_no    VARCHAR(100),
  status          ENUM('pending','processed','failed') DEFAULT 'pending',
  busy_exported   BOOLEAN DEFAULT FALSE,
  busy_export_at  DATETIME,
  notes           TEXT,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (purchase_bill_id) REFERENCES purchase_bills(id),
  FOREIGN KEY (broker_id)        REFERENCES brokers(id)
);

-- ============================================================
-- MARKET PRICES (for tender bidding intelligence)
-- ============================================================

CREATE TABLE market_prices (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  material_id   INT NOT NULL,
  price_date    DATE NOT NULL,
  price_per_mt  DECIMAL(10,2) NOT NULL,
  market        VARCHAR(100),                   -- e.g. "Jodhpur Mandi"
  source        ENUM('manual','agmarknet','ncdex','scrape') DEFAULT 'manual',
  notes         TEXT,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (material_id) REFERENCES materials(id),
  UNIQUE KEY uq_material_date_market (material_id, price_date, market)
);

-- ============================================================
-- BUSY EXPORT LOG
-- ============================================================

CREATE TABLE busy_exports (
  id           INT AUTO_INCREMENT PRIMARY KEY,
  export_type  ENUM('purchase_bill','sales_bill','payment_voucher','busy_staging_bill') NOT NULL,
  record_ids   JSON NOT NULL,                   -- array of IDs exported
  file_path    VARCHAR(500),
  exported_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  exported_by  VARCHAR(100)
);

-- ============================================================
-- BUSY STAGING BILLS (isolated Busy export uploads)
-- ============================================================

CREATE TABLE busy_staging_bills (
  id              INT AUTO_INCREMENT PRIMARY KEY,
  company_id      INT NULL,
  source          VARCHAR(20) DEFAULT 'web',
  image_path      VARCHAR(500),
  file_hash       VARCHAR(64),
  broker_name     VARCHAR(200),
  vehicle_number  VARCHAR(20),
  material_name   VARCHAR(100),
  qty_mt          DECIMAL(10,2),
  rate_per_mt     DECIMAL(10,2),
  total_amount    DECIMAL(14,2),
  bill_date       DATE,
  bill_number     VARCHAR(100),
  plant_name      VARCHAR(100),
  ocr_source      ENUM('paddle','gemini','manual') DEFAULT 'paddle',
  ocr_confidence  DECIMAL(4,3),
  ocr_raw_text    TEXT,
  is_handwritten  BOOLEAN DEFAULT FALSE,
  validation_amount   BOOLEAN DEFAULT FALSE,
  validation_vehicle  BOOLEAN DEFAULT FALSE,
  validation_material BOOLEAN DEFAULT FALSE,
  busy_exported   BOOLEAN DEFAULT FALSE,
  busy_exported_at DATETIME,
  created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_busy_staging_bills_file_hash (file_hash),
  INDEX idx_busy_staging_bills_company (company_id),
  INDEX idx_busy_staging_bills_exported (busy_exported),
  INDEX idx_busy_staging_bills_created (created_at),
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

-- ============================================================
-- COMPANY + MAIN TENDER HIERARCHY (Company -> Main Tender -> Sub-Tender)
-- ============================================================

CREATE TABLE IF NOT EXISTS companies (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  name        VARCHAR(200) NOT NULL UNIQUE,
  code        VARCHAR(50) UNIQUE,
  is_active   BOOLEAN DEFAULT TRUE,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS main_tenders (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  company_id  INT NOT NULL,
  tender_code VARCHAR(100) NOT NULL,
  title       VARCHAR(200),
  notes       TEXT,
  is_active   BOOLEAN DEFAULT TRUE,
  created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  UNIQUE KEY uq_main_tenders_company_code (company_id, tender_code),
  INDEX idx_main_tenders_company (company_id),
  FOREIGN KEY (company_id) REFERENCES companies(id)
);

ALTER TABLE sproxx_cycles ADD COLUMN IF NOT EXISTS company_id INT NULL;

ALTER TABLE tenders ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE tenders ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE tenders ADD INDEX idx_tenders_scope (company_id, main_tender_id, created_at);

ALTER TABLE deals ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE deals ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE deals ADD INDEX idx_deals_scope (company_id, main_tender_id, tender_id);

ALTER TABLE bills ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE bills ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE bills ADD COLUMN IF NOT EXISTS tender_id INT NULL;
ALTER TABLE bills ADD INDEX idx_bills_scope (company_id, main_tender_id, tender_id, status);

ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE dispatches ADD COLUMN IF NOT EXISTS tender_id INT NULL;
ALTER TABLE dispatches ADD INDEX idx_dispatch_scope (company_id, main_tender_id, tender_id, is_deleted);

ALTER TABLE plant_receipts ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE plant_receipts ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE plant_receipts ADD COLUMN IF NOT EXISTS tender_id INT NULL;
ALTER TABLE plant_receipts ADD INDEX idx_receipt_scope (company_id, main_tender_id, tender_id, is_deleted);

ALTER TABLE plant_unloading_masters ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE plant_unloading_masters ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE plant_unloading_masters ADD COLUMN IF NOT EXISTS tender_id INT NULL;

ALTER TABLE plant_unloading_entries ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE plant_unloading_entries ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE plant_unloading_entries ADD COLUMN IF NOT EXISTS tender_id INT NULL;

ALTER TABLE purchase_bills ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE purchase_bills ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE purchase_bills ADD COLUMN IF NOT EXISTS tender_id INT NULL;

ALTER TABLE sales_bills ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE sales_bills ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;

ALTER TABLE payments ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS tender_id INT NULL;

ALTER TABLE market_prices ADD COLUMN IF NOT EXISTS company_id INT NULL;

ALTER TABLE busy_exports ADD COLUMN IF NOT EXISTS company_id INT NULL;
ALTER TABLE busy_exports ADD COLUMN IF NOT EXISTS main_tender_id INT NULL;

-- ============================================================
-- VIEWS for common queries
-- ============================================================

CREATE OR REPLACE VIEW v_tender_summary AS
SELECT
  t.id,
  t.tender_number,
  p.name  AS plant,
  m.name  AS material,
  sc.name AS cycle,
  t.tender_mt,
  t.week1_target_mt,
  t.week1_deadline,
  t.week2_deadline,
  t.status,
  COALESCE(SUM(d.deal_mt),      0) AS total_deal_mt,
  COALESCE(SUM(d.dispatched_mt),0) AS total_dispatched_mt,
  COALESCE(SUM(d.accepted_mt),  0) AS total_accepted_mt,
  COALESCE(SUM(d.rejected_mt),  0) AS total_rejected_mt,
  ROUND(COALESCE(SUM(d.accepted_mt),0) / t.tender_mt * 100, 1) AS accepted_pct,
  ROUND(COALESCE(SUM(d.accepted_mt),0) / t.week1_target_mt * 100, 1) AS week1_pct
FROM tenders t
JOIN plants        p  ON t.plant_id    = p.id
JOIN materials     m  ON t.material_id = m.id
JOIN sproxx_cycles sc ON t.cycle_id    = sc.id
LEFT JOIN deals    d  ON d.tender_id   = t.id AND d.status != 'cancelled'
GROUP BY t.id;

CREATE OR REPLACE VIEW v_bill_summary AS
SELECT
  b.*,
  br.name  AS broker_name_resolved,
  p.name   AS plant_name_resolved,
  m.name   AS material_name_resolved,
  d.deal_number
FROM bills b
LEFT JOIN brokers   br ON b.broker_id   = br.id
LEFT JOIN plants    p  ON b.plant_id    = p.id
LEFT JOIN materials m  ON b.material_id = m.id
LEFT JOIN deals     d  ON b.deal_id     = d.id;

-- ============================================================
-- SAMPLE SPROXX CYCLE
-- ============================================================

INSERT INTO sproxx_cycles (name, cycle_start, cycle_end, week1_end, week2_end, is_active)
VALUES ('Mar 18–31 2026', '2026-03-18', '2026-03-31', '2026-03-24', '2026-03-31', TRUE);

-- Sample brokers
INSERT INTO brokers (name, phone) VALUES
  ('Sharma Traders',    '9876543210'),
  ('Gupta Feed Co.',    '9876543211'),
  ('Ram Agro',          '9876543212'),
  ('Verma Bros',        '9876543213'),
  ('Rajput Traders',    '9876543214'),
  ('Singh Commodities', '9876543215'),
  ('Meena Traders',     '9876543216'),
  ('Agarwal Agro',      '9876543217');
