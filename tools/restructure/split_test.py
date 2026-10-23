"""Split a mixed C test file into parts by subject (restructure step 6e).

Usage: python3 tools/restructure/split_test.py SPEC.json [--root DIR] [--check] [--list]
       python3 tools/restructure/split_test.py MERGE.json --merge [--root DIR] [--check]   (see merge())

SPEC: {"source": "<area>/test_pool_gNN.c", "parts": [{"file": "<area>/test_<behaviour>.c", "header": "<the comment text,
one paragraph per list item>", "calls": ["check_x", ...], "main_blocks": [n, ...]}, ...]}

The source is cut into its preamble (the leading comment, which is replaced, and the #include / #define lines, which every
part keeps), its top-level items (each with its leading comment) and main. A part gets the preamble, the items its calls
need (the named check functions and every item they reach by name, in the source's order), and a main with the source's
df_test_begin and df_test_end around the part's calls (in the source's order) and, for a main whose checks are written
inline, the numbered top-level statements of main's body that the part lists (main_blocks: 0-based, a statement being a
`{ ... }` block or one line, with its leading comment). Every check call and every main block of the source goes to exactly
one part, every item to at least one; anything else is refused. --check writes nothing and only verifies the spec. The
CTest name in df_test_begin becomes the part's (duoforge.<area>.<behaviour>). Stdlib only.
"""
import json
import re
import sys
from pathlib import Path


class Refused(Exception):
    pass


def top_level(text):
    """[(start, end)] of the top-level items: a run of lines from a non-blank line at depth 0 to the line where the depth
    is 0 again and the item ends (a closing } at the start of a line, or a ; at depth 0). Comments and strings are skipped."""
    items, depth, i, start, n = [], 0, 0, None, len(text)
    line_start = 0
    while i < n:
        c = text[i]
        if text.startswith('/*', i):
            j = text.index('*/', i + 2) + 2
            if start is None and depth == 0:
                start = line_start
            i = j
            continue
        if text.startswith('//', i):
            if start is None and depth == 0:
                start = line_start
            i = text.index('\n', i)
            continue
        if c == '"' or c == "'":
            j = i + 1
            while text[j] != c:
                j += 2 if text[j] == '\\' else 1
            i = j + 1
            continue
        if c == '\n':
            line_start = i + 1
            i += 1
            continue
        if c == '#' and depth == 0 and text[line_start:i].strip() == '':
            j = text.index('\n', i)
            while text[j - 1] == '\\':
                j = text.index('\n', j + 1)
            items.append(('pp', start if start is not None else line_start, j + 1))
            start = None
            i = j + 1
            line_start = i
            continue
        if not c.isspace() and start is None and depth == 0:
            start = line_start
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and text[line_start:i].strip() == '':
                end = text.index('\n', i) + 1
                if text[i + 1:end].strip() in ('', ';'):
                    items.append(('item', start, end))
                    start = None
                    i = end
                    line_start = i
                    continue
        elif c == ';' and depth == 0:
            end = text.index('\n', i) + 1
            items.append(('item', start, end))
            start = None
            i = end
            line_start = i
            continue
        i += 1
    return items


NAME = re.compile(r'^(?:static\s+)?(?:inline\s+|DFI_ALWAYS_INLINE\s+|const\s+)*[\w\s\*]*?\b(\w+)\s*(?:\(|\[|=|;)', re.M)


def item_name(body):
    code = re.sub(r'/\*.*?\*/', '', body, flags=re.S).strip()
    m = re.match(r'#define\s+(\w+)', code)
    if m:
        return m.group(1)
    if code.startswith('#'):
        return None
    m = re.match(r'(?:struct|union|enum)\s+(\w+)\s*\{', code)
    if m and code.rstrip().endswith('};'):  # a tagged type of its own: struct X {...};
        return m.group(1)
    m = re.match(r'enum\s*\{\s*(\w+)', code)
    if m:  # an anonymous enum: named by its first enumerator (every enumerator leads to it, see enumerators())
        return m.group(1)
    if code.startswith('typedef'):
        m = re.search(r'(\w+)\s*;\s*$', code)
        return m.group(1) if m else None
    m = NAME.search(code)
    return m.group(1) if m else None


