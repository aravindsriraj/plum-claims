"""Mock document generator: renders realistic Indian medical documents as
JPEG images for demoing the vision extraction path.

Usage:  .venv/bin/python ../scripts/generate_mock_docs.py [output_dir]

Generates a matched prescription + hospital bill pair (TC004-style) plus one
blurry bill for the unreadable-document demo.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 850, 1100
MARGIN = 60


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _new_page() -> tuple[Image.Image, ImageDraw.Draw]:
    img = Image.new("RGB", (W, H), color="white")
    return img, ImageDraw.Draw(img)


def make_prescription(path: Path) -> None:
    img, d = _new_page()
    f_head, f_body, f_small = _font(26), _font(22), _font(19)
    y = MARGIN
    d.line((MARGIN, 110, W - MARGIN, 110), fill="black", width=2)
    d.text((MARGIN, y), "Dr. Arun Sharma, MBBS, MD (Internal Medicine)", font=f_head, fill="black"); y += 36
    d.text((MARGIN, y), "Reg. No: KA/45678/2015", font=f_small, fill="black"); y += 28
    d.text((MARGIN, y), "City Medical Centre, 12 MG Road, Bengaluru", font=f_small, fill="black"); y += 28
    d.text((MARGIN, y), "Ph: +91-80-4123-8890", font=f_small, fill="black"); y += 70
    d.text((MARGIN, y), "Patient: Rajesh Kumar          Date: 01-Nov-2024", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Age: 39 years   Gender: M", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Chief Complaint: Fever since 3 days, body ache", font=f_body, fill="black"); y += 60
    d.text((MARGIN, y), "Diagnosis: Viral Fever", font=f_body, fill="black"); y += 60
    d.text((MARGIN, y), "Rx:", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "1. Tab Paracetamol 650mg - 1-1-1 x 5 days", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "2. Tab Vitamin C 500mg - 0-0-1 x 7 days", font=f_body, fill="black"); y += 60
    d.text((MARGIN, y), "Investigations: CBC, Dengue NS1", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Follow-up: After 5 days if no improvement", font=f_body, fill="black")
    d.text((W - MARGIN - 260, H - 160), "[Signature]", font=f_small, fill="gray")
    d.ellipse((W - MARGIN - 240, H - 140, W - MARGIN - 60, H - 60), outline="blue", width=3)
    d.text((W - MARGIN - 225, H - 115), "KA/45678", font=_font(16), fill="blue")
    img.save(path, "JPEG", quality=92)


def make_hospital_bill(path: Path) -> None:
    img, d = _new_page()
    f_head, f_body, f_small = _font(28), _font(22), _font(19)
    y = MARGIN
    d.text((MARGIN, y), "CITY MEDICAL CENTRE", font=f_head, fill="black"); y += 40
    d.text((MARGIN, y), "12 MG Road, Bengaluru - 560001", font=f_small, fill="black"); y += 28
    d.text((MARGIN, y), "GSTIN: 29ABCDE1234F1Z5   Ph: 080-4123-8890", font=f_small, fill="black"); y += 50
    d.line((MARGIN, y, W - MARGIN, y), fill="black", width=2); y += 20
    d.text((MARGIN, y), "BILL / RECEIPT", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Bill No: CMC/2024/08321    Date: 01-Nov-2024", font=f_small, fill="black"); y += 50
    d.text((MARGIN, y), "Patient Name: Rajesh Kumar", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Age/Gender: 39 / Male", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Referring Doctor: Dr. Arun Sharma", font=f_body, fill="black"); y += 60
    d.text((MARGIN, y), "DESCRIPTION                              AMOUNT", font=f_small, fill="black"); y += 32
    d.line((MARGIN, y, W - MARGIN, y), fill="black", width=1); y += 16
    for desc, amt in [("Consultation Fee (OPD)", "1000.00"),
                      ("CBC (Complete Blood Count)", "300.00"),
                      ("Dengue NS1 Antigen Test", "200.00")]:
        d.text((MARGIN, y), desc, font=f_body, fill="black")
        d.text((W - MARGIN - 160, y), amt, font=f_body, fill="black"); y += 36
    y += 30
    d.line((MARGIN, y, W - MARGIN, y), fill="black", width=1); y += 16
    d.text((MARGIN, y), "Subtotal:", font=f_body, fill="black")
    d.text((W - MARGIN - 160, y), "1500.00", font=f_body, fill="black"); y += 36
    d.text((MARGIN, y), "GST (0% on medical):", font=f_body, fill="black")
    d.text((W - MARGIN - 160, y), "0.00", font=f_body, fill="black"); y += 36
    d.text((MARGIN, y), "Total Amount:", font=f_head, fill="black")
    d.text((W - MARGIN - 160, y), "1500.00", font=f_head, fill="black"); y += 60
    d.text((MARGIN, y), "Payment Mode: UPI", font=f_small, fill="black")
    img.save(path, "JPEG", quality=92)


def make_blurry_bill(path: Path) -> None:
    """Same bill, but degraded past readability — for the TC002-style demo."""
    tmp = path.with_suffix(".tmp.jpg")
    make_hospital_bill(tmp)
    img = Image.open(tmp)
    img = img.filter(ImageFilter.GaussianBlur(radius=9))
    img = img.resize((W // 2, H // 2)).resize((W, H))  # downscale+upscale kills detail
    img = img.filter(ImageFilter.GaussianBlur(radius=5))
    img.save(path, "JPEG", quality=40)
    tmp.unlink()


def make_apollo_bill(path: Path) -> None:
    """₹4,500 bill at Apollo Hospitals (a network hospital) — for the
    TC010-style network discount demo: 4,500 -> 3,600 -> 3,240."""
    img, d = _new_page()
    f_head, f_body, f_small = _font(28), _font(22), _font(19)
    y = MARGIN
    d.text((MARGIN, y), "APOLLO HOSPITALS", font=f_head, fill="black"); y += 40
    d.text((MARGIN, y), "154/11 Bannerghatta Road, Bengaluru - 560076", font=f_small, fill="black"); y += 28
    d.text((MARGIN, y), "GSTIN: 29AAACA1234A1Z2   Ph: 080-2630-4050", font=f_small, fill="black"); y += 50
    d.line((MARGIN, y, W - MARGIN, y), fill="black", width=2); y += 20
    d.text((MARGIN, y), "BILL / RECEIPT", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Bill No: APL/2024/55190    Date: 03-Nov-2024", font=f_small, fill="black"); y += 50
    d.text((MARGIN, y), "Patient Name: Deepak Shah", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Age/Gender: 44 / Male", font=f_body, fill="black"); y += 34
    d.text((MARGIN, y), "Referring Doctor: Dr. S. Iyer", font=f_body, fill="black"); y += 60
    d.text((MARGIN, y), "DESCRIPTION                              AMOUNT", font=f_small, fill="black"); y += 32
    d.line((MARGIN, y, W - MARGIN, y), fill="black", width=1); y += 16
    for desc, amt in [("Consultation Fee (OPD)", "1500.00"),
                      ("Medicines (Amoxicillin, Inhaler)", "3000.00")]:
        d.text((MARGIN, y), desc, font=f_body, fill="black")
        d.text((W - MARGIN - 160, y), amt, font=f_body, fill="black"); y += 36
    y += 30
    d.line((MARGIN, y, W - MARGIN, y), fill="black", width=1); y += 16
    d.text((MARGIN, y), "Total Amount:", font=f_head, fill="black")
    d.text((W - MARGIN - 160, y), "4500.00", font=f_head, fill="black"); y += 60
    d.text((MARGIN, y), "Payment Mode: Card", font=f_small, fill="black")
    img.save(path, "JPEG", quality=92)


if __name__ == "__main__":
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "mock_docs"
    out_dir.mkdir(parents=True, exist_ok=True)
    make_prescription(out_dir / "prescription_rajesh.jpg")
    make_hospital_bill(out_dir / "bill_rajesh.jpg")
    make_blurry_bill(out_dir / "blurry_bill.jpg")
    make_apollo_bill(out_dir / "bill_apollo_deepak.jpg")
    print(f"Generated 4 mock documents in {out_dir}")
