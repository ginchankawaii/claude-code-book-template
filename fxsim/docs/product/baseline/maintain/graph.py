import ast, sys, pathlib, collections
root = pathlib.Path('.')
mods = {}
for p in list(root.glob('app/**/*.py')) + list(root.glob('scripts/*.py')):
    if '__pycache__' in str(p): continue
    name = '.'.join(p.with_suffix('').parts)
    if name.endswith('.__init__'): name = name[:-9]
    mods[name] = p
deps = collections.defaultdict(set)
for name, p in mods.items():
    tree = ast.parse(p.read_text())
    pkg = name.split('.')
    is_pkg = p.name == '__init__.py'
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in mods: deps[name].add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg if is_pkg else pkg[:-1]
                base = base[:len(base)-(node.level-1)]
                m = '.'.join(base + ([node.module] if node.module else []))
            else:
                m = node.module or ''
            if m in mods: deps[name].add(m)
            for a in node.names:
                c = m + '.' + a.name
                if c in mods: deps[name].add(c)
def closure(roots):
    seen=set(); st=list(roots)
    while st:
        x=st.pop()
        if x in seen: continue
        seen.add(x); st.extend(deps[x])
    return seen
live = closure(['scripts.run_ai_bridge'])
ops = closure(['scripts.run_monitor','app.server','scripts.diagnose_live','scripts.monitor_envelope'])
def loc(ms): return sum(len(mods[m].read_text().splitlines()) for m in ms)
print('LIVE BRAIN closure', len(live), loc(live)); print(sorted(live))
print('OPS-only (monitor/server/diagnose) minus live', len(ops-live), loc(ops-live)); print(sorted(ops-live))
rest = set(mods)-live-ops
print('REST', len(rest), loc(rest)); print(sorted(rest))
print('TOTAL', len(mods), loc(mods))
