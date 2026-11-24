(() => {
	if (frappe.tjyOperationsLoaded) return;
	frappe.tjyOperationsLoaded = true;
	const prefix = "tongjianyun.canteen_ops.meal_operations.";
	const safety = "Tongjianyun Meal Safety Check", opinion = "Tongjianyun Meal Family Opinion";
	const feedback = "Tongjianyun Meal Class Feedback", handover = "Tongjianyun Meal Diet Handover";
	const publication = "Tongjianyun Meal Publication", arrangement = "Tongjianyun Meal Diet Arrangement";
	const delivery = "Tongjianyun Meal Delivery Handover";
	const read = async (method, args) => (await frappe.call({method:prefix+method, args, type:"GET"})).message;
	const open = (type, name) => frappe.set_route("Form", type, name);
	const scope = doc => ({company:doc.company,canteen:doc.canteen,student_group:doc.student_group,service_date:doc.service_date});
	for (const type of [safety,opinion,feedback,handover,publication,arrangement,delivery]) {
		frappe.ui.form.on(type,{setup(frm) {
			frm.set_query("canteen",()=>({filters:{company:frm.doc.company,disabled:0}}));
			if(frm.fields_dict.student_group) frm.set_query("student_group",()=>({filters:{company:frm.doc.company,disabled:0}}));
			if (!frappe.user_roles.includes("System Manager") && ["膳食园方负责人","膳食保健员","膳食安全员","膳食班级教师"].some(r=>frappe.user_roles.includes(r))) {
				const query=()=>({query:prefix+"scope_links",filters:{company:frm.doc.company,student_group:frm.doc.student_group}});
				frm.set_query("company",query);
				if(frm.fields_dict.student_group) frm.set_query("student_group",query);
				if(type===arrangement) frm.set_query("student",query);
			}
			if(frm.fields_dict.meal_week) frm.set_query("meal_week",()=>({filters:{company:frm.doc.company,docstatus:1}}));
			if(frm.fields_dict.publication) frm.set_query("publication",()=>({filters:{canteen:frm.doc.canteen,docstatus:1}}));
		}});
	}
	function checklist(frm) {
		if(!frm.is_new() || !frm.doc.period) return;
		const lists = {"日管控":["人员健康与卫生","进货验收与储存温度","生熟分开与加工温控","清洗消毒与分餐","留样、陪餐与添加剂"],
			"周排查":["本周日检查与遗漏","风险趋势与隐患处置","整改复核及下周措施"],"月调度":["听取食品安全工作汇报","本月检查及整改情况","下月重点与责任分工"]};
		if((frm.doc.checks||[]).some(row=>row.result||row.observation)) return;
		frm.clear_table("checks");
		for(const control of lists[frm.doc.period]) frm.add_child("checks",{control});
		frm.refresh_field("checks");
	}
	function review(frm) {
		frm.remove_custom_button("查看本期检查");
		if(frm.doc.period==="日管控") return;
		frm.add_custom_button("查看本期检查",async()=>{
			const rows=await read("review_period",{canteen:frm.doc.canteen,period:frm.doc.period,service_date:frm.doc.service_date});
			const d=new frappe.ui.Dialog({title:"本期检查依据",fields:[{fieldname:"records",fieldtype:"HTML"}]});
			const el=d.fields_dict.records.$wrapper;
			for(const r of rows){
				const line=$("<p>").appendTo(el);
				$("<a>",{href:frappe.utils.get_form_link(safety,r.name)}).text(r.service_date+" · "+r.signed_by).appendTo(line);
				$("<span>").text("　"+(r.summary||(r.finding?"有待追踪整改":"已完成检查"))).appendTo(line);
			}
			if(!rows.length) el.text("本期暂无已确认的下级检查记录。");
			d.show();
		});
	}
	frappe.ui.form.on(safety,{refresh(frm){checklist(frm);review(frm);},period(frm){checklist(frm);review(frm);}});
	frappe.ui.form.on(feedback,{refresh(frm) {
		if(frm.doc.docstatus) return;
		frm.add_custom_button("从本餐选菜",async()=>{
			const rows=await read("class_dishes",{...scope(frm.doc),meal_type:frm.doc.meal_type,
				meal_week:frm.doc.meal_week,publication:frm.doc.publication});
			frappe.prompt([{fieldname:"dish",label:"实际菜品",fieldtype:"Select",options:rows,reqd:1}],v=>{
				if(!(frm.doc.observations||[]).some(r=>r.dish===v.dish)) frm.add_child("observations",{dish:v.dish,acceptance:"未观察"});
				frm.refresh_field("observations");frm.dirty();
			},"选择观察菜品");
		});
	}});
	frappe.ui.form.on(handover,{refresh(frm) {
		if(frm.doc.docstatus) return;
		frm.add_custom_button("选择待交接特殊餐",async()=>{
			const rows=await read("diet_list",scope(frm.doc));
			if(!rows.length) return frappe.msgprint("本班当日没有生效的特殊膳食安排。");
			frappe.prompt([{fieldname:"record",label:"幼儿与替代安排",fieldtype:"Select",reqd:1,
				options:rows.map(r=>({label:r.student+" · "+r.alternative,value:r.name}))}],async v=>{
				const row=rows.find(r=>r.name===v.record);
				await frm.set_value({arrangement:row.name, student:row.student, alternate:row.alternative, received_by:frappe.session.user});
			},"确认本次交接");
		});
	}});
	frappe.ui.form.on(delivery,{refresh(frm) {
		if(frm.doc.docstatus!==1 || frm.doc.result!=="接收") return;
		const values={company:frm.doc.company,canteen:frm.doc.canteen,external_handover:frm.doc.name,meal_type:frm.doc.meal_type,meal_date:frm.doc.service_date};
		for(const [dt,label] of [["Tongjianyun Food Sample","登记留样"],["Tongjianyun Meal Companion","登记陪餐"]]) {
			if(frappe.model.can_create(dt)) frm.add_custom_button(label,()=>frappe.new_doc(dt,values));
		}
	}});
	frappe.ui.form.on(publication,{refresh(frm) {
		if(frm.doc.docstatus!==1||!frm.doc.public_key) return;
		const url=new URL("/meal_family",location.origin);url.searchParams.set("key",frm.doc.public_key);
		frm.add_custom_button("家长只读版",()=>window.open(url.href,"_blank","noopener,noreferrer"));
		if(!frm.doc.meal_week) frm.add_custom_button("登记到园交接",()=>frappe.new_doc(delivery,{company:frm.doc.company,canteen:frm.doc.canteen,publication:frm.doc.name}));
	}});
})();
