// Browser ESM uses .js so the existing site's MIME configuration serves JavaScript.
export const STATUS = {Present: '已登记到园', Absent: '缺勤', Leave: '请假', Unknown: '待点名'};
export const COLORS = {Present: '#32b489', Absent: '#e48185', Leave: '#e9b45e', Unknown: '#a4b4c7'};
export const MEALS = [['breakfast', '早餐'], ['morning_snack', '早点'], ['lunch', '午餐'], ['afternoon_snack', '午点'], ['dinner', '晚餐']];
export const LOG_TYPES = {General: '日常观察', Academic: '学习活动', Achievement: '成长瞬间'};
export const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
export function mealSelections(rows) {
  return rows.map(row => {
    const result = {student: row.student, student_name: row.student_name};
    MEALS.forEach(([key]) => { result[key] = row[key] === '不供餐' ? '不供餐' : row[key] === '已就餐' ? '就餐' : row[key] === '未就餐' ? '不就餐' : row[`${key}_expected`] ? '就餐' : '不就餐'; });
    return result;
  });
}
export const mealTotals = rows => Object.fromEntries(MEALS.map(([key]) => [key, rows.filter(r => r[key] === '就餐').length]));
export const timeLabel = value => String(value || '').replace(/^(\d):/, '0$1:').slice(0, 5);
export function hash(value) { let h = 0; for (const c of String(value)) h = (Math.imul(h, 31) + c.codePointAt(0)) | 0; return h >>> 0; }
export function attendanceChanges(rows, edits) {
  return rows.filter(row => edits[row.student] && edits[row.student].status !== row.status)
    .map(row => ({student: row.student, status: edits[row.student].status, leave_reason: edits[row.student].leave_reason || ''}));
}
