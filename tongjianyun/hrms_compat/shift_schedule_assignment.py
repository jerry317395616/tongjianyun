from datetime import timedelta

import frappe
from frappe.utils import getdate

_FREQUENCY_WEEKS = {
	"Every Week": 1,
	"Every 2 Weeks": 2,
	"Every 3 Weeks": 3,
	"Every 4 Weeks": 4,
}


class PreserveShiftCycleBoundaryMixin:
	def create_shifts(self, start_date: str, end_date: str | None = None) -> None:
		schedule = frappe.get_doc("Shift Schedule", self.shift_schedule)
		frequency_weeks = _FREQUENCY_WEEKS[schedule.frequency]
		super().create_shifts(start_date, end_date)
		self.db_set(
			"create_shifts_after",
			_processed_cycle_boundary(start_date, end_date, frequency_weeks),
			update_modified=False,
		)


def _processed_cycle_boundary(start_date, end_date, frequency_weeks):
	"""Include skipped weeks in the successful native generator's progress cursor."""
	start = getdate(start_date)
	end = getdate(end_date) if end_date else start + timedelta(days=90)
	elapsed = (end - start).days
	if elapsed < 0:
		return start - timedelta(days=1)

	cycle_days = 7 * frequency_weeks
	completed_cycles, cycle_offset = divmod(elapsed, cycle_days)
	if cycle_offset >= 6:
		elapsed = (completed_cycles + 1) * cycle_days - 1
	return start + timedelta(days=elapsed)
