from io import BytesIO
from pypdf import PdfReader, PdfWriter

from compiler import compile_rules


def make_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)

    # Add text through a simple generated PDF fixture.
    # Blank PDFs have no extractable text, so use a real fixture
    # PDF for the actual compiler test.
    output = BytesIO()
    writer.write(output)
    output.seek(0)
    return output


def test_blank_pdf_returns_no_rules():
    pdf = make_pdf()
    assert compile_rules(pdf) == []
