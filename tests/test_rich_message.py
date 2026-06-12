"""Юнит-тесты сборки Rich Message HTML."""

from __future__ import annotations

from satellite.telegram_bot.rich_message import (
    details_block,
    escape_rich,
    input_rich_message,
    join_blocks,
    rich_blocks_for_streaming,
    section_heading,
    table,
    truncate_rich_html,
)


def test_escape_rich_escapes_angle_brackets() -> None:
    assert escape_rich("a <b> & c") == "a &lt;b&gt; &amp; c"


def test_input_rich_message_skip_entity_detection() -> None:
    payload = input_rich_message("<p>hi</p>")
    assert payload["html"] == "<p>hi</p>"
    assert payload["skip_entity_detection"] is True


def test_details_block_open_by_default() -> None:
    html = details_block("<b>Summary</b>", "<p>body</p>")
    assert html.startswith("<details open>")
    assert "<summary>▼ <b>Summary</b></summary>" in html


def test_details_block_closed() -> None:
    html = details_block("S", "B", open=False)
    assert html.startswith("<details>")
    assert " open" not in html.split(">")[0]
    assert "<summary>▶ S</summary>" in html


def test_table_renders_headers_and_rows() -> None:
    html = table(["A", "B"], [["1", "2"]])
    assert "<th>A</th>" in html
    assert "<td>2</td>" in html


def test_section_heading_level() -> None:
    assert section_heading("T", level=2) == "<h2>T</h2>"


def test_join_blocks_skips_empty() -> None:
    assert join_blocks(["<p>a</p>", "", "<p>b</p>"]) == "<p>a</p><p>b</p>"


def test_truncate_rich_html_adds_notice() -> None:
    long_text = "x" * 100
    result = truncate_rich_html(long_text, max_len=50)
    assert len(result) <= 50 + 120
    assert "укорочено" in result


def test_truncate_rich_html_does_not_split_open_tag() -> None:
    html = "<p>" + ("a" * 200) + "</p>"
    result = truncate_rich_html(html, max_len=80)
    assert result.endswith("</i></p>") or "</p>" in result
    assert "<p>aaa" in result
    assert result.count("<p>") == result.count("</p>")


def test_rich_blocks_for_streaming_splits_on_block_end() -> None:
    html = "<h2>Title</h2><p>para</p><hr><details open><summary>S</summary><p>x</p></details>"
    blocks = rich_blocks_for_streaming(html)
    assert blocks[0] == "<h2>Title</h2>"
    assert blocks[1] == "<p>para</p>"
    assert blocks[2] == "<hr>"
    assert blocks[0] + blocks[1] + blocks[2] in html
    assert any("details" in block for block in blocks)


def test_rich_blocks_for_streaming_keeps_nested_content_inside_details() -> None:
    """Вложенные ``</ul>``/``</p>`` не разрывают сворачиваемый блок пополам."""
    html = (
        "<h2>T</h2>"
        "<details open><summary>S</summary><ul><li>a</li><li>b</li></ul></details>"
        "<table><tr><th>A</th></tr><tr><td>1</td></tr></table>"
        "<p>tail</p>"
    )
    blocks = rich_blocks_for_streaming(html)
    assert blocks[0] == "<h2>T</h2>"
    assert blocks[1].startswith("<details open>")
    assert blocks[1].endswith("</details>")
    assert blocks[2].startswith("<table>")
    assert blocks[2].endswith("</table>")
    assert blocks[3] == "<p>tail</p>"
    assert "".join(blocks) == html
