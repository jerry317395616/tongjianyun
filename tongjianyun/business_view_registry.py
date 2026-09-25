"""Audited business canvas catalog. Never infer fields or expose arbitrary DocTypes.

This is a read surface, not a replacement for each domain's write/approval services.
Personal identifiers, credentials, face templates, raw video and payroll are excluded.
"""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Entity:
    title: str
    domain: str
    doctype: str
    columns: tuple
    date_field: str = ''
    end_field: str = ''
    period: str = 'all'
    note: str = ''
    children: tuple = ()


def entity(title, domain, doctype, columns, **kwargs):
    return Entity(title, domain, doctype, tuple(tuple(c.split(':', 1)) for c in columns.split('|')), **kwargs)


DOMAINS = ('学生与班级', '出勤与教学', '膳食与营养', '采购与收货', '库存与物料', '财务单据', '教职工与视频考勤', '基础资料')
ITEMS = ('items', '物料明细', 'item_code:物料编号|item_name:物料|qty:数量|uom:单位|rate:单价|amount:金额|warehouse:仓库')
REGISTRY = {
    'student_records': entity('学生档案', DOMAINS[0], 'Student', 'student_name:姓名|name:学生编号|enabled:启用|gender:性别|joining_date:入园日期', note='启用学籍不等于今日出勤；人数总览请使用“在园学生”。'),
    'classes': entity('班级档案', DOMAINS[0], 'Student Group', 'student_group_name:班级|name:编号|academic_year:学年|program:学段|disabled:停用|max_strength:容量', children=(('students', '班级成员', 'student:学生编号|student_name:姓名|active:有效'),)),
    'guardians': entity('监护人档案', DOMAINS[0], 'Guardian', 'guardian_name:姓名|name:监护人编号', note='此视图不展示家庭电话、住址或职业资料。'),
    'enrollments': entity('学生注册', DOMAINS[0], 'Program Enrollment', 'name:注册编号|student_name:学生|student:学生编号|program:学段|academic_year:学年|enrollment_date:注册日期', date_field='enrollment_date'),
    'student_attendance': entity('学生考勤记录', DOMAINS[1], 'Student Attendance', 'name:记录|student_name:学生|student_group:班级|date:日期|status:考勤状态', date_field='date', period='day', note='仅展示已登记记录；没有记录不表示缺勤，也不表示出勤。'),
    'student_leave': entity('学生请假', DOMAINS[1], 'Student Leave Application', 'name:请假单|student_name:学生|student_group:班级|from_date:开始|to_date:结束|total_leave_days:天数', date_field='from_date', end_field='to_date', period='week'),
    'student_logs': entity('学生日常记录', DOMAINS[1], 'Student Log', 'name:记录|student_name:学生|date:日期|type:类型|academic_year:学年', date_field='date', period='week', note='这里只展示记录索引，不展开可能包含隐私的自由文本。'),
    'schedules': entity('班级课程安排', DOMAINS[1], 'Course Schedule', 'name:课程安排|student_group:班级|course:课程|instructor_name:教师|schedule_date:日期|from_time:开始|to_time:结束|room:地点', date_field='schedule_date', period='week'),
    'health': entity('学生健康登记', DOMAINS[1], 'Tongjianyun Student Health', 'name:登记|student_name:学生|student_group:班级|month:月份|history_state:病史登记状态|allergy_state:过敏登记状态|review_status:核对状态', date_field='month', period='month', note='需专属健康权限；仅显示登记状态，不展示病史、电话。无记录或未登记绝不等于健康正常。'),
    'recipes': entity('周食谱档案', DOMAINS[2], 'Tongjianyun Recipe', 'title:食谱|name:编号|week_start:开始|week_end:结束|workflow_status:状态|imported_at:导入时间', date_field='week_start', end_field='week_end', period='week', note='草稿不代表已发布，不能作为采购或供餐执行依据。'),
    'recipe_dishes': entity('食谱菜品', DOMAINS[2], 'Tongjianyun Recipe Dish', 'dish_name:菜品|name:编号|recipe:所属食谱|meal_date:日期|meal_label:餐次|amount_per_child_text:每生用量', date_field='meal_date', period='week'),
    'recipe_ingredients': entity('食谱食材用量', DOMAINS[2], 'Tongjianyun Recipe Ingredient', 'ingredient_name:食材|name:编号|recipe:食谱|recipe_dish:菜品编号|amount:用量|unit:单位|grams_per_child:每生克数', note='原始食谱用量；不等于采购总量，不同单位不合计。'),
    'class_meals': entity('班级就餐确认', DOMAINS[2], 'Tongjianyun Class Meal Confirmation', 'name:确认单|meal_date:日期|student_group:班级|status:状态|confirmed_at:确认时间', date_field='meal_date', period='day', note='无记录或未确认不记为零；真实用餐人数请使用“用餐人数”视图。'),
    'daily_meals': entity('全园每日就餐汇总', DOMAINS[2], 'Tongjianyun Daily Meal Confirmation', 'name:汇总单|meal_date:日期|status:状态|total_enrolled_count:在册人数|total_absent_count:缺勤|total_leave_count:请假|total_lunch_count:午餐登记数', date_field='meal_date', period='day', note='保存的汇总记录不是实时全园人数；请结合状态及班级确认核对。'),
    'meal_adjustments': entity('就餐调整记录', DOMAINS[2], 'Tongjianyun Daily Meal Adjustment', 'name:调整单|meal_date:日期|student_group:班级|adjustment_type:类型|breakfast_delta:早餐变化|lunch_delta:午餐变化|dinner_delta:晚餐变化', date_field='meal_date', period='week'),
    'monthly_meals': entity('月度就餐统计', DOMAINS[2], 'Tongjianyun Meal Attendance', 'name:统计单|month:月份|status:状态|breakfast_total:早餐人次|lunch_total:午餐人次|dinner_total:晚餐人次|total_meal_times:用餐人次|total_person_days:人天', date_field='month', period='month', note='人次、人天不是去重学生人数；以单据状态为准。'),
    'nutrition_rules': entity('营养计算规则', DOMAINS[2], 'Tongjianyun Nutrition Rule Set', 'title:规则|name:编号|version:版本|status:状态|effective_from:生效日期|source:来源', note='只读查看已配置规则，不自动修改或发布营养标准。'),
    'nutrition_revisions': entity('营养规则变更记录', DOMAINS[2], 'Tongjianyun Nutrition Rule Revision', 'name:记录|rule_set:规则|action:操作|acted_at:时间', date_field='acted_at', period='month'),
    'material_requests': entity('采购需求单', DOMAINS[3], 'Material Request', 'name:需求单|title:标题|material_request_type:类型|transaction_date:日期|schedule_date:需求日期|status:状态|company:组织', date_field='transaction_date', period='week', children=(ITEMS,)),
    'purchase_orders': entity('采购订单', DOMAINS[3], 'Purchase Order', 'name:订单|title:标题|supplier_name:供应商|transaction_date:日期|status:状态|grand_total:金额|currency:币种|per_received:已收货百分比', date_field='transaction_date', period='week', children=(ITEMS,), note='按订单交易日期筛选，不等同于标题中的食谱日期；金额不跨币种合计。'),
    'purchase_receipts': entity('到货与验收单', DOMAINS[3], 'Purchase Receipt', 'name:收货单|supplier_name:供应商|posting_date:日期|status:状态|is_return:退货|grand_total:金额|currency:币种', date_field='posting_date', period='week', children=(ITEMS,), note='采购收货单据状态不等于食品安全验收结论。'),
    'suppliers': entity('供应商档案', DOMAINS[3], 'Supplier', 'supplier_name:供应商|name:编号|supplier_group:分组|supplier_type:类型|disabled:停用|default_currency:结算币种'),
    'supplier_groups': entity('供应商分类', DOMAINS[3], 'Supplier Group', 'name:分类|parent_supplier_group:上级分类|is_group:目录'),
    'items': entity('食材与物料档案', DOMAINS[4], 'Item', 'item_name:物料|name:编号|item_group:分类|stock_uom:库存单位|is_stock_item:库存物料|disabled:停用'),
    'item_groups': entity('物料分类', DOMAINS[4], 'Item Group', 'name:分类|parent_item_group:上级分类|is_group:目录'),
    'warehouses': entity('仓库档案', DOMAINS[4], 'Warehouse', 'warehouse_name:仓库|name:编号|company:组织|parent_warehouse:上级仓库|is_group:目录|disabled:停用'),
    'stock_entries': entity('领料与库存作业单', DOMAINS[4], 'Stock Entry', 'name:库存单|posting_date:日期|stock_entry_type:作业类型|purpose:用途|from_warehouse:来源仓|to_warehouse:目标仓|company:组织', date_field='posting_date', period='week', children=(ITEMS,)),
    'stock_ledger': entity('库存流水', DOMAINS[4], 'Stock Ledger Entry', 'name:流水|item_code:物料|warehouse:仓库|posting_date:日期|actual_qty:数量变动|qty_after_transaction:交易后数量|stock_uom:单位|voucher_no:来源单据', date_field='posting_date', period='week', note='仅已入账流水；不同物料、仓库和单位不直接相加。'),
    'batches': entity('食材批次与有效期', DOMAINS[4], 'Batch', 'batch_id:批次|name:编号|item_name:物料|item:物料编号|manufacturing_date:生产日期|expiry_date:到期日期|disabled:停用', date_field='expiry_date', note='日期筛选针对到期日；过期与否不等于实际库存或食品安全鉴定。'),
    'item_prices': entity('食材价格', DOMAINS[4], 'Item Price', 'name:价格记录|item_name:物料|price_list:价目表|price_list_rate:单价|currency:币种|uom:单位|valid_from:起效|valid_upto:失效'),
    'purchase_invoices': entity('采购发票与应付', DOMAINS[5], 'Purchase Invoice', 'name:发票|supplier_name:供应商|posting_date:记账日|due_date:到期日|status:状态|grand_total:金额|outstanding_amount:未付金额|currency:币种', date_field='posting_date', period='month', children=(ITEMS,), note='单据金额按各自币种显示，未付款不等于逾期；不替代会计核对。'),
    'payments': entity('收付款记录', DOMAINS[5], 'Payment Entry', 'name:付款单|posting_date:日期|payment_type:类型|party_name:往来方|paid_amount:付出金额|paid_from_account_currency:付出币种|received_amount:收到金额|paid_to_account_currency:收到币种', date_field='posting_date', period='month', note='收付两侧可能使用不同币种，不能直接相加或互相抵销。'),
    'employees': entity('教职工档案', DOMAINS[6], 'Employee', 'employee_name:姓名|name:员工编号|status:状态|department:部门|designation:岗位|date_of_joining:入职日期', note='不展示身份证、薪酬、银行或个人健康字段。'),
    'instructors': entity('任课教师', DOMAINS[6], 'Instructor', 'instructor_name:教师|name:编号|employee:员工编号|status:状态|department:部门'),
    'staff_attendance': entity('教职工考勤', DOMAINS[6], 'Attendance', 'name:考勤单|employee_name:员工|attendance_date:日期|status:状态|working_hours:工时|late_entry:迟到|early_exit:早退', date_field='attendance_date', period='day', note='只显示已登记考勤，不由打卡次数推断出勤。'),
    'staff_checkins': entity('教职工打卡', DOMAINS[6], 'Employee Checkin', 'name:打卡记录|employee_name:员工|time:时间|log_type:进出类型|attendance:关联考勤单', date_field='time', period='day', note='打卡时间遵循原字段权限；打卡不等于已经生成考勤。'),
    'staff_leave': entity('教职工请假', DOMAINS[6], 'Leave Application', 'name:请假单|employee_name:员工|leave_type:类型|from_date:开始|to_date:结束|total_leave_days:天数|status:状态', date_field='from_date', end_field='to_date', period='week'),
    'video_devices': entity('视频考勤设备', DOMAINS[6], 'Tongjianyun Video Device', 'title:设备|name:编号|enabled:启用|direction:方向|last_seen:最近心跳|health:上报状态|pending:待上传数', note='最近心跳与设备上报状态不等于实时在线保证；不展示上传密钥或视频地址。'),
    'video_batches': entity('视频考勤处理批次', DOMAINS[6], 'Tongjianyun Video Batch', 'name:批次|camera:设备|started_at:开始|ended_at:结束|status:处理状态|attempts:尝试次数|video_deleted:视频已清理', date_field='started_at', period='day'),
    'video_events': entity('视频考勤待核对记录', DOMAINS[6], 'Tongjianyun Video Event', 'name:事件|employee:员工编号|occurred_at:时间|log_type:方向|status:核对状态|checkin:关联打卡', date_field='occurred_at', period='day', note='识别事件不等于确认考勤；本视图不会批准、驳回或写入打卡。'),
    'face_profiles': entity('教师人脸授权状态', DOMAINS[6], 'Tongjianyun Teacher Face', 'name:记录|employee:员工编号|consent:已授权|active:启用|model_version:模型版本', note='仅授权状态，绝不读取或显示人脸模板、照片或识别特征。'),
    'academic_years': entity('学年', DOMAINS[7], 'Academic Year', 'name:学年|year_start_date:开始|year_end_date:结束'),
    'academic_terms': entity('学期', DOMAINS[7], 'Academic Term', 'name:学期|academic_year:学年|term_start_date:开始|term_end_date:结束'),
    'programs': entity('学段与培养项目', DOMAINS[7], 'Program', 'program_name:名称|name:编号|program_abbreviation:简称'),
    'companies': entity('园所与核算组织', DOMAINS[7], 'Company', 'company_name:组织|name:编号|abbr:简称|default_currency:本位币|parent_company:上级组织'),
    'departments': entity('部门', DOMAINS[7], 'Department', 'department_name:部门|name:编号|company:组织|parent_department:上级部门|disabled:停用'),
    'designations': entity('岗位', DOMAINS[7], 'Designation', 'designation_name:岗位|name:编号'),
    'uoms': entity('计量单位', DOMAINS[7], 'UOM', 'uom_name:单位|name:编号|must_be_whole_number:整数计量|enabled:启用'),
    'price_lists': entity('价目表', DOMAINS[7], 'Price List', 'name:价目表|currency:币种|buying:采购|selling:销售|enabled:启用'),
    'cost_centers': entity('成本中心', DOMAINS[7], 'Cost Center', 'cost_center_name:成本中心|name:编号|company:组织|parent_cost_center:上级|is_group:目录|disabled:停用'),
    'fiscal_years': entity('会计年度', DOMAINS[7], 'Fiscal Year', 'name:会计年度|year_start_date:开始|year_end_date:结束|disabled:停用'),
    'payment_modes': entity('支付方式', DOMAINS[7], 'Mode of Payment', 'mode_of_payment:方式|name:编号|type:类型|enabled:启用'),
}

