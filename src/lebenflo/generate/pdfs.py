"""Draw the synthetic documents as PDFs with reportlab.

Layouts are deliberately simple "label: value" forms so Document Intelligence can read them,
and every page carries the SAMPLE watermark.
"""

from pathlib import Path

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from lebenflo.generate.profiles import Applicant

WATERMARK = "SAMPLE – SYNTHETIC TEST DATA"
WIDTH, HEIGHT = letter


def new_canvas(path: Path) -> Canvas:
    # Uncompressed so the watermark text is directly searchable (tests check for it).
    return Canvas(str(path), pagesize=letter, pageCompression=0)


def money(x: float) -> str:
    return f"${x:,.2f}"


def us_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{m}/{d}/{y}"


def watermark(c: Canvas) -> None:
    """Large diagonal watermark plus a footer line, drawn on every page."""
    c.saveState()
    c.setFillColor(Color(0.85, 0.1, 0.1, alpha=0.18))
    c.setFont("Helvetica-Bold", 40)
    c.translate(WIDTH / 2, HEIGHT / 2)
    c.rotate(35)
    c.drawCentredString(0, 0, WATERMARK)
    c.restoreState()
    c.setFont("Helvetica", 8)
    c.drawCentredString(WIDTH / 2, 30, f"{WATERMARK} – fictional document, not valid for any use")


def rows(
    c: Canvas,
    x: float,
    y: float,
    items: list[tuple[str, str]],
    gap: float = 18,
    label_width: float = 170,
) -> float:
    """Draw 'Label: value' rows and return the y position after the last row."""
    for label, value in items:
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(x + label_width, y, value)
        y -= gap
    return y


def header(c: Canvas, title: str, subtitle: str) -> None:
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, HEIGHT - 60, title)
    c.setFont("Helvetica", 10)
    c.drawString(50, HEIGHT - 78, subtitle)
    c.line(50, HEIGHT - 88, WIDTH - 50, HEIGHT - 88)


def draw_pay_stub(a: Applicant, f: dict, path: Path) -> None:
    c = new_canvas(path)
    header(c, "EARNINGS STATEMENT", f"{f['employer_name']} – Payroll Department")
    y = rows(
        c,
        50,
        HEIGHT - 120,
        [
            ("Employer", f["employer_name"]),
            ("Employee Name", f["employee_name"]),
            ("Employee Address", a.address),
            ("Social Security Number", f["employee_ssn"]),
            ("Pay Period Start", us_date(f["pay_period_start"])),
            ("Pay Period End", us_date(f["pay_period_end"])),
            ("Pay Date", us_date(f["pay_date"])),
        ],
    )
    # Earnings table: current period vs year to date.
    y -= 10
    c.setFont("Helvetica-Bold", 10)
    for x, text in [(50, "Earnings"), (300, "Current"), (420, "Year to Date")]:
        c.drawString(x, y, text)
    c.setFont("Helvetica", 10)
    for label, cur, ytd in [
        ("Gross Pay", f["gross_pay"], f["ytd_gross_pay"]),
        (
            "Taxes and Deductions",
            f["gross_pay"] - f["net_pay"],
            f["ytd_gross_pay"] - round(f["ytd_gross_pay"] * 0.76, 2),
        ),
        ("Net Pay", f["net_pay"], round(f["ytd_gross_pay"] * 0.76, 2)),
    ]:
        y -= 18
        c.drawString(50, y, label)
        c.drawString(300, y, money(cur))
        c.drawString(420, y, money(ytd))
    watermark(c)
    c.save()


def draw_w2(a: Applicant, f: dict, path: Path) -> None:
    c = new_canvas(path)
    header(
        c,
        f"Form W-2 Wage and Tax Statement {f['tax_year']}",
        "Copy B – To Be Filed With Employee's FEDERAL Tax Return",
    )
    rows(
        c,
        50,
        HEIGHT - 120,
        [
            ("a Employee's social security number", f["employee_ssn"]),
            ("b Employer identification number", "00-0000000"),
            ("c Employer's name", f["employer_name"]),
            ("e Employee's name", f["employee_name"]),
            ("f Employee's address", a.address),
            ("1 Wages, tips, other compensation", money(f["wages"])),
            ("2 Federal income tax withheld", money(round(f["wages"] * 0.12, 2))),
            ("3 Social security wages", money(f["wages"])),
            ("5 Medicare wages and tips", money(f["wages"])),
        ],
        gap=22,
        label_width=230,
    )
    watermark(c)
    c.save()


def draw_bank_statement(a: Applicant, f: dict, path: Path) -> None:
    c = new_canvas(path)
    header(
        c, "Lebenflo Credit Union – Member Account Statement", "Lebenflo Credit Union is fictional"
    )
    y = rows(
        c,
        50,
        HEIGHT - 120,
        [
            ("Account Holder", f["account_holder_name"]),
            ("Address", a.address),
            ("Account Type", "Share Draft Checking"),
            ("Account Number", f["account_number"]),
            (
                "Statement Period",
                f"{us_date(f['statement_start'])} - {us_date(f['statement_end'])}",
            ),
            ("Beginning Balance", money(f["beginning_balance"])),
            ("Ending Balance", money(f["ending_balance"])),
        ],
    )
    y -= 10
    c.setFont("Helvetica-Bold", 10)
    for x, text in [(50, "Date"), (130, "Description"), (360, "Deposits"), (460, "Withdrawals")]:
        c.drawString(x, y, text)
    c.setFont("Helvetica", 10)
    lines = [
        ("09/15/2026", f"Payroll {a.employer}", f["_deposits"][0], None),
        ("09/30/2026", f"Payroll {a.employer}", f["_deposits"][1], None),
    ]
    for day, amount in zip(
        ["09/04/2026", "09/11/2026", "09/19/2026", "09/26/2026"], f["_withdrawals"], strict=True
    ):
        lines.append((day, "Card purchase", None, amount))
    for day, desc, dep, wd in sorted(lines):
        y -= 16
        c.drawString(50, y, day)
        c.drawString(130, y, desc)
        c.drawString(360, y, money(dep) if dep else "")
        c.drawString(460, y, money(wd) if wd else "")
    watermark(c)
    c.save()


def draw_drivers_license(a: Applicant, f: dict, path: Path) -> None:
    c = new_canvas(path)
    # A card-shaped box near the top of the page, like a photocopy of a license.
    x0, y0, w, h = 60, HEIGHT - 300, 400, 230
    c.roundRect(x0, y0, w, h, 12)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(x0 + 15, y0 + h - 25, "STATE OF NORTHMARCH  DRIVER LICENSE")
    c.rect(x0 + 15, y0 + 20, 90, 120)  # photo placeholder
    c.setFont("Helvetica", 7)
    c.drawCentredString(x0 + 60, y0 + 78, "NO PHOTO – SAMPLE")
    rows(
        c,
        x0 + 115,
        y0 + h - 55,
        [
            ("DL NO", f["document_number"]),
            ("LAST NAME", f["last_name"].upper()),
            ("FIRST NAME", f["first_name"].upper()),
            ("DOB", us_date(f["date_of_birth"])),
            ("EXP", us_date(f["date_of_expiration"])),
            ("ISS", "01/15/2024"),
            ("ADDRESS", a.address.split(",")[0].upper()),
        ],
        gap=17,
        label_width=80,
    )
    watermark(c)
    c.save()


DRAWERS = {
    "pay_stub": draw_pay_stub,
    "w2": draw_w2,
    "bank_statement": draw_bank_statement,
    "drivers_license": draw_drivers_license,
}
