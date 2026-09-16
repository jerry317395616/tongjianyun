(() => {
  const definition = frappe.pages["tongjianyun-workbench"];
  if (!definition || definition._video_entry_installed) return;
  definition._video_entry_installed = true;
  const original = definition.on_page_show;
  definition.on_page_show = function (wrapper) {
    if (original) original.apply(this, arguments);
    if (wrapper.page && !wrapper._video_entry_added) {
      wrapper.page.add_inner_button("教师视频考勤", () => frappe.set_route("teacher-video-attendance"));
      wrapper._video_entry_added = true;
    }
  };
})();
