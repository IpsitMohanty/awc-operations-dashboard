from pathlib import Path


def wrap_text(text: str, width: int = 92) -> list[str]:
    lines = []
    for raw in text.splitlines():
        if not raw.strip():
            lines.append("")
            continue
        words = raw.split()
        current = words[0]
        for word in words[1:]:
            if len(current) + 1 + len(word) <= width:
                current += " " + word
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_text_stream(page_lines: list[str]) -> bytes:
    content_lines = ["BT", "0.1 0.1 0.1 rg", "/F1 10 Tf", "50 790 Td", "14 TL"]
    first = True
    for line in page_lines:
        safe = esc(line)
        if first:
            content_lines.append(f"({safe}) Tj")
            first = False
        else:
            content_lines.append("T*")
            content_lines.append(f"({safe}) Tj")
    content_lines.append("ET")
    return "\n".join(content_lines).encode("latin-1", errors="replace")


def build_architecture_stream() -> bytes:
    commands = []

    def rect(x, y, w, h):
        commands.append(f"{x} {y} {w} {h} re S")

    def text(x, y, size, value):
        commands.append("BT")
        commands.append("0.1 0.1 0.1 rg")
        commands.append(f"/F1 {size} Tf")
        commands.append(f"{x} {y} Td")
        commands.append(f"({esc(value)}) Tj")
        commands.append("ET")

    def line(x1, y1, x2, y2):
        commands.append(f"{x1} {y1} m {x2} {y2} l S")

    def arrow(x1, y1, x2, y2):
        line(x1, y1, x2, y2)
        if x2 >= x1 and abs(y2 - y1) < 2:
            line(x2 - 8, y2 + 4, x2, y2)
            line(x2 - 8, y2 - 4, x2, y2)
        elif y2 >= y1:
            line(x2 - 4, y2 - 8, x2, y2)
            line(x2 + 4, y2 - 8, x2, y2)

    commands.append("0.2 0.16 0.1 RG")
    commands.append("0.98 0.96 0.92 rg")
    commands.append("0 0 612 792 re f")
    commands.append("0.84 0.79 0.71 RG")
    commands.append("0.1 0.1 0.1 rg")
    commands.append("1 w")

    text(40, 748, 18, "Monitoring Architecture for Child Health Risk Surveillance")
    text(40, 728, 10, "From messy monthly data to monitoring, escalation, and programme decision support")

    boxes = [
        (40, 600, 120, 70, "Monthly data", ["AWC files", "counts + burden"]),
        (190, 600, 140, 70, "Quality checks", ["schema / period", "duplicates / drift"]),
        (360, 600, 140, 70, "Harmonized data", ["one row per", "AWC per month"]),
        (520, 600, 60, 70, "Indicators", ["rates", "efficiency"]),
        (80, 420, 140, 80, "Anomaly logic", ["previous month", "rolling baseline"]),
        (250, 420, 140, 80, "Risk logic", ["burden thresholds", "LOW / MED / HIGH"]),
        (420, 420, 150, 80, "Escalation", ["new high risk", "escalated / persistent"]),
        (150, 250, 150, 80, "Warehouse + dashboard", ["facts / marts", "filters / export"]),
        (350, 250, 180, 80, "Programme use", ["review + targeting", "evaluation readiness"]),
    ]

    for x, y, w, h, title, body in boxes:
        rect(x, y, w, h)
        text(x + 8, y + h - 18, 11, title)
        text(x + 8, y + h - 36, 9, body[0])
        text(x + 8, y + h - 50, 9, body[1])

    arrow(160, 635, 190, 635)
    arrow(330, 635, 360, 635)
    arrow(500, 635, 520, 635)
    arrow(550, 600, 495, 540)
    arrow(430, 600, 320, 540)
    arrow(390, 600, 150, 540)
    arrow(150, 420, 220, 330)
    arrow(220, 460, 250, 460)
    arrow(495, 420, 440, 330)
    arrow(390, 460, 420, 460)
    arrow(300, 290, 350, 290)

    text(40, 90, 10, "Core idea: routine frontline data becomes useful only after standardization,")
    text(40, 76, 10, "quality checks, indicator construction, and escalation logic that teams can act on.")
    return "\n".join(commands).encode("latin-1", errors="replace")


def build_pdf(streams: list[bytes], output_path: Path) -> None:
    font_object_id = 3
    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [] /Count 0 >>"),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
    ]
    content_ids = []
    page_ids = []
    next_id = 4

    for stream in streams:
        content_id = next_id
        next_id += 1
        page_id = next_id
        next_id += 1
        content_ids.append(content_id)
        page_ids.append(page_id)
        objects.append((content_id, f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"))
        page_body = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
            f"/Resources << /Font << /F1 {font_object_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("latin-1")
        objects.append((page_id, page_body))

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[1] = (2, f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1"))
    objects.sort(key=lambda x: x[0])

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj_id, content in objects:
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        pdf.extend(content)
        pdf.extend(b"\nendobj\n")

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode("latin-1"))
    output_path.write_bytes(pdf)


def main() -> None:
    folder = Path(__file__).resolve().parent
    text = (folder / "application_work_product.md").read_text(encoding="utf-8")
    lines = wrap_text(text, width=92)
    pages = []
    page_lines = []
    max_lines = 46
    for line in lines:
        page_lines.append(line)
        if len(page_lines) >= max_lines:
            pages.append(page_lines)
            page_lines = []
    if page_lines:
        pages.append(page_lines)

    streams = [build_text_stream(page) for page in pages]
    streams.append(build_architecture_stream())
    output_path = folder / "suvita_upload_work_product.pdf"
    build_pdf(streams, output_path)
    print(f"PDF written to: {output_path}")


if __name__ == "__main__":
    main()
