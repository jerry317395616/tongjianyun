/**
 * Extend Recipe Ingredient form to support price fields and auto-calculate subtotal.
 * This runs on the standard Frappe form for Tongjianyun Recipe Ingredient.
 */
frappe.ui.form.on("Tongjianyun Recipe Ingredient", {
    setup: function (frm) {
        frm.set_query("unit", function () {
            return {
                filters: [
                    ["UOM", "name", "in", ["g", "kg", "mg", "ml", "L"]],
                ],
            };
        });
    },

    unit_price: function (frm) {
        calculateSubtotal(frm);
    },

    amount: function (frm) {
        calculateSubtotal(frm);
    },

    unit: function (frm) {
        calculateSubtotal(frm);
    },
});

/**
 * Calculate subtotal: amount / conversionFactor * unit_price
 * Assumes amount is in the given unit.
 * If unit is 'g', convert to kg: amount / 1000 * unit_price
 * If unit is 'kg', directly: amount * unit_price
 * If unit is 'mg', convert: amount / 1000000 * unit_price
 * If unit is 'ml' or 'L', same logic as g/kg
 */
function calculateSubtotal(frm) {
    if (!frm.doc.amount || !frm.doc.unit_price) {
        frm.set_value("subtotal", 0);
        return;
    }

    const amount = parseFloat(frm.doc.amount) || 0;
    const unitPrice = parseFloat(frm.doc.unit_price) || 0;
    const unit = (frm.doc.unit || "g").toLowerCase();

    let amountInKg = amount;
    switch (unit) {
        case "g":
        case "ml":
            amountInKg = amount / 1000;
            break;
        case "mg":
            amountInKg = amount / 1000000;
            break;
        case "kg":
        case "l":
            amountInKg = amount;
            break;
    }

    const subtotal = amountInKg * unitPrice;
    frm.set_value("subtotal", Math.round(subtotal * 100) / 100);
}
