"""Markdown/HTML 렌더러.

PDF는 ReportRenderer 포트의 어댑터로 추가한다 (한글 폰트 임베딩이 필요해
별도 의존성과 함께 도입 - docs/adr 참고).
"""

from __future__ import annotations

import html

from pams.reporting.domain import (
    Block,
    KeyValueBlock,
    Paragraph,
    ReportDocument,
    TableBlock,
)


class MarkdownRenderer:
    def render(self, document: ReportDocument) -> str:
        lines: list[str] = [f"# {document.title}", "", f"기준일: {document.as_of.isoformat()}"]
        for section in document.sections:
            lines += ["", f"## {section.heading}", ""]
            for block in section.blocks:
                lines += self._render_block(block)
        return "\n".join(lines).rstrip() + "\n"

    def _render_block(self, block: Block) -> list[str]:
        if isinstance(block, Paragraph):
            return [block.text, ""]
        if isinstance(block, KeyValueBlock):
            return [f"- **{label}**: {value}" for label, value in block.items] + [""]
        return self._render_table(block)

    @staticmethod
    def _render_table(table: TableBlock) -> list[str]:
        def row(cells: tuple[str, ...]) -> str:
            escaped = (cell.replace("|", "\\|") for cell in cells)
            return "| " + " | ".join(escaped) + " |"

        lines = [row(table.headers), "|" + " --- |" * len(table.headers)]
        lines += [row(cells) for cells in table.rows]
        return [*lines, ""]


_HTML_STYLE = """
body { font-family: sans-serif; max-width: 60rem; margin: 2rem auto; padding: 0 1rem; }
table { border-collapse: collapse; margin: 1rem 0; }
th, td { border: 1px solid #999; padding: 0.4rem 0.8rem; text-align: left; }
dt { font-weight: bold; }
dd { margin: 0 0 0.5rem 0; }
""".strip()


class HtmlRenderer:
    def render(self, document: ReportDocument) -> str:
        body: list[str] = [f"<h1>{_esc(document.title)}</h1>"]
        body.append(f"<p>기준일: {document.as_of.isoformat()}</p>")
        for section in document.sections:
            body.append(f"<h2>{_esc(section.heading)}</h2>")
            for block in section.blocks:
                body.append(self._render_block(block))
        joined = "\n".join(body)
        return (
            "<!doctype html>\n"
            '<html lang="ko">\n<head>\n<meta charset="utf-8">\n'
            f"<title>{_esc(document.title)}</title>\n"
            f"<style>\n{_HTML_STYLE}\n</style>\n</head>\n<body>\n"
            f"{joined}\n</body>\n</html>\n"
        )

    def _render_block(self, block: Block) -> str:
        if isinstance(block, Paragraph):
            return f"<p>{_esc(block.text)}</p>"
        if isinstance(block, KeyValueBlock):
            entries = "\n".join(
                f"<dt>{_esc(label)}</dt><dd>{_esc(value)}</dd>" for label, value in block.items
            )
            return f"<dl>\n{entries}\n</dl>"
        return self._render_table(block)

    @staticmethod
    def _render_table(table: TableBlock) -> str:
        head = "".join(f"<th>{_esc(cell)}</th>" for cell in table.headers)
        rows = "\n".join(
            "<tr>" + "".join(f"<td>{_esc(cell)}</td>" for cell in cells) + "</tr>"
            for cells in table.rows
        )
        return f"<table>\n<thead><tr>{head}</tr></thead>\n<tbody>\n{rows}\n</tbody>\n</table>"


def _esc(text: str) -> str:
    return html.escape(text)
