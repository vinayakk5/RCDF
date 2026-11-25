# Tender_Preparation

Complete automated toolkit for downloading Cattle Feed Raw Material BOQ Excel files from eProc Rajasthan and organizing Demand Draft (DD) files plant-wise.

---

## 1. Directory Structure

```text
Tender_Preparation/
├── .venv/                      # Self-contained virtual environment (Playwright + PyPDF)
├── captcha_images/             # Saved CAPTCHA images (e.g. captcha_jodhpur.png)
├── eproc_boq_downloader.py     # Cattle Feed BOQ Downloader with on-screen verification
├── dd_sorter.py                # Standalone DD ZIP & allocation PDF sorter
├── run_boq_downloader.bat      # 1-Click launcher to download all BOQs
├── run_dd_sorter.bat           # 1-Click launcher to sort DD files
├── README.md                   # Documentation
└── Tender_Prep_YYYY-MM-DD/     # Organized plant folders containing BOQs & DDs
    ├── Ajmer/
    ├── Bikaner/
    ├── Gulabpura/
    ├── Jodhpur/
    ├── Kaladera/
    ├── Lambiyakalan/
    ├── Nadbai/
    └── Pali/
```

---

## 2. Usage Instructions

### A. Download Current Active BOQs (1-Click)
Double-click `run_boq_downloader.bat` or run:
```powershell
.\run_boq_downloader.bat
```
* As each plant's download modal is reached, a clean on-screen dialog displays the 5-character CAPTCHA image with an auto-focused input box.
* Type the 5 characters and hit **Enter**.
* The genuine `.xls` BOQ is automatically extracted from the government ZIP, saved to `Tender_Prep_<YYYY-MM-DD>/<Plant>/`, and the image is preserved in `captcha_images/`.

### B. Sort & Organize DD PDFs / Images (1-Click Auto-Detect)
Put your DD `.zip` archive (containing both the scanned DDs and your handwritten/printed allocation sheet) in the `Tender_Preparation` folder and **double-click `run_dd_sorter.bat`** (or drag-and-drop any `.zip` onto it):
```powershell
.\run_dd_sorter.bat
```
* Automatically picks up the `.zip` file in the same folder (or pass an explicit path: `.\run_dd_sorter.bat "path\to\DDs.zip"`).
* Uses RCDF's free Vision LLM pipeline (`Mistral Pixtral` -> `Gemini Flash` -> `OpenRouter :free` -> `Azure Read OCR`) to read both the handwritten mapping note and the MICR/DD numbers on every scanned Demand Draft.
* Copies & renames each DD PDF (`DD<num><Plant>.pdf`, strictly alphanumeric with zero special characters for eProc upload compatibility) right next to that plant's `BOQ_XXXXX.xls`.