# Only these explicitly audited child fields are displayed, never an entire document dump.
for key, children in {
    'class_meals': (('students', '学生各餐确认', 'student_name:姓名|student:学生编号|breakfast:早餐实际|morning_snack:早点实际|lunch:午餐实际|afternoon_snack:午点实际|dinner:晚餐实际|lunch_expected:午餐预计'),),
    'daily_meals': (('details', '班级汇总明细', 'class_name:班级|student_group:班级编号|enrolled_count:在册|absent_count:缺勤|leave_count:请假|breakfast_count:早餐|morning_snack_count:早点|lunch_count:午餐|afternoon_snack_count:午点|dinner_count:晚餐'),),
    'monthly_meals': (('details', '班级月度明细', 'class_name:班级|class_id:班级编号|breakfast_count:早餐人次|lunch_count:午餐人次|dinner_count:晚餐人次'),),
    'nutrition_rules': (('rules', '营养规则参数', 'nutrient:指标|unit:单位|edible_ratio:可食部系数|retention_rate:保留率|lower_percent:下限百分比|upper_percent:上限百分比|enabled:启用'),),
    'stock_entries': (('items', '库存作业明细', 'item_code:物料编号|item_name:物料|qty:数量|uom:单位|s_warehouse:来源仓|t_warehouse:目标仓'),),
}.items():
    REGISTRY[key] = replace(REGISTRY[key], children=children)

# Model context uses this fixed list, not database metadata or arbitrary code.
def catalog_instruction():
    return '；'.join(f'{key}={entry.title}' for key, entry in REGISTRY.items())
