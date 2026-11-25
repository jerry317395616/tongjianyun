from __future__ import annotations

import io
import json
import re
import zipfile
from datetime import datetime, timezone
from html import escape
from typing import Any


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CONTENT_WIDTH = 9360
MIN_CONTENT_CHARACTERS = 1200
MIN_SECTIONS = 10
INVALID_XML = re.compile(r"[^\x09\x0A\x0D\x20-\uD7FF\uE000-\uFFFD]")


def clean(value: Any) -> str:
	return INVALID_XML.sub("", str(value or "")).strip()


def _run(text: Any, *, bold: bool = False, color: str | None = None, size: int | None = None) -> str:
	properties = []
	if bold:
		properties.append("<w:b/><w:bCs/>")
	if color:
		properties.append(f'<w:color w:val="{color}"/>')
	if size:
		properties.append(f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>')
	parts = clean(text).split("\n")
	content = []
	for index, part in enumerate(parts):
		if index:
			content.append("<w:br/>")
		content.append(f'<w:t xml:space="preserve">{escape(part, quote=True)}</w:t>')
	return f"<w:r><w:rPr>{''.join(properties)}</w:rPr>{''.join(content)}</w:r>"


def _paragraph(
	text: Any = "",
	*,
	style: str = "Normal",
	bold: bool = False,
	color: str | None = None,
	size: int | None = None,
	alignment: str | None = None,
	keep_next: bool = False,
	num_id: int | None = None,
	indent: int | None = None,
) -> str:
	properties = [f'<w:pStyle w:val="{style}"/>'] if style else []
	if alignment:
		properties.append(f'<w:jc w:val="{alignment}"/>')
	if keep_next:
		properties.append("<w:keepNext/>")
	if num_id is not None:
		properties.append(
			f'<w:numPr><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
		)
	if indent is not None:
		properties.append(f'<w:ind w:left="{indent}"/>')
	return (
		f"<w:p><w:pPr>{''.join(properties)}</w:pPr>"
		f"{_run(text, bold=bold, color=color, size=size)}</w:p>"
	)


def _page_break() -> str:
	return '<w:p><w:r><w:br w:type="page"/></w:r></w:p>'


def _column_widths(headers: list[str], rows: list[list[str]]) -> list[int]:
	weights = []
	for index, header in enumerate(headers):
		values = [header, *(row[index] if index < len(row) else "" for row in rows)]
		weights.append(max(7, min(34, max(len(clean(value)) for value in values))))
	total = sum(weights)
	widths = [round(CONTENT_WIDTH * weight / total) for weight in weights]
	widths[-1] += CONTENT_WIDTH - sum(widths)
	return widths


def _table_block(table: dict[str, Any]) -> str:
	headers = [clean(value) for value in table.get("headers") or []]
	rows = [[clean(value) for value in row] for row in table.get("rows") or []]
	if not headers or not rows:
		return ""
	if any(len(row) != len(headers) for row in rows):
		raise ValueError(f"Table '{clean(table.get('title'))}' has inconsistent column counts")
	widths = _column_widths(headers, rows)
	grid = "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)

	def cell(value: str, width: int, *, header: bool = False) -> str:
		shade = '<w:shd w:val="clear" w:color="auto" w:fill="F2F4F7"/>' if header else ""
		text = _paragraph(value, style="TableText", bold=header, color="153A5B" if header else None)
		return (
			f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}'
			'<w:vAlign w:val="center"/><w:tcMar>'
			'<w:top w:w="80" w:type="dxa"/><w:left w:w="120" w:type="dxa"/>'
			'<w:bottom w:w="80" w:type="dxa"/><w:right w:w="120" w:type="dxa"/>'
			f"</w:tcMar></w:tcPr>{text}</w:tc>"
		)

	header_row = (
		'<w:tr><w:trPr><w:tblHeader/></w:trPr>'
		+ "".join(cell(value, widths[index], header=True) for index, value in enumerate(headers))
		+ "</w:tr>"
	)
	body_rows = "".join(
		"<w:tr>"
		+ "".join(cell(value, widths[index]) for index, value in enumerate(row))
		+ "</w:tr>"
		for row in rows
	)
	title = _paragraph(table.get("title"), style="Caption", keep_next=True) if table.get("title") else ""
	return title + (
		f'<w:tbl><w:tblPr><w:tblW w:w="{CONTENT_WIDTH}" w:type="dxa"/>'
		'<w:tblInd w:w="120" w:type="dxa"/><w:tblLayout w:type="fixed"/><w:tblBorders>'
		'<w:top w:val="single" w:sz="6" w:color="B8C7D4"/>'
		'<w:left w:val="single" w:sz="6" w:color="B8C7D4"/>'
		'<w:bottom w:val="single" w:sz="6" w:color="B8C7D4"/>'
		'<w:right w:val="single" w:sz="6" w:color="B8C7D4"/>'
		'<w:insideH w:val="single" w:sz="4" w:color="D8E1E8"/>'
		'<w:insideV w:val="single" w:sz="4" w:color="D8E1E8"/>'
		f"</w:tblBorders></w:tblPr><w:tblGrid>{grid}</w:tblGrid>{header_row}{body_rows}</w:tbl>"
		'<w:p><w:pPr><w:spacing w:after="120"/></w:pPr></w:p>'
	)


