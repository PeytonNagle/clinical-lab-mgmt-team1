from io import BytesIO

from barcode import Code128
from barcode.writer import SVGWriter


def barcode_svg(value):
    """Return a Code 128 barcode for `value` as an inline <svg> string.

    Built in memory (no image files, no Pillow). The library's text under the bars is
    turned off because the label template prints the value itself.
    """
    buffer = BytesIO()
    Code128(str(value), writer=SVGWriter()).write(
        buffer,
        options={
            "write_text": False,
            # Narrowest bar in mm; 0.3 scans more reliably than the library's 0.2 default.
            "module_width": 0.3,
            "module_height": 10.0,
            "quiet_zone": 3.0,
        },
    )
    svg = buffer.getvalue().decode("utf-8")
    # Drop the XML declaration and DOCTYPE, which don't belong inside an HTML page.
    return svg[svg.index("<svg"):]
