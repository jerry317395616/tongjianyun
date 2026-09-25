"""Read-only scene views for explicit, version-bound private proposal handoffs.

The browser never chooses an owner/site and a GET never accepts or activates a
proposal. Lists are freshly authorized by BusinessProposals, including their
lookahead rows. Presentation does not turn a handoff receipt into activation.
"""
from copy import deepcopy

from tongjianyun.business_agent_proposals import _id

VIEWS = {'business_proposal_inbox': '方案交接', 'business_proposal_handoff': '查看交接方案'}
FIELDS = {'folder', 'state', 'cursor', 'handoff_id'}
STATES = {'pending': '待接收', 'copying': '正在核对接收结果', 'uncertain': '接收结果待核实',
          'accepted': '已接收，启用状态另行核验', 'stale': '方案已修改，请重新交接'}


def selection(value):
    if type(value) is not dict:
        raise ValueError('Expected an exact proposal view selection')
    view = value.get('view')
    if view == 'business_proposal_handoff':
        if set(value) != {'view', 'handoff_id'}:
            raise ValueError('A handoff view only accepts its exact identifier')
        return {'view': view, 'handoff_id': _id(value['handoff_id'])}
    if (view != 'business_proposal_inbox' or set(value) - {'view', 'folder', 'state', 'cursor'}
            or value.get('folder') not in ('sent', 'received')):
        raise ValueError('Expected a private sent or received handoff list')
    state = value.get('state', 'all' if value['folder'] == 'sent' else 'pending')
    if state not in ('pending', 'all') or value['folder'] == 'sent' and state != 'all':
        raise ValueError('Unsupported handoff list filter')
    clean = {'view': view, 'folder': value['folder'], 'state': state}
    if 'cursor' in value:
        clean['cursor'] = _id(value['cursor'])
    return clean


def _application():
    from tongjianyun.business_agent_service import application
    from tongjianyun.business_agent_proposals import BusinessProposals
    app, _ = application(require_ready=False)
    if not isinstance(app.proposals, BusinessProposals):
        raise PermissionError('Private proposal storage is unavailable')
    return app.proposals, app.viewer()


def _action(label, choice):
    return {'label': label, 'selection': choice}


def get_view(value):
    choice = selection(value)
    proposals, viewer = _application()
    if choice['view'] == 'business_proposal_handoff':
        result = deepcopy(proposals.preview_handoff(viewer, choice['handoff_id']))
        if result.get('handoff_id') != choice['handoff_id'] or result.get('handoff_state') not in STATES:
            raise ValueError('Unverified handoff preview')
        state = result['handoff_state']
        blocks = result.get('components')
        if not isinstance(blocks, list) or len(blocks) != 1 or blocks[0].get('type') != 'business_proposal':
            raise ValueError('Unexpected private proposal preview')
        blocks[0].update(type='business_proposal_handoff', handoff_id=choice['handoff_id'],
                         handoff_state=state, sender=result['sender'], can_handoff=False,
                         can_activate=False, can_accept=state == 'pending',
                         warnings=['这是明确交给当前账号的固定方案版本，不是业务记录。',
                                   '接收仅保存负责人自己的私有方案，不会自动启用业务或授予任何角色。'])
        if state == 'accepted':
            target = result.get('accepted_selection')
            if (type(target) is not dict or set(target) != {'view', 'proposal_id'}
                    or target.get('view') != 'business_blueprint'
                    or not isinstance(target.get('proposal_id'), str) or not 1 <= len(target['proposal_id']) <= 140
                    or any(ord(c) < 32 for c in target['proposal_id'])):
                raise ValueError('Accepted proposal needs a freshly verified private File')
            blocks[0]['accepted_selection'] = target
        result.update(view=choice['view'], selection=choice,
                      subtitle='方案交接 · ' + STATES[state],
                      actions=[_action('返回收到的方案', {'view': 'business_proposal_inbox', 'folder': 'received', 'state': 'all'})],
                      summary={'handoff_state': state, 'activation_verified': False,
                               'answer': '已读取明确交给当前账号的固定版本；接收方案不等于启用业务。'})
        return result

    incoming = choice['folder'] == 'received'
    page = (proposals.list_received(viewer, cursor=choice.get('cursor'), size=10, state=choice['state']) if incoming
            else proposals.list_sent(viewer, cursor=choice.get('cursor'), size=10))
    rows = []
    for entry in page['entries']:
        target = ({'view': 'business_proposal_handoff', 'handoff_id': entry['handoff_id']} if incoming else
                  {'view': 'business_proposal', 'proposal_id': entry['proposal_id'], 'revision': entry['revision']})
        rows.append({'cells': [entry['title'], entry['sender' if incoming else 'recipient'], STATES[entry['state']]],
                     'action': _action('查看交接方案' if incoming else '查看原方案', target)})
    actions = []
    if 'cursor' in choice:
        actions.append(_action('回到第一页', {k: v for k, v in choice.items() if k != 'cursor'}))
    if page['has_more']:
        actions.append(_action('下一页', {**choice, 'cursor': _id(page['next_cursor'])}))
    if incoming:
        actions.append(_action('查看全部接收记录' if choice['state'] == 'pending' else '仅看待处理',
                               {'view': choice['view'], 'folder': 'received', 'state': 'all' if choice['state'] == 'pending' else 'pending'}))
    return {'selection': choice, 'title': '收到的业务方案' if incoming else '我交出的业务方案',
            'subtitle': page['scope'], 'components': [
                {'type': 'table', 'title': '方案交接记录', 'columns': ['方案', '提出人' if incoming else '接收人', '状态'], 'rows': rows},
                {'type': 'notice', 'text': ('本页暂无可见交接记录。' if not rows else f'本页 {len(rows)} 条；这是交接记录，不是已启用业务数。') +
                 '修改草稿后，旧的待接收交接会失效。接收结果不明时请核对，不要重复提交。'}],
            'actions': actions, 'source': page['note'],
            'summary': {'page_count': len(rows), 'has_more': page['has_more'], 'activation_verified': False,
                        'answer': f'本页 {len(rows)} 条可见方案交接记录；不代表这些业务已经启用。'}}