def main_body_statements(body):
    """The top-level statements of main's body: [(start, end)] relative to body, each with its leading comment (a ; inside
    parentheses, as in a for, ends nothing)."""
    out, depth, paren, i, start, n, line_start = [], 0, 0, 0, None, len(body), 0
    while i < n:
        if body.startswith('/*', i):
            if start is None and depth == 0:
                start = line_start
            i = body.index('*/', i + 2) + 2
            continue
        if body.startswith('//', i):
            if start is None and depth == 0:
                start = line_start
            i = body.index('\n', i)
            continue
        c = body[i]
        if c in '"\'':
            j = i + 1
            while body[j] != c:
                j += 2 if body[j] == '\\' else 1
            i = j + 1
            continue
        if c == '\n':
            line_start = i + 1
        elif not c.isspace() and start is None and depth == 0:
            start = line_start
        if c == '(':
            paren += 1
        elif c == ')':
            paren -= 1
        elif c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                end = body.index('\n', i) + 1
                out.append((start, end))
                start = None
                i = end
                line_start = i
                continue
        elif c == ';' and depth == 0 and paren == 0:
            end = body.index('\n', i) + 1
            out.append((start, end))
            start = None
            i = end
            line_start = i
            continue
        i += 1
    return out


def code_only(text):
    """The text without its comments and string literals (a name there is no use)."""
    text = re.sub(r'/\*.*?\*/|//[^\n]*', ' ', text, flags=re.S)
    return re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'', '""', text)