def validate_analysis(analysis: dict[str, Any]) -> None:
	if not isinstance(analysis, dict):
		raise ValueError("analysis must be an object")
	summary = analysis.get("executive_summary")
	if not isinstance(summary, list) or len([item for item in summary if clean(item)]) < 2:
		raise ValueError("A detailed analysis requires at least two executive summary paragraphs")
	sections = analysis.get("sections")
	if not isinstance(sections, list) or len(sections) < MIN_SECTIONS:
		raise ValueError(f"A detailed analysis requires at least {MIN_SECTIONS} sections")
	for index, section in enumerate(sections, start=1):
		if not isinstance(section, dict) or not clean(section.get("title")):
			raise ValueError(f"Analysis section {index} requires a title")
		if not any(section.get(key) for key in ("paragraphs", "bullets", "tables")):
			raise ValueError(f"Analysis section {index} requires content")
		for table in section.get("tables") or []:
			if not isinstance(table, dict) or not table.get("headers") or not table.get("rows"):
				raise ValueError("Each analysis table requires headers and rows")
	content = json.dumps(analysis, ensure_ascii=False)
	if len(re.sub(r"\s+", "", content)) < MIN_CONTENT_CHARACTERS:
		raise ValueError(
			f"Analysis content is too short; provide at least {MIN_CONTENT_CHARACTERS} non-whitespace characters"
		)


def _document_xml(
	analysis: dict[str, Any],
	*,
	lead_name: str,
	customer_name: str,
	prepared_for: str,
) -> str:
	date = datetime.now().astimezone().strftime("%Y-%m-%d")
	metadata = _table_block(
		{
			"headers": ["项目", "内容"],
			"rows": [
				["客户/机构", customer_name],
				["CRM 线索", lead_name],
				["跟进负责人", prepared_for],
				["分析日期", date],
				["文档状态", "需求分析初稿（待客户确认）"],
			],
		}
	)
	body = [
		_paragraph("内部业务资料", style="Caption", color="5B7285", alignment="right"),
		_paragraph("I-ONE AI", style="Subtitle", color="0B7285", bold=True, alignment="center"),
		_paragraph(clean(analysis.get("report_title")) or "客户需求分析报告", style="Title", alignment="center"),
		_paragraph(customer_name, style="Subtitle", alignment="center"),
		_paragraph("从线索事实到可执行跟进策略", style="Subtitle", color="5B7285", alignment="center"),
		_paragraph("", style="Normal"),
		metadata,
		_paragraph(
			"说明：本报告依据当前线索资料及公开来源形成。未获得客户确认的信息均应视为分析假设，并在后续沟通中逐项验证。",
			style="Caption",
		),
		_page_break(),
		_paragraph("管理摘要", style="Heading1", keep_next=True),
	]
	for item in analysis["executive_summary"]:
		if clean(item):
			body.append(_paragraph(item))
	body.append(_paragraph("分析目录", style="Heading1", keep_next=True))
	for index, section in enumerate(analysis["sections"], start=1):
		body.append(_paragraph(f"{index}. {section['title']}", indent=240))
	body.append(_page_break())
	for index, section in enumerate(analysis["sections"], start=1):
		body.append(_paragraph(f"{index}. {section['title']}", style="Heading1", keep_next=True))
		for item in section.get("paragraphs") or []:
			if clean(item):
				body.append(_paragraph(item))
		for item in section.get("bullets") or []:
			if clean(item):
				body.append(_paragraph(item, style="ListParagraph", num_id=1))
		for table in section.get("tables") or []:
			body.append(_table_block(table))
	if analysis.get("sources"):
		body.append(_paragraph("资料来源", style="Heading1", keep_next=True))
		for source in analysis["sources"]:
			if clean(source):
				body.append(_paragraph(source, style="ListParagraph", num_id=1))
	body.append(
		'<w:sectPr><w:headerReference w:type="default" r:id="rId4"/>'
		'<w:footerReference w:type="default" r:id="rId5"/>'
		'<w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:right="1440" '
		'w:bottom="1440" w:left="1440" w:header="708" w:footer="708" w:gutter="0"/>'
		'<w:cols w:space="720"/><w:docGrid w:linePitch="312"/></w:sectPr>'
	)
	return (
		'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
		f'<w:document xmlns:w="{WORD_NS}" xmlns:r="{REL_NS}"><w:body>{"".join(body)}</w:body></w:document>'
	)


