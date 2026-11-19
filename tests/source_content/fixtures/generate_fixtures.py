"""Generate deterministic, non-domain-specific extraction benchmark inputs."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from pptx import Presentation
from pptx.chart.data import ChartData
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE, PP_PLACEHOLDER
from pptx.util import Inches
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas


def _image_with_text(path: Path, lines: list[str]) -> None:
    image = Image.new("RGB", (1600, 1000), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=48)
    y = 100
    for line in lines:
        draw.text((100, y), line, fill="black", font=font)
        y += 90
    image.save(path, format="PNG")


def _multi_column_pdf(path: Path) -> None:
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=True)
    pdf.setTitle("Ordered extraction fixture")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(54, 750, "Ordered extraction fixture")
    pdf.setFont("Helvetica", 10)
    left = ["L1 first left block", "L2 second left block", "L3 third left block"]
    right = ["R1 first right block", "R2 second right block", "R3 third right block"]
    for index, text in enumerate(left):
        pdf.drawString(54, 700 - index * 28, text)
    for index, text in enumerate(right):
        pdf.drawString(320, 700 - index * 28, text)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(54, 575, "Table A")
    data = (("Role", "Decision"), ("Reviewer", "Approve"), ("Author", "Revise"))
    for row_index, row in enumerate(data):
        for column_index, value in enumerate(row):
            pdf.rect(54 + column_index * 160, 520 - row_index * 24, 160, 24)
            pdf.drawString(60 + column_index * 160, 528 - row_index * 24, value)
    pdf.showPage()
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(54, 750, "Second section")
    pdf.setFont("Helvetica", 10)
    pdf.drawString(54, 720, "A footnote marker appears here [1].")
    pdf.drawString(54, 60, "[1] Footnote content must remain attached to its reference.")
    pdf.save()


def _image_only_pdf(path: Path, work_dir: Path) -> None:
    image_path = work_dir / "image-only-page.png"
    _image_with_text(image_path, ["SCANNED PAGE", "Alpha precedes Beta", "Review is required"])
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=True)
    pdf.drawImage(ImageReader(str(image_path)), 36, 180, width=540, height=338)
    pdf.save()
    image_path.unlink()


def _mixed_pdf(path: Path, work_dir: Path) -> None:
    image_path = work_dir / "mixed-scanned-page.png"
    _image_with_text(image_path, ["SECOND PAGE IMAGE", "Exception follows the rule"])
    pdf = canvas.Canvas(str(path), pagesize=letter, invariant=True)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(54, 730, "First page native text must remain authoritative.")
    pdf.showPage()
    pdf.drawImage(ImageReader(str(image_path)), 36, 180, width=540, height=338)
    pdf.save()
    image_path.unlink()


def _pptx(path: Path) -> None:
    deck = Presentation()
    title_slide = deck.slides.add_slide(deck.slide_layouts[0])
    title_slide.shapes.title.text = "Structured presentation fixture"
    title_slide.placeholders[1].text = "Subtitle follows title"

    content_slide = deck.slides.add_slide(deck.slide_layouts[5])
    content_slide.shapes.title.text = "Process and evidence"
    for index, label in enumerate(("Collect", "Review", "Approve")):
        shape = content_slide.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE,
            Inches(0.8 + index * 2.8),
            Inches(2.0),
            Inches(2.0),
            Inches(0.8),
        )
        shape.text = label
    table = content_slide.shapes.add_table(2, 2, Inches(1.0), Inches(3.5), Inches(4.5), Inches(1.2)).table
    table.cell(0, 0).text = "Signal"
    table.cell(0, 1).text = "Action"
    table.cell(1, 0).text = "Low confidence"
    table.cell(1, 1).text = "Review source"

    chart_slide = deck.slides.add_slide(deck.slide_layouts[5])
    chart_slide.shapes.title.text = "Quarterly review completion"
    chart_data = ChartData()
    chart_data.categories = ["Q1", "Q2", "Q3"]
    chart_data.add_series("Completed", (40, 65, 85))
    chart_slide.shapes.add_chart(
        XL_CHART_TYPE.COLUMN_CLUSTERED,
        Inches(1.0),
        Inches(1.7),
        Inches(7.5),
        Inches(4.5),
        chart_data,
    )

    for slide, note in (
        (title_slide, "Introduce the purpose before the process."),
        (content_slide, "The order is Collect, Review, then Approve."),
        (chart_slide, "Completion increases across all three quarters."),
    ):
        notes_slide = slide.notes_slide
        for placeholder in notes_slide.placeholders:
            if placeholder.placeholder_format.type == PP_PLACEHOLDER.BODY:
                placeholder.text = note
                break

    deck.core_properties.title = "Structured presentation fixture"
    deck.core_properties.author = "Omnichannel Learning benchmark"
    deck.save(path)


def generate(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _multi_column_pdf(output_dir / "ordered-multicolumn.pdf")
    _image_only_pdf(output_dir / "image-only.pdf", output_dir)
    _mixed_pdf(output_dir / "mixed-native-scanned.pdf", output_dir)
    _pptx(output_dir / "structured-presentation.pptx")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    generate(args.output_dir)


if __name__ == "__main__":
    main()