def in_code(text, pattern, repl):
    """re.sub of pattern in the code of text only: comments and string literals stay as they are."""
    out, pos = [], 0
    for m in re.finditer(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"', text, flags=re.S):
        out.append(re.sub(pattern, repl, text[pos:m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(re.sub(pattern, repl, text[pos:]))
    return ''.join(out)


def enumerators(defs):
    """{enumerator: the item that defines it} of the anonymous enums among the items."""
    out = {}
    for n, b in defs:
        m = re.match(r'enum\s*\{([^}]*)\}', code_only(b).strip())
        if m:
            for e in re.findall(r'\b([A-Za-z_]\w*)\b(?:\s*=[^,]*)?\s*(?:,|$)', m.group(1)):
                out[e] = n
    return out


def norm(code):
    return ' '.join(re.sub(r'/\*.*?\*/', ' ', code, flags=re.S).split())


def support_items(root, spec, defs):
    """{old name: new name} of the items a support header provides (functions and types), after checking that each is the
    source's own copy: the header's item, with `static inline` read as `static` and its names read back as the source's,
    equals the source's item, comments and white space aside."""
    sup = spec.get('support')
    if not sup:
        return {}, None
    header = (root / 'tests' / sup['header']).read_text(encoding='utf-8')
    theirs_by_name = {}
    for kind, s, e in top_level(header[header.index('*/') + 2:]):
        body = header[header.index('*/') + 2:][s:e]
        if kind == 'item':
            theirs_by_name[item_name(body)] = body
    items = dict(defs)
    back = {new: old for old, new in sup['items'].items()}
    for old, new in sup['items'].items():
        if old not in items:
            raise Refused('support: the source has no %s' % old)
        if new not in theirs_by_name:
            raise Refused('support: %s has no %s' % (sup['header'], new))
        theirs = theirs_by_name[new].replace('static inline ', 'static ', 1)
        theirs = re.sub(r'\b(%s)\b' % '|'.join(map(re.escape, back)), lambda m: back[m.group(1)], theirs)
        if norm(theirs) != norm(items[old]):
            raise Refused('support: %s of %s is not the source\'s %s' % (new, sup['header'], old))
    return dict(sup['items']), sup['header']


def comment(ctest, text, width=128):
    """The part's leading comment: "<ctest> (white-box): " and the text, each paragraph wrapped to the width; a paragraph
    whose lines start with a space (a list) keeps its lines."""
    import textwrap
    out = []
    for k, para in enumerate(text.strip().split('\n\n')):
        if k == 0:
            para = '%s (white-box): %s' % (ctest, para)
        if para.startswith(' '):
            out += [(' * ' + l).rstrip() for l in para.split('\n')]
        else:
            out += [' * ' + l for l in textwrap.wrap(' '.join(para.split()), width - 3, break_on_hyphens=False)]
        out.append(' *')
    return '/*\n' + '\n'.join(out[:-1]) + '\n */\n'


SECTIONS = []  # every part split() made, as its pieces, for merge()


def merge(root, mspec):
    """One file from the parts of several splits (restructure step 6e, the Mega stones): mspec = {"file": <area>/test_x.c,
    "header": text, "sections": [{"spec": <split spec>, "prefix": "<name>_"}, ...]}. Each section is the part of its spec
    whose file is mspec's file (split() places and checks it as for any part). The includes are the union, a top-level
    item that two sections have is kept once when its text is the same and else renamed in each section by its prefix
    (code only), and main runs the sections' bodies in the given order. Returns (ctest, text)."""
    target = mspec['file']
    secs = []
    for sec in mspec['sections']:
        SECTIONS.clear()
        spec = sec['spec'] if isinstance(sec['spec'], dict) else json.loads((root / sec['spec']).read_text(encoding='utf-8'))
        sec = dict(sec, spec=spec)
        split(root, spec)
        mine = [x for x in SECTIONS if x['file'] == target]
        if len(mine) != 1:
            raise Refused('merge: %s has no part %s' % (sec['spec']['source'], target))
        secs.append(dict(mine[0], prefix=sec['prefix']))
    by_name = {}
    for k, x in enumerate(secs):
        for n, b in x['defs']:
            by_name.setdefault(n, []).append((k, b))
    rename = [dict() for _ in secs]

    def renamed(k, b):
        for o, n in rename[k].items():
            b = in_code(b, r'(?<![\w.>])%s\b' % re.escape(o), n)
        return b
    # A name two sections share stays one item only when its text is the same in both after each section's renames
    # (a function that calls a renamed helper differs too): renames until nothing changes.
    changed = True
    while changed:
        changed = False
        for n, uses in by_name.items():
            if len(uses) > 1 and any(n not in rename[k] for k, _ in uses) and \
                    len({norm(renamed(k, b)) for k, b in uses}) > 1:
                for k, _ in uses:
                    if n not in rename[k]:
                        rename[k][n] = secs[k]['prefix'] + n
                        changed = True
    lines_sys, lines_q, macros = [], [], []
    for x in secs:
        for l in x['preamble'].split('\n'):
            if l.startswith('#include <') and l not in lines_sys:
                lines_sys.append(l)
            elif l.startswith('#include "') and l not in lines_q:
                lines_q.append(l)
    defs_out, seen, body = [], set(), ''
    for k, x in enumerate(secs):
        used = set(re.findall(r'\b\w+\b', code_only(''.join(b for _, b in x['defs']) + x['body'])))
        for l in re.findall(r'^#define [^\n]*(?:\\\n[^\n]*)*', x['preamble'], re.M):
            name = re.match(r'#define (\w+)', l).group(1)
            if name not in used:
                continue  # a macro of another part of the source
            for o, n in rename[k].items():
                l = in_code(l, r'(?<![\w.>])%s\b' % re.escape(o), n)
            if any(re.match(r'#define %s\b' % re.escape(name), m) for m in macros) and l not in macros:
                rename[k][name] = x['prefix'] + name
                l = l.replace('#define ' + name, '#define ' + x['prefix'] + name, 1)
            if l not in macros:
                macros.append(l)
        def ren(text, k=k):
            for o, n in rename[k].items():
                text = in_code(text, r'(?<![\w.>])%s\b' % re.escape(o), n)
            return text
        for n, b in x['defs']:
            nn = rename[k].get(n, n)
            if nn in seen:
                continue
            seen.add(nn)
            defs_out.append(ren(b))
        # each section's statements in a block of their own (two sections may both declare a context `kp`)
        block = ''.join(('    ' + l if l.strip() else l) for l in ren(x['body']).splitlines(True))
        body += '    { /* %s */\n%s    }\n' % (x['prefix'].rstrip('_').replace('_', ' '), block)
    m = re.fullmatch(r'([a-z]+)/test_([a-z0-9_]+)\.c', target)
    ctest = 'duoforge.%s.%s' % (m.group(1), m.group(2))
    groups = [sorted(l for l in lines_sys if not l.startswith('#include <duoforge/')),
              sorted(l for l in lines_sys if l.startswith('#include <duoforge/')), sorted(lines_q)]
    pre = '\n\n'.join('\n'.join(g) for g in groups if g) + '\n'
    if macros:
        pre += '\n' + '\n'.join(macros) + '\n'
    head = secs[0]['main_head'].replace(secs[0]['old_ctest'], ctest)
    text = comment(ctest, mspec['header']) + pre + ''.join('\n' + d.lstrip('\n') for d in defs_out) + '\n' + \
        head + body + secs[0]['main_tail']
    return ctest, text


def split(root, spec):
    src = root / 'tests' / spec['source']
    text = src.read_text(encoding='utf-8')
    if not text.startswith('/*'):
        raise Refused('%s does not start with its comment' % spec['source'])
    head_end = text.index('*/') + 3
    items = top_level(text[head_end:])
    items = [(k, s + head_end, e + head_end) for k, s, e in items]
    pre, defs, main_item = [], [], None
    first_def = next(s for k, s, e in items if k == 'item')
    pre.append(text[head_end:first_def].rstrip('\n') + '\n')  # the includes and macros before the first item, as written
    for kind, s, e in items:
        body = text[s:e]
        if kind == 'pp':
            if s >= first_def:
                if not re.match(r'\s*#\s*(define|undef)\b', re.sub(r'/\*.*?\*/', '', body, flags=re.S)):
                    raise Refused('a preprocessor conditional or include after the first item (%s): split by hand'
                                  % body.strip().split('\n')[-1][:60])
                pre.append(body)
        elif re.search(r'^int main\(void\)', body, re.M):
            main_item = body
        else:
            defs.append((item_name(body), body))
    if main_item is None:
        raise Refused('no main')
    names = [n for n, _ in defs]
    if None in names or len(set(names)) != len(names):
        raise Refused('items without a name or twice: %s' % names)
    provided, sup_header = support_items(root, spec, defs)
    funcs = {n for n, b in defs if re.search(r'^static [^\n=;]*\b%s\(' % re.escape(n), b, re.M)}
    mb = main_item[main_item.index('{') + 1:main_item.rindex('}')]
    begin = re.search(r'^    df_test_begin\(&t, "([^"]+)"\);\n', mb, re.M)
    end = re.search(r'^    return df_test_end\(&t\);\n', mb, re.M)
    if not begin or not end:
        raise Refused('main has no df_test_begin / return df_test_end')
    decl_end = begin.end()
    inner = mb[decl_end:end.start()]
    stmts = main_body_statements(inner)
    stmt_texts = [inner[s:e] for s, e in stmts]
    call_of = {}
    for k, st in enumerate(stmt_texts):
        m = re.fullmatch(r'\s*(\w+)\(&t(?:, [^;]*)?\);\s*', re.sub(r'/\*.*?\*/', '', st, flags=re.S))
        if m and m.group(1) in names:
            call_of[k] = m.group(1)
    taken_calls, taken_blocks, used_items = {}, {}, set()
    parts = []
    body_calls = {}
    for part in spec['parts']:
        sel = set()
        if 'main_body' in part:  # a main written out (a loop over contexts that calls several parts' checks)
            body = '\n'.join(part['main_body']) + '\n'
            for n in re.findall(r'\b(\w+)\(&t', body):
                if n in names:
                    body_calls[n] = part['file']  # how often and with what is checked below, against the source's calls
        for c in part.get('calls', []):
            ks = [k for k, n in call_of.items() if n == c]
            if not ks:
                raise Refused('%s: no call of %s in main' % (part['file'], c))
            for k in ks:
                if k in taken_calls:
                    raise Refused('%s: the call of %s is in %s already' % (part['file'], c, taken_calls[k]))
                taken_calls[k] = part['file']
                sel.add(k)
        shared = set(spec.get('shared_blocks', []))
        for k in part.get('main_blocks', []):
            if k in call_of or not 0 <= k < len(stmt_texts):
                raise Refused('%s: main block %d is a call or out of range' % (part['file'], k))
            if k in shared:
                taken_blocks.setdefault(k, part['file'])
                sel.add(k)
                continue
            if k in taken_blocks:
                raise Refused('%s: main block %d is in %s already' % (part['file'], k, taken_blocks[k]))
            taken_blocks[k] = part['file']
            sel.add(k)
        if 'main_body' not in part:
            body = ''.join(stmt_texts[k] for k in sorted(sel))
        aliases = enumerators(defs)
        refs = lambda text: {aliases.get(w, w) for w in re.findall(r'\b\w+\b', code_only(text))} & set(names)
        need, todo = set(), refs(body)
        while todo:
            n = todo.pop()
            if n in need:
                continue
            need.add(n)
            todo |= refs(dict(defs)[n]) - {n}
        used_items |= need
        m = re.fullmatch(r'([a-z]+)/test_([a-z0-9_]+)\.c', part['file'])
        if not m:
            raise Refused('part file %r' % part['file'])
        ctest = 'duoforge.%s.%s' % (m.group(1), m.group(2))
        # a part that stays the source (its file and name) keeps the source's own comment
        header = text[:head_end] if part.get('keep_header') else comment(ctest, part['header'])
        preamble = ''.join(pre)
        if sup_header and need & set(provided):
            quoted = list(re.finditer(r'^#include "([^"]+)"\n', preamble, re.M))
            after = [m for m in quoted if m.group(1) < sup_header]  # in the sorted place among the quoted includes
            at = after[-1].end() if after else quoted[0].start()
            preamble = preamble[:at] + '#include "%s"\n' % sup_header + preamble[at:]
        defs_text = ''.join('\n' + b.lstrip('\n') if not b.startswith('\n') else b
                            for n, b in defs if n in need and n not in provided)
        new_main = main_item[:main_item.index('{') + 1] + mb[:decl_end].replace(begin.group(1), ctest) + body + mb[end.start():] + '}\n'
        code = defs_text + '\n' + new_main.lstrip('\n')
        for o, n in provided.items():  # the header's names: a function where it is called, a type as a word
            if o in funcs:
                code = in_code(code, r'(?<![\w.>])%s\(' % re.escape(o), n + '(')
            else:
                code = in_code(code, r'(?<![\w.>])%s\b' % re.escape(o), n)
        out = header + preamble + code
        parts.append((part['file'], ctest, out))
        sec_defs = []
        for n, b in defs:
            if n in need and n not in provided:
                for o, nn in provided.items():
                    b = in_code(b, r'(?<![\w.>])%s\b' % re.escape(o), nn)
                sec_defs.append((n, b))
        sec_body = body
        for o, nn in provided.items():
            sec_body = in_code(sec_body, r'(?<![\w.>])%s\b' % re.escape(o), nn)
        SECTIONS.append({'file': part['file'], 'source': spec['source'], 'preamble': preamble, 'defs': sec_defs,
                         'body': sec_body, 'main_head': main_item[:main_item.index('{') + 1] + mb[:decl_end],
                         'main_tail': mb[end.start():] + '}\n', 'old_ctest': begin.group(1)})
    if spec.get('list'):
        return begin.group(1), [('%d%s' % (k, ' call ' + call_of[k] if k in call_of else ''), '', st) for k, st in enumerate(stmt_texts)]
    if body_calls:
        # A main written out: every check call of the source main, with its arguments, is made by exactly one part (as a
        # multiset of call texts), and every other line of the source main is a line of some part's main (its loops, its
        # contexts, its guards). The parts may add lines (a context of their own), which the proof counts.
        def lines(text):
            return [' '.join(l.split()) for l in code_only(text).split('\n') if l.strip()]
        is_call = lambda l: re.match(r'(\w+)\(&t\b', l) and re.match(r'(\w+)', l).group(1) in names
        src_calls = sorted(l for l in lines(inner) if is_call(l))
        part_lines = [lines('\n'.join(p['main_body']) if 'main_body' in p else
                            ''.join(stmt_texts[k] for k in range(len(stmt_texts))
                                    if taken_calls.get(k) == p['file'] or taken_blocks.get(k) == p['file']
                                    or k in set(spec.get('shared_blocks', [])) & set(p.get('main_blocks', []))))
                      for p in spec['parts']]
        got_calls = sorted(l for pl in part_lines for l in pl if is_call(l))
        if src_calls != got_calls:
            raise Refused('main_body: the parts make the calls %s, the source %s' % (got_calls, src_calls))
        every = {l for pl in part_lines for l in pl}
        missing = [l for l in lines(inner) if not is_call(l) and l not in every]
        if missing:
            raise Refused('main_body: lines of the source main in no part: %s' % missing)
        left_calls = left_blocks = []
    else:
        left_calls = sorted(set(call_of) - set(taken_calls))
        left_blocks = sorted(set(range(len(stmt_texts))) - set(call_of) - set(taken_blocks))
    if left_calls or left_blocks:
        raise Refused('not placed: calls %s, main blocks %s (%s)' % (
            [call_of[k] for k in left_calls], left_blocks,
            '; '.join('%d: %s' % (k, stmt_texts[k].strip().split('\n')[0][:70]) for k in left_blocks)))
    unused = [n for n in names if n not in used_items]
    if unused:
        raise Refused('items no part uses: %s' % unused)
    return begin.group(1), parts


def main(argv):
    root = Path(__file__).resolve().parents[2]
    args = list(argv)
    if '--root' in args:
        i = args.index('--root')
        root = Path(args[i + 1]).resolve()
        del args[i:i + 2]
    check = '--check' in args
    listing = '--list' in args
    merging = '--merge' in args
    args = [a for a in args if a not in ('--check', '--list', '--merge')]
    skip = set()
    while '--except' in args:  # a part another step writes (the target of a merge)
        i = args.index('--except')
        skip.add(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        print(__doc__)
        return 2
    spec = json.loads(Path(args[0]).read_text(encoding='utf-8'))
    if merging:
        try:
            ctest, text = merge(root, spec)
        except Refused as e:
            print('split_test: refused: %s' % e, file=sys.stderr)
            return 2
        print('%s %s %s (%d lines)' % ('would write' if check else 'writes', spec['file'], ctest, text.count('\n')))
        if not check:
            (root / 'tests' / spec['file']).write_text(text, encoding='utf-8', newline='\n')
        return 0
    if listing:
        spec = {'source': spec['source'], 'parts': [], 'list': True}
    try:
        old, parts = split(root, spec)
    except Refused as e:
        print('split_test: refused: %s' % e, file=sys.stderr)
        return 2
    if listing:
        for k, _, st in parts:
            print('[%s] %s' % (k, ' '.join(st.split())[:150]))
        return 0
    for f, ctest, text in parts:
        if f in skip:
            print('leaves %s (written by its merge)' % f)
            continue
        print('%s %s %s (%d lines)' % ('would write' if check else 'writes', f, ctest, text.count('\n')))
        if not check:
            (root / 'tests' / f).write_text(text, encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
