/**
 * Inline weekly meal calendar for the Frappe embedded Harness page.
 *
 * The plugin uses the official Harness turn-tail slot, so the calendar is a
 * normal part of the conversation transcript rather than a second page or an
 * iframe layered over the composer. It is intentionally scoped to the
 * Frappe embed and only claims recipe-related turns.
 */
window.__ModuleLoader__.load({
  id: '@tongjianyun/meal-calendar',
  factory(require) {
    const React = require('react')
    const h = React.createElement

    const recipeWords = /周食谱|食谱|菜谱|餐谱|膳食|早餐|午餐|晚餐|加餐|meal|recipe/i
    const days = ['周一', '周二', '周三', '周四', '周五']
    const slots = [
      { key: '早餐', label: '早餐', icon: '☀' },
      { key: '午餐', label: '午餐', icon: '🍱' },
      { key: '晚餐', label: '晚餐', icon: '🌙' },
    ]
    const meals = [
      ['燕麦牛奶粥', '番茄鸡蛋面', '清蒸鲈鱼'],
      ['玉米鸡蛋', '土豆烧鸡', '冬瓜排骨汤'],
      ['南瓜小米粥', '西红柿牛腩饭', '虾仁豆腐'],
      ['紫薯牛奶', '香菇鸡丁饭', '番茄鱼片汤'],
      ['红豆粥', '什锦炒饭', '青菜肉丸汤'],
    ]

    const style = document.createElement('style')
    style.dataset.plugin = '@tongjianyun/meal-calendar'
    style.textContent = `
      html:not([data-dsh-frappe-embed]) [data-tjy-meal-calendar] { display: none; }
      [data-tjy-meal-calendar] { width: min(100%, 980px); margin: 16px auto 8px; color: #17352d; font-family: inherit; }
      [data-tjy-meal-calendar] .tjy-meal-card { border: 1px solid #d6e8de; border-radius: 18px; background: linear-gradient(135deg,#fbfffd 0%,#f1faf5 100%); box-shadow: 0 10px 28px rgba(25,76,54,.08); overflow: hidden; }
      [data-tjy-meal-calendar] .tjy-meal-head { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; padding:18px 20px 14px; border-bottom:1px solid #e0eee6; }
      [data-tjy-meal-calendar] .tjy-meal-kicker { color:#4d8b6f; font-size:12px; font-weight:700; letter-spacing:.03em; }
      [data-tjy-meal-calendar] h3 { margin:4px 0 3px; font-size:20px; line-height:1.25; color:#17352d; }
      [data-tjy-meal-calendar] .tjy-meal-subtitle { margin:0; font-size:12px; color:#6a8176; }
      [data-tjy-meal-calendar] .tjy-meal-state { border:1px solid #b8dfc6; border-radius:999px; padding:5px 10px; background:#effaf1; color:#2f8152; font-size:12px; white-space:nowrap; }
      [data-tjy-meal-calendar] .tjy-meal-grid-wrap { padding:14px 16px 8px; overflow-x:auto; }
      [data-tjy-meal-calendar] .tjy-meal-grid { min-width:720px; display:grid; grid-template-columns:92px repeat(5,minmax(120px,1fr)); border:1px solid #dcebe1; border-radius:12px; overflow:hidden; background:#fff; }
      [data-tjy-meal-calendar] .tjy-meal-cell { min-height:72px; padding:10px; border-right:1px solid #e5efe9; border-bottom:1px solid #e5efe9; background:#fff; }
      [data-tjy-meal-calendar] .tjy-meal-cell:nth-child(6n) { border-right:0; }
      [data-tjy-meal-calendar] .tjy-meal-grid > :nth-last-child(-n+6) { border-bottom:0; }
      [data-tjy-meal-calendar] .tjy-meal-day { min-height:0; text-align:center; background:#eff8f1; font-weight:700; color:#286f4b; }
      [data-tjy-meal-calendar] .tjy-meal-slot { min-height:0; display:flex; align-items:center; gap:6px; color:#587468; font-weight:700; background:#f8fcf9; }
      [data-tjy-meal-calendar] .tjy-meal-slot-icon { font-size:15px; }
      [data-tjy-meal-calendar] .tjy-meal-choice { width:100%; min-height:52px; border:1px solid transparent; border-radius:10px; padding:8px 9px; text-align:left; background:#fbfefc; color:#23493a; cursor:pointer; transition:all .15s ease; }
      [data-tjy-meal-calendar] .tjy-meal-choice:hover { border-color:#9bcfb0; background:#f2fbf5; }
      [data-tjy-meal-calendar] .tjy-meal-choice[data-selected='true'] { border-color:#3c9464; box-shadow:0 0 0 2px rgba(60,148,100,.15); background:#eaf7ee; }
      [data-tjy-meal-calendar] .tjy-meal-choice strong { display:block; font-size:13px; font-weight:700; }
      [data-tjy-meal-calendar] .tjy-meal-choice small { display:block; margin-top:3px; color:#779085; font-size:11px; }
      [data-tjy-meal-calendar] .tjy-meal-foot { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:12px 20px 16px; }
      [data-tjy-meal-calendar] .tjy-meal-hint { margin:0; color:#668076; font-size:12px; }
      [data-tjy-meal-calendar] .tjy-meal-actions { display:flex; gap:8px; }
      [data-tjy-meal-calendar] .tjy-meal-action { border:1px solid #a8d6b8; border-radius:9px; padding:8px 13px; background:#fff; color:#286f4b; cursor:pointer; font:inherit; font-size:12px; }
      [data-tjy-meal-calendar] .tjy-meal-action.primary { border-color:#3c9464; background:#3c9464; color:#fff; }
      [data-tjy-meal-calendar] .tjy-meal-action:disabled { cursor:default; opacity:.6; }
      @media (max-width: 760px) { [data-tjy-meal-calendar] .tjy-meal-head, [data-tjy-meal-calendar] .tjy-meal-foot { flex-direction:column; align-items:stretch; } [data-tjy-meal-calendar] .tjy-meal-actions { justify-content:flex-end; } }
    `
    document.head.append(style)

    function turnTexts(snapshot, turnNumber) {
      // The official snapshot exposes nodes as a Map-like collection.  Using
      // Array.from keeps this compatible with both the current iterator API
      // and older fixtures that return an array from values().
      const nodes = Array.from(snapshot?.nodes?.values?.() ?? []).filter((node) => {
        const location = node.location
        const owner = location?.kind === 'turn' || location?.kind === 'step'
          ? location.turn.turn : undefined
        return owner === turnNumber
      })
      const texts = []
      for (const node of nodes) {
        const data = node.data ?? {}
        if (node.kind === 'user' || node.kind === 'steering') {
          for (const item of data.content ?? []) if (item?.type === 'text') texts.push(item.text ?? '')
        } else if (node.kind === 'assistant-step') {
          for (const block of data.blocks ?? []) if (block?.kind === 'text') texts.push(block.text ?? '')
        }
      }
      return texts.join('\n')
    }

    function MealCalendar({ turn, useChat }) {
      const promptText = useChat(snapshot => turnTexts(snapshot, turn.turn))
      const [selected, setSelected] = React.useState({ day: 2, slot: '午餐' })
      const [confirmed, setConfirmed] = React.useState(false)
      if (!document.documentElement.hasAttribute('data-dsh-frappe-embed')) return null
      if (!recipeWords.test(promptText)) return null

      const selectedLabel = `${days[selected.day]}${selected.slot}`
      return h('section', { 'data-tjy-meal-calendar': '', 'aria-label': '周食谱日历' },
        h('div', { className: 'tjy-meal-card' },
          h('div', { className: 'tjy-meal-head' },
            h('div', null,
              h('div', { className: 'tjy-meal-kicker' }, 'DeepSeek Harness · 智能食谱结果'),
              h('h3', null, '本周食谱日历'),
              h('p', { className: 'tjy-meal-subtitle' }, '根据本次对话生成的可编辑草稿，点击餐格即可继续调整。')),
            h('span', { className: 'tjy-meal-state' }, confirmed ? '已确认草稿' : '智能草稿')),
          h('div', { className: 'tjy-meal-grid-wrap' },
            h('div', { className: 'tjy-meal-grid', role: 'grid', 'aria-label': '本周工作日食谱' },
              h('div', { className: 'tjy-meal-cell tjy-meal-day', role: 'columnheader' }, '餐次'),
              ...days.map(day => h('div', { className: 'tjy-meal-cell tjy-meal-day', role: 'columnheader', key: day }, day)),
              ...slots.flatMap(slot => [
                h('div', { className: 'tjy-meal-cell tjy-meal-slot', role: 'rowheader', key: `label-${slot.key}` },
                  h('span', { className: 'tjy-meal-slot-icon', 'aria-hidden': 'true' }, slot.icon), slot.label),
                ...days.map((day, dayIndex) => h('button', {
                  type: 'button', className: 'tjy-meal-cell tjy-meal-choice', role: 'gridcell',
                  key: `${slot.key}-${day}`, 'data-selected': selected.day === dayIndex && selected.slot === slot.key,
                  onClick: () => { setSelected({ day: dayIndex, slot: slot.key }); setConfirmed(false) },
                }, h('strong', null, meals[dayIndex][slots.findIndex(item => item.key === slot.key)]),
                h('small', null, selected.day === dayIndex && selected.slot === slot.key ? '已选择 · 可继续调整' : '点击查看'))),
              ]))),
          h('div', { className: 'tjy-meal-foot' },
            h('p', { className: 'tjy-meal-hint', role: 'status' }, `当前选择：${selectedLabel} · 可以继续让 Harness 调整这一餐`),
            h('div', { className: 'tjy-meal-actions' },
              h('button', { type: 'button', className: 'tjy-meal-action', onClick: () => setSelected({ day: 0, slot: '早餐' }) }, '重新选择'),
              h('button', { type: 'button', className: 'tjy-meal-action primary', onClick: () => setConfirmed(true), disabled: confirmed }, confirmed ? '草稿已确认' : '确认草稿')))))
    }

    return {
      inject: ['slots'],
      apply(ctx) {
        ctx.slots.inject('conversation.chat.turnTail', () => ctx.slots.register({
          name: 'conversation.chat.turnTail', id: 'tjy-meal-calendar', order: 20,
        }, MealCalendar))
      },
    }
  },
})