def _styles_xml() -> str:
	return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{WORD_NS}">
  <w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="Microsoft YaHei" w:cs="Calibri"/><w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="zh-CN" w:eastAsia="zh-CN"/></w:rPr></w:rPrDefault><w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="264" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr></w:pPrDefault></w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/><w:pPr><w:widowControl/><w:spacing w:after="120" w:line="264" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="900" w:after="300"/><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="153A5B"/><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:spacing w:after="170"/><w:jc w:val="center"/></w:pPr><w:rPr><w:color w:val="5B7285"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="320" w:after="160"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="2E74B5"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/><w:pPr><w:ind w:left="720" w:hanging="360"/><w:spacing w:after="160" w:line="280" w:lineRule="auto"/></w:pPr></w:style>
  <w:style w:type="paragraph" w:styleId="Caption"><w:name w:val="Caption"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="100" w:after="80"/></w:pPr><w:rPr><w:b/><w:bCs/><w:color w:val="5B7285"/><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
  <w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="0" w:after="0" w:line="290" w:lineRule="auto"/><w:jc w:val="left"/></w:pPr><w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
</w:styles>'''


def create_lead_analysis_docx(
	analysis: dict[str, Any],
	*,
	lead_name: str,
	customer_name: str,
	prepared_for: str,
) -> bytes:
	"""Render a validated customer requirements analysis into a compact DOCX package."""
	validate_analysis(analysis)
	now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
	title = clean(analysis.get("report_title")) or "客户需求分析报告"
	parts = {
		"[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/><Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/><Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/><Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/><Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/><Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/><Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/></Types>''',
		"_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/></Relationships>''',
		"word/document.xml": _document_xml(
			analysis,
			lead_name=clean(lead_name),
			customer_name=clean(customer_name),
			prepared_for=clean(prepared_for),
		),
		"word/styles.xml": _styles_xml(),
		"word/numbering.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="{WORD_NS}"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="multilevel"/><w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/><w:pPr><w:tabs><w:tab w:val="num" w:pos="360"/></w:tabs><w:ind w:left="720" w:hanging="360"/><w:spacing w:after="160" w:line="280" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/></w:rPr></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>''',
		"word/settings.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings xmlns:w="{WORD_NS}"><w:zoom w:percent="100"/><w:updateFields w:val="true"/><w:defaultTabStop w:val="720"/><w:compat/></w:settings>''',
		"word/header1.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr xmlns:w="{WORD_NS}" xmlns:r="{REL_NS}">{_paragraph("I-ONE AI  |  " + title, style="Caption", color="5B7285")}</w:hdr>''',
		"word/footer1.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr xmlns:w="{WORD_NS}" xmlns:r="{REL_NS}"><w:p><w:pPr><w:jc w:val="center"/></w:pPr>{_run("内部业务资料  |  ", color="6F8394", size=17)}<w:r><w:rPr><w:color w:val="6F8394"/><w:sz w:val="17"/></w:rPr><w:fldChar w:fldCharType="begin"/><w:instrText xml:space="preserve"> PAGE </w:instrText><w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>''',
		"word/_rels/document.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/><Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/><Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/></Relationships>''',
		"docProps/core.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>{escape(title, quote=True)}</dc:title><dc:subject>{escape(clean(customer_name), quote=True)}</dc:subject><dc:creator>I-ONE AI</dc:creator><cp:lastModifiedBy>I-ONE AI</cp:lastModifiedBy><dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created><dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>''',
		"docProps/app.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes"><Application>I-ONE AI</Application><DocSecurity>0</DocSecurity><ScaleCrop>false</ScaleCrop><Company>I-ONE</Company><AppVersion>1.0</AppVersion></Properties>''',
	}
	buffer = io.BytesIO()
	with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
		for name, content in parts.items():
			archive.writestr(name, content.encode("utf-8"))
	with zipfile.ZipFile(io.BytesIO(buffer.getvalue())) as archive:
		if archive.testzip() is not None:
			raise ValueError("Generated lead analysis DOCX failed integrity validation")
	return buffer.getvalue()
