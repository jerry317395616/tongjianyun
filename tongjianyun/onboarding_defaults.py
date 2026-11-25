# ruff: noqa: RUF001

import json


def _json(value):
	return json.dumps(value, ensure_ascii=False)


DEFAULT_STRENGTHS = [
	["人脉资源", 68],
	["专业技能", 72],
	["资金实力", 60],
	["沟通能力", 74],
	["执行能力", 80],
	["内容能力", 62],
]


REPORT_PRESETS = {
	"network": {
		"report_type": "人际资源型",
		"report_description": "你擅长沟通和资源整合，适合将客户拓展和关系维护作为核心优势。",
		"strengths": [["人脉资源", 90], ["专业技能", 60], ["资金实力", 50], ["沟通能力", 85], ["执行能力", 70], ["内容能力", 40]],
		"team": ["销售顾问", "财务助理", "行政助理"],
		"automation": ["自动记账", "自动催款", "资料归档"],
		"manual": ["客户拓展", "业务谈判"],
	},
	"skill": {
		"report_type": "技术能力型",
		"report_description": "你有扎实的专业能力，适合以专业交付为核心，让 AI 承担运营工作。",
		"strengths": [["人脉资源", 50], ["专业技能", 92], ["资金实力", 60], ["沟通能力", 65], ["执行能力", 78], ["内容能力", 55]],
		"team": ["财务助理", "运营助理", "行政助理"],
		"automation": ["商机跟进", "资料归档", "经营记账"],
		"manual": ["技术方案", "专业交付"],
	},
	"content": {
		"report_type": "内容创作型",
		"report_description": "你适合以内容和品牌驱动增长，AI 团队负责线索整理和经营协同。",
		"strengths": [["人脉资源", 45], ["专业技能", 75], ["资金实力", 45], ["沟通能力", 65], ["执行能力", 68], ["内容能力", 95]],
		"team": ["运营助理", "销售顾问", "财务助理"],
		"automation": ["内容分发", "客户跟进", "自动记账"],
		"manual": ["内容创作", "品牌建设"],
	},
}


def _option(step_code, option_code, label, icon, sequence, description="", preset=None):
	row = {
		"step_code": step_code,
		"option_code": option_code,
		"label": label,
		"icon": icon,
		"description": description,
		"sequence": sequence,
	}
	if preset:
		row.update(
			{
				"report_type": preset["report_type"],
				"report_description": preset["report_description"],
				"strengths_json": _json(preset["strengths"]),
				"team_json": _json(preset["team"]),
				"automation_json": _json(preset["automation"]),
				"manual_json": _json(preset["manual"]),
			}
		)
	return row


def get_default_onboarding_flow_data():
	industries = [
		("ad", "广告传媒", "📢"),
		("ecom", "电商零售", "🛒"),
		("design", "设计工作室", "🎨"),
		("photo", "摄影摄像", "📸"),
		("consult", "咨询服务", "💼"),
		("edu", "教育培训", "📚"),
		("food", "餐饮美食", "🍜"),
		("beauty", "美容美发", "💇"),
		("logistics", "物流运输", "🚚"),
		("it", "IT 外包", "💻"),
		("media", "自媒体/博主", "✍️"),
	]
	advantages = [
		("network", "人脉广、资源多", "🤝"),
		("skill", "有技术/专业技能", "🛠️"),
		("capital", "有启动资金", "💰"),
		("communication", "擅长沟通、客户多", "💬"),
		("content", "会做内容/设计", "🎨"),
		("execution", "能吃苦、执行力强", "💪"),
		("channel", "有独特资源/渠道", "🧩"),
		("random", "随机匹配", "🎯"),
	]
	pain_points = [
		("accounting", "不想处理记账/报税", "📊"),
		("collection", "不想自己催款", "💵"),
		("customer", "不想处理客户沟通", "💬"),
		("delivery", "不想跑腿取送", "🚚"),
		("repetition", "不想做重复性工作", "🔁"),
		("overtime", "不想熬夜赶工", "🌙"),
		("all", "以上都想省心", "✨"),
	]
	times = [
		("full_time", "全职，大部分时间都在", "🕘"),
		("part_time", "兼职，每天 2-3 小时", "⏱️"),
		("fragmented", "碎片时间，偶尔看看", "📱"),
		("delegated", "想当甩手掌柜，交给 AI", "🤖"),
	]
	options = []
	for index, (code, label, icon) in enumerate(industries, 1):
		options.append(_option("industry", code, label, icon, index, "生成对应行业的经营方案"))
	for index, (code, label, icon) in enumerate(advantages, 1):
		options.append(_option("advantage", code, label, icon, index, preset=REPORT_PRESETS.get(code)))
	for index, (code, label, icon) in enumerate(pain_points, 1):
		options.append(_option("pain_point", code, label, icon, index))
	for index, (code, label, icon) in enumerate(times, 1):
		options.append(_option("time_available", code, label, icon, index))

	return {
		"doctype": "I-ONE Onboarding Flow",
		"flow_code": "mobile-default",
		"flow_name": "手机端默认引导",
		"status": "已发布",
		"version": 1,
		"is_default": 1,
		"welcome_badge": "I-ONE AI 智能经营系统",
		"welcome_title": "建立你的一人公司工作台",
		"welcome_description": "用几项简单选择生成业务分工、AI 团队和自动化建议。",
		"start_button_label": "开始建立档案",
		"completion_button_label": "进入工作台",
		"steps": [
			{"step_code": "welcome", "step_type": "欢迎页", "title": "欢迎", "sequence": 1},
			{"step_code": "industry", "step_type": "单选题", "title": "选择你的行业", "description": "系统会据此调整业务模块和建议。", "required": 1, "sequence": 2},
			{"step_code": "advantage", "step_type": "多选题", "title": "你的核心优势是什么？", "description": "可以多选，至少选择一项。", "required": 1, "multiple_select": 1, "sequence": 3},
			{"step_code": "pain_point", "step_type": "多选题", "title": "最想让 AI 帮你处理什么？", "description": "可以选择多个经营痛点。", "required": 1, "multiple_select": 1, "sequence": 4},
			{"step_code": "time_available", "step_type": "单选题", "title": "每天能投入多少时间？", "description": "这会影响系统建议的自动化程度。", "required": 1, "sequence": 5},
			{"step_code": "profile", "step_type": "资料页", "title": "补充基础信息", "description": "这些信息用于个性化工作台，也可以稍后修改。", "sequence": 6},
			{"step_code": "report", "step_type": "报告页", "title": "你的经营方案已生成", "description": "以下内容可以在工作台中继续调整。", "sequence": 7},
		],
		"options": options,
		"default_report_type": "综合经营型",
		"default_report_description": "你的能力结构较为均衡，适合用 AI 团队承接重复工作，将时间集中在决策和客户上。",
		"default_strengths_json": _json(DEFAULT_STRENGTHS),
		"default_team_json": _json(["销售顾问", "财务助理", "运营助理"]),
		"default_automation_json": _json(["自动记账", "自动催款", "任务提醒"]),
		"default_manual_json": _json(["业务决策", "关键客户维护"]),
	}
