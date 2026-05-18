from pathlib import Path


def esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_architecture_pdf(output_path: Path) -> None:
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

    stream = "\n".join(commands).encode("latin-1")

    objects = [
        (1, b"<< /Type /Catalog /Pages 2 0 R >>"),
        (2, b"<< /Type /Pages /Kids [5 0 R] /Count 1 >>"),
        (3, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"),
        (4, f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1") + stream + b"\nendstream"),
        (5, b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>"),
    ]

    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj_id, content in objects:
        offsets.append(len(pdf))
        pdf.extend(f"{obj_id} 0 obj\n".encode("latin-1"))
        pdf.extend(content)
        pdf.extend(b"\nendobj\n")
    xref = len(pdf)
    pdf.extend(b"xref\n0 6\n")
    pdf.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        pdf.extend(f"{off:010d} 00000 n \n".encode("latin-1"))
    pdf.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode("latin-1"))
    output_path.write_bytes(pdf)


def main() -> None:
    folder = Path(__file__).resolve().parent
    output_path = folder / "suvita_architecture_flow.pdf"
    build_architecture_pdf(output_path)
    print(f"PDF written to: {output_path}")


if __name__ == "__main__":
    main()
