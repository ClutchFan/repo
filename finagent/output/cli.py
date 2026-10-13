"""Console rendering for pipeline results using rich."""
from finagent.narrative.verifier import render_claim_text


def render_console(result) -> str:
    """Render a Result to a human-readable string for the console.

    Output includes:
      - A table (company/alias rows, frame columns, N/A notes, derived markers)
      - Claims with verdict markers (✓/✗) and interpretation marker
      - Footer: 【核查】X passed · N downgraded
    """
    try:
        from rich.table import Table
        from rich.console import Console
        import io
    except ImportError:
        return _render_plain(result)

    # Build the table
    table = Table(title="Financial Data")
    table.add_column("Company")
    table.add_column("Metric")
    for col in result.table.columns:
        table.add_column(col)

    for row in result.table.rows:
        cells_display = []
        for cell in row.cells:
            if cell.value is None:
                cells_display.append(cell.note or "N/A")
            else:
                val_str = str(cell.value)
                if cell.note:
                    val_str = f"{val_str} [{cell.note}]"
                cells_display.append(val_str)
        table.add_row(row.company, row.alias, *cells_display)

    # Build claims section
    claim_lines = []
    verdicts_by_id = {v.claim_id: v for v in result.verdicts}
    for claim in result.claims:
        v = verdicts_by_id.get(claim.id)
        marker = "✓" if (v and v.ok) else "✗"
        text = render_claim_text(claim)
        claim_lines.append(f"  {marker} {text}")

    # Footer
    ok_count = sum(1 for v in result.verdicts if v.ok and _claim_retained(v.claim_id, result.claims))
    footer = f"【核查】{ok_count} passed · {result.downgraded} downgraded"

    # Capture rich output to string
    console = Console(file=io.StringIO(), width=120)
    console.print(table)
    console.print()
    console.print("Claims:")
    for line in claim_lines:
        console.print(line)
    console.print()
    console.print(footer)

    return console.file.getvalue()


def _claim_retained(claim_id, claims):
    """Check if a claim id is present in the retained claims list."""
    return any(c.id == claim_id for c in claims)


def _render_plain(result) -> str:
    """Fallback plain-text renderer if rich is not available."""
    lines = []
    lines.append("Financial Data")
    lines.append("-" * 60)

    # Header
    header = ["Company", "Metric"] + list(result.table.columns)
    lines.append("\t".join(header))

    for row in result.table.rows:
        cells = []
        for cell in row.cells:
            if cell.value is None:
                cells.append(cell.note or "N/A")
            else:
                val_str = str(cell.value)
                if cell.note:
                    val_str = f"{val_str} [{cell.note}]"
                cells.append(val_str)
        lines.append("\t".join([row.company, row.alias] + cells))

    lines.append("")
    lines.append("Claims:")
    verdicts_by_id = {v.claim_id: v for v in result.verdicts}
    for claim in result.claims:
        v = verdicts_by_id.get(claim.id)
        marker = "[OK]" if (v and v.ok) else "[FAIL]"
        text = render_claim_text(claim)
        lines.append(f"  {marker} {text}")

    ok_count = sum(1 for v in result.verdicts if v.ok and _claim_retained(v.claim_id, result.claims))
    lines.append("")
    lines.append(f"【核查】{ok_count} passed · {result.downgraded} downgraded")

    return "\n".join(lines)
