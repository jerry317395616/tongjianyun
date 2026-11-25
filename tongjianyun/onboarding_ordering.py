def _value(row, fieldname, default=None):
	if isinstance(row, dict):
		return row.get(fieldname, default)
	return getattr(row, fieldname, default)


def _set_value(row, fieldname, value):
	if isinstance(row, dict):
		row[fieldname] = value
	else:
		setattr(row, fieldname, value)


def _position(row, fallback):
	try:
		position = int(_value(row, "sequence") or fallback)
	except (TypeError, ValueError):
		position = fallback
	return max(position, 1)


def _row_index(row, fallback):
	try:
		return int(_value(row, "idx") or fallback)
	except (TypeError, ValueError):
		return fallback


def normalize_step_order(rows, previous_rows=None):
	"""Apply sequence values as insertion positions and return continuous ordering."""
	rows = list(rows or [])
	previous_rows = list(previous_rows or [])
	if not rows:
		return rows

	previous_by_name = {_value(row, "name"): row for row in previous_rows if _value(row, "name")}
	if not previous_by_name:
		ordered = sorted(
			rows,
			key=lambda row: (
				_position(row, len(rows) + 1),
				_row_index(row, len(rows) + 1),
			),
		)
	else:
		stable = []
		moved = []
		for row in rows:
			previous = previous_by_name.get(_value(row, "name"))
			if previous is None or _position(row, len(rows) + 1) != _position(previous, len(rows) + 1):
				moved.append(row)
			else:
				stable.append(row)

		ordered = sorted(
			stable,
			key=lambda row: (
				_position(previous_by_name[_value(row, "name")], len(rows) + 1),
				_row_index(previous_by_name[_value(row, "name")], len(rows) + 1),
			),
		)
		for row in sorted(moved, key=lambda item: _row_index(item, len(rows) + 1)):
			target = min(_position(row, len(ordered) + 1), len(ordered) + 1)
			ordered.insert(target - 1, row)

	for index, row in enumerate(ordered, start=1):
		_set_value(row, "idx", index)
		_set_value(row, "sequence", index)
	return ordered
