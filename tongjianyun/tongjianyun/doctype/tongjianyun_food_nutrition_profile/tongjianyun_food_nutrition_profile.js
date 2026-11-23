frappe.ui.form.on("Tongjianyun Food Nutrition Profile", {
    setup(frm) {
        frm.set_query("item_code", () => ({
            query: "tongjianyun.dish_recipe_editor.ingredient_query",
            filters: {custom_tjy_standard_ingredient: 1, disabled: 0},
        }));
    },
});
