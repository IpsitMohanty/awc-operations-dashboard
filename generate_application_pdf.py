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


def escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_architecture_stream() -> bytes:
    commands = []

    def rect(x, y, w, h):
        commands.append(f"{x} {y} {w} {h} re S")

    def text(x, y, size, value):
        commands.append("BT")
        commands.append("0.1 0.1 0.1 rg")
        commands.append(f"/F1 {size} Tf")
        commands.append(f"{x} {y} Td")
        commands.append(f"({escape_pdf_text(value)}) Tj")
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
    commands.append("0 0 612 842 re f")
    commands.append("0.84 0.79 0.71 RG")
    commands.append("0.1 0.1 0.1 rg")
    commands.append("1 w")

    text(40, 790, 18, "Monitoring Architecture for Child Health Risk Surveillance")
    text(40, 770, 10, "From messy monthly data to monitoring, escalation, and programme decision support")

    boxes = [
        (40, 640, 120, 70, "Monthly data", ["AWC files", "counts + burden"]),
        (190, 640, 140, 70, "Quality checks", ["schema / period", "duplicates / drift"]),
        (360, 640, 140, 70, "Harmonized data", ["one row per", "AWC per month"]),
        (520, 640, 60, 70, "Indicators", ["rates", "efficiency"]),
        (80, 460, 140, 80, "Anomaly logic", ["previous month", "rolling baseline"]),
        (250, 460, 140, 80, "Risk logic", ["burden thresholds", "LOW / MED / HIGH"]),
        (420, 460, 150, 80, "Escalation", ["new high risk", "escalated / persistent"]),
        (150, 290, 150, 80, "Warehouse + dashboard", ["facts / marts", "filters / export"]),
        (350, 290, 180, 80, "Programme use", ["review + targeting", "evaluation readiness"]),
    ]

    for x, y, w, h, title, body in boxes:
        rect(x, y, w, h)
        text(x + 8, y + h - 18, 11, title)
        text(x + 8, y + h - 36, 9, body[0])
        text(x + 8, y + h - 50, 9, body[1])

    arrow(160, 675, 190, 675)
    arrow(330, 675, 360, 675)
    arrow(500, 675, 520, 675)
    arrow(550, 640, 495, 580)
    arrow(430, 640, 320, 580)
    arrow(390, 640, 150, 580)
    arrow(150, 460, 220, 370)
    arrow(220, 500, 250, 500)
    arrow(495, 460, 440, 370)
    arrow(390, 500, 420, 500)
    arrow(300, 330, 350, 330)

    text(40, 110, 10, "Core idea: routine frontline data becomes useful only after standardization,")
    text(40, 96, 10, "quality checks, indicator construction, and escalation logic that teams can act on.")
    return "\n".join(commands).encode("latin-1", errors="replace")


def build_pdf(lines: list[str], output_path: Path) -> None:
    include_architecture_page = "__ARCHITECTURE_PAGE__" in lines
    lines = [line for line in lines if line != "__ARCHITECTURE_PAGE__"]
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

    streams = []
    for page in pages:
        content_lines = ["BT", "/F1 10 Tf", "50 790 Td", "14 TL"]
        first = True
        for line in page:
            safe = escape_pdf_text(line)
            if first:
                content_lines.append(f"({safe}) Tj")
                first = False
            else:
                content_lines.append("T*")
                content_lines.append(f"({safe}) Tj")
        content_lines.append("ET")
        streams.append("\n".join(content_lines).encode("latin-1", errors="replace"))

    if include_architecture_page:
        streams.append(build_architecture_stream())

    objects = []
    page_object_ids = []
    content_object_ids = []
    font_object_id = 3
    next_id = 4

    for stream in streams:
        content_object_ids.append(next_id)
        objects.append((next_id, f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"))
        next_id += 1
        page_object_ids.append(next_id)
        next_id += 1

    objects.insert(0, (font_object_id, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
    objects.insert(0, (2, b"<< /Type /Pages /Kids [] /Count 0 >>"))
    objects.insert(0, (1, b"<< /Type /Catalog /Pages 2 0 R >>"))

    updated_objects = []
    for obj_id, content in objects:
        if obj_id == 2:
            kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
            content = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_object_ids)} >>".encode("latin-1")
        updated_objects.append((obj_id, content))

    final_objects = []
    page_idx = 0
    for obj_id, content in updated_objects:
        final_objects.append((obj_id, content))
        if obj_id in content_object_ids:
            page_obj_id = page_object_ids[page_idx]
            page_content_id = content_object_ids[page_idx]
            page_body = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
                f"/Resources << /Font << /F1 {font_object_id} 0 R >> >> "
                f"/Contents {page_content_id} 0 R >>"
            ).encode("latin-1")
            final_objects.append((page_obj_id, page_body))
            page_idx += 1

    final_objects.sort(key=lambda x: x[0])

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj_id, content in final_objects:
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        pdf.extend(content)
        pdf.extend(b"\nendobj\n")

    xref_pos = len(pdf)
    pdf.extend(f"xref\n0 {len(final_objects) + 1}\n".encode("latin-1"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(final_objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF"
        ).encode("latin-1")
    )
    output_path.write_bytes(pdf)


def main() -> None:
    folder = Path(__file__).resolve().parent
    files = [
        ("application_work_product.md", "application_work_product.pdf"),
        ("suvita_companion_note.md", "suvita_companion_note.pdf"),
    ]
    for source_name, output_name in files:
        source_path = folder / source_name
        output_path = folder / output_name
        text = source_path.read_text(encoding="utf-8")
        lines = wrap_text(text, width=92)
        if source_name == "application_work_product.md":
            lines.extend([""] * 4)
            lines.extend(["__ARCHITECTURE_PAGE__"])
        build_pdf(lines, output_path)
        print(f"PDF written to: {output_path}")


if __name__ == "__main__":
    main()
