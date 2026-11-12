"""기존 CapCut 프로젝트의 자막 시간을 새 프로젝트 버전에 반영합니다.

- 자막 트랙만 고친다: 기본은 자막(subtitle)형 텍스트가 든 트랙, 없으면 '자막'이라는 이름의 트랙, 그것도 없으면 텍스트 클립이 가장 많은 트랙.
  --track 으로 트랙 이름을 직접 정할 수 있다.
- --start 는 자막 시작을, --end 는 자막 끝을 옮긴다(초, + 늦게 / - 빠르게).
- 다음 자막과 겹치지 않게 최소 --min-gap 초를 띄운다. 자막이 0.3초보다 짧아지지 않게 한다.
- CapCut이 켜져 있으면 거부한다(켜진 상태에서 고치면 CapCut이 덮어쓴다).
- 원본 프로젝트는 읽기만 하고, 새 이름의 스테이징 폴더에 사본을 만든다.
- --install을 지정하면 CapCut 프로젝트 목록에 새 버전을 등록한다.
- draft_content.json, template-2.tmp, Timelines/<id>/ 안 사본을 새 버전에서 함께 고친다.
- SRT 파일을 주면 그 SRT를 옮겨 '<이름>_shifted.srt'로 저장한다(원본 SRT는 그대로).

사용 예:
  python subs_shift.py "초벌_v001" --end +0.2 --name "초벌_v002"
  python subs_shift.py "초벌_v001" --start +0.15 --end +0.2 --name "초벌_v002" --install
  python subs_shift.py "초벌_v001" --start -0.1 --dry-run     # 바뀔 내용만 보기
  python subs_shift.py 초벌_v001.srt --end +0.2              # SRT 파일
"""
import argparse
import copy
import json
import re
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.dont_write_bytecode = True      # 스킬 폴더에 __pycache__ 를 만들지 않는다
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C  # noqa: E402

MIN_DUR = 0.3


def shift_cues(cues, ds, de, gap, limit=None):
    """cues: [[시작, 끝, ...]] (초). 시작 순으로 정렬돼 있어야 한다."""
    out = []
    for c in cues:
        out.append([max(0.0, c[0] + ds), max(0.0, c[1] + de)] + list(c[2:]))
    for i, c in enumerate(out):
        if limit is not None:
            c[1] = min(c[1], limit)
        if i + 1 < len(out):
            c[1] = min(c[1], out[i + 1][0] - gap)
        if c[1] - c[0] < MIN_DUR:
            c[1] = c[0] + MIN_DUR
            if i + 1 < len(out) and c[1] > out[i + 1][0] - gap:
                c[1] = max(c[0] + 0.05, out[i + 1][0] - gap)   # 다음 자막이 너무 붙어 있으면 짧아도 겹치지 않게
    return out


def parse_srt(text):
    blocks = re.split(r'\n\s*\n', text.replace('\r\n', '\n').strip())
    cues = []

    def ts(x):
        h, m, s = x.replace(',', '.').split(':')
        return int(h) * 3600 + int(m) * 60 + float(s)
    for b in blocks:
        lines = b.strip().split('\n')
        k = next((i for i, l in enumerate(lines) if '-->' in l), None)
        if k is None:
            continue
        a, z = [x.strip() for x in lines[k].split('-->')]
        cues.append([ts(a), ts(z.split()[0]), '\n'.join(lines[k + 1:])])
    return cues


def srt_time(t):
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def pick_tracks(D, name=None):
    M = C.material_index(D)
    texts = [t for t in D['tracks'] if t['type'] == 'text' and t['segments']]
    if name:
        sel = [t for t in texts if t.get('name') == name]
        if not sel:
            C.die(f'"{name}" 이름의 텍스트 트랙이 없습니다. 있는 트랙: {[t.get("name") for t in texts]}')
        return sel
    sub = [t for t in texts if sum(M.get(s['material_id'], (0, {}))[1].get('type') == 'subtitle' for s in t['segments']) > len(t['segments']) / 2]
    if sub:
        return sub
    named = [t for t in texts if re.search(r'자막|subtitle|caption', t.get('name', ''), re.I)]
    if named:
        return named
    return [max(texts, key=lambda t: len(t['segments']))] if texts else []


def apply(D, ds, de, gap, track_name=None):
    """D(드래프트)의 자막 트랙 시간을 옮긴다. 바뀐 자막 수와 예시를 돌려준다."""
    M = C.material_index(D)
    tracks = pick_tracks(D, track_name)
    if not tracks:
        C.die('텍스트(자막) 트랙이 없습니다.')
    total = D['duration'] / C.US
    changed, sample = 0, []
    for t in tracks:
        segs = sorted(t['segments'], key=lambda s: s['target_timerange']['start'])
        cues = [[s['target_timerange']['start'] / C.US, (s['target_timerange']['start'] + s['target_timerange']['duration']) / C.US, s]
                for s in segs]
        new = shift_cues(cues, ds, de, gap, total)
        for (a0, b0, s), (a1, b1, _) in zip(cues, new):
            st, en = C.us(a1), C.us(b1)
            if st != s['target_timerange']['start'] or en - st != s['target_timerange']['duration']:
                changed += 1
                if len(sample) < 5:
                    txt = ''
                    m = M.get(s['material_id'], (0, {}))[1]
                    try:
                        txt = json.loads(m.get('content', '{}')).get('text', '')
                    except Exception:
                        pass
                    sample.append(f'{C.mmss(a0)}~{C.mmss(b0)} → {C.mmss(a1)}~{C.mmss(b1)}  {txt[:24]}')
            s['target_timerange'] = dict(start=st, duration=max(1, en - st))
            dur = en - st
            for ref in s.get('extra_material_refs', []):          # 나가는 애니메이션 위치도 맞춘다
                k, m = M.get(ref, (None, {}))
                if k == 'material_animations':
                    for an in m.get('animations', []) or []:
                        if an.get('type') == 'out':
                            an['start'] = max(0, dur - an.get('duration', 0))
        t['segments'] = segs
    return changed, sample, [t.get('name') or '(이름 없음)' for t in tracks]


def matching_drafts(folder, project_id):
    """기준 타임라인과 같은 ID인 프로젝트 JSON 사본만 찾는다."""
    root = folder / 'draft_content.json'
    files = [root]
    candidates = [folder / 'template-2.tmp', folder / 'template.tmp']
    timelines = folder / 'Timelines'
    if timelines.exists():
        candidates += sorted(timelines.glob('*/draft_content.json'))
        candidates += sorted(timelines.glob('*/template*.tmp'))
    for path in candidates:
        if path.exists() and path not in files:
            try:
                if C.read_json(path).get('id') == project_id:
                    files.append(path)
            except (OSError, ValueError):
                pass
    return files


def stage_version(folder, stage, name, dest, drafts, shifted, ds, de, gap, track_name):
    """원본을 읽기만 하며 새 ID의 CapCut 프로젝트를 스테이징한다."""
    if stage.exists():
        C.die(f'스테이징 폴더가 이미 있습니다. 덮어쓰지 않습니다: {stage}')
    old_id = C.read_draft(folder / 'draft_content.json')['id']
    new_id = str(uuid.uuid4()).upper()
    ignore = shutil.ignore_patterns('*.bak', '.locked', '_staging_by_capcut_build.txt')
    try:
        shutil.copytree(folder, stage, ignore=ignore)
        timeline_dir = stage / 'Timelines'
        old_timeline = timeline_dir / old_id
        new_timeline = timeline_dir / new_id
        if old_timeline.exists():
            if new_timeline.exists():
                raise RuntimeError(f'새 타임라인 폴더가 이미 있습니다: {new_timeline}')
            old_timeline.rename(new_timeline)
        for source in drafts:
            relative = source.relative_to(folder)
            if relative.parts[:2] == ('Timelines', old_id):
                relative = Path('Timelines', new_id, *relative.parts[2:])
            target = stage / relative
            data = shifted if source == folder / 'draft_content.json' else C.read_draft(source)
            if source != folder / 'draft_content.json':
                apply(data, ds, de, gap, track_name)
            data['id'] = new_id
            C.write_json(target, data, compact=True)
        # CapCut의 template.tmp가 기준 드래프트보다 오래된 경우도 있다.
        # 새 버전에서는 메인 타임라인의 보조 파일을 동일한 내용으로 맞춘다.
        for target in (stage / 'template-2.tmp', stage / 'template.tmp',
                       new_timeline / 'template-2.tmp', new_timeline / 'template.tmp'):
            if target.exists():
                C.write_json(target, shifted, compact=True)
        project_json = timeline_dir / 'project.json'
        if project_json.exists():
            project = C.read_json(project_json)
            if project.get('id') == old_id:
                project['id'] = new_id
            if project.get('main_timeline_id') == old_id:
                project['main_timeline_id'] = new_id
            for item in project.get('timelines', []):
                if item.get('id') == old_id:
                    item['id'] = new_id
            C.write_json(project_json, project, compact=True)
        layout = stage / 'timeline_layout.json'
        if layout.exists():
            data = C.read_json(layout)
            for item in data.get('dockItems', []):
                item['timelineIds'] = [new_id if x == old_id else x for x in item.get('timelineIds', [])]
            C.write_json(layout, data, compact=True)
        meta_path = stage / 'draft_meta_info.json'
        meta = C.read_json(meta_path)
        now = C.now_us()
        meta.update(draft_id=new_id, draft_name=name, draft_fold_path=dest.as_posix(),
                    draft_root_path=dest.parent.as_posix(), tm_draft_create=now,
                    tm_draft_modified=now, tm_duration=shifted.get('duration', 0),
                    draft_is_invisible=False)
        C.write_json(meta_path, meta, compact=True)
        (stage / '_staging_by_capcut_build.txt').write_text('subs_shift.py가 만든 새 프로젝트 버전입니다.\n', 'utf-8')
        if C.read_draft(stage / 'draft_content.json')['id'] != meta['draft_id']:
            raise RuntimeError('스테이징 프로젝트 ID 검증 실패')
        return new_id
    except Exception:
        # stage는 이 함수의 copytree가 새로 만든 폴더다. 원본은 건드리지 않는다.
        if stage.exists():
            shutil.rmtree(stage)
        raise


def main():
    C.setup_console()
    ap = argparse.ArgumentParser(description='CapCut 자막 클립 시간 한 번에 옮기기')
    ap.add_argument('project', help='CapCut 프로젝트 이름, 프로젝트 폴더, 또는 .srt 파일')
    ap.add_argument('--start', type=float, default=0.0, help='자막 시작 이동(초, +늦게/-빠르게)')
    ap.add_argument('--end', type=float, default=0.0, help='자막 끝 이동(초)')
    ap.add_argument('--min-gap', type=float, default=0.04, help='자막 사이 최소 간격(초)')
    ap.add_argument('--track', help='고칠 텍스트 트랙 이름(기본: 자동)')
    ap.add_argument('--dry-run', action='store_true', help='바꾸지 않고 바뀔 내용만 보여 준다')
    ap.add_argument('--name', help='새 프로젝트 이름(기본: <원본>_shifted_날짜시각)')
    ap.add_argument('--stage-dir', help='스테이징 상위 폴더(기본: ./capcut_staging)')
    ap.add_argument('--install', action='store_true', help='새 버전을 CapCut 목록에 등록')
    ap.add_argument('--backup-dir', help='--install 때 프로젝트 목록 백업 폴더(기본: ./capcut_backups)')
    ap.add_argument('--capcut-dir', help='CapCut 프로젝트 폴더(자동으로 못 찾을 때)')
    a = ap.parse_args()
    if not a.start and not a.end:
        C.die('--start 나 --end 중 하나는 0이 아니어야 합니다.')

    p = Path(a.project)
    if p.suffix.lower() == '.srt' and p.is_file():
        cues = parse_srt(p.read_text('utf-8-sig'))
        new = shift_cues(sorted(cues, key=lambda c: c[0]), a.start, a.end, a.min_gap)
        out = p.with_name(p.stem + '_shifted.srt')
        if not a.dry_run:
            out.write_text('\n'.join(f'{i + 1}\n{srt_time(x)} --> {srt_time(y)}\n{z}\n' for i, (x, y, z) in enumerate(new)), 'utf-8-sig')
        print(f'SRT 자막 {len(new)}개 이동(시작 {a.start:+g}초, 끝 {a.end:+g}초) → {out if not a.dry_run else "(dry-run)"}')
        return

    folder = C.resolve_project(a.project, a.capcut_dir).resolve()
    if C.capcut_running() and not a.dry_run:
        C.die('CapCut이 켜져 있습니다. CapCut을 완전히 끈 뒤 다시 실행해 주세요(켜진 채로 고치면 CapCut이 덮어씁니다).', 2)
    root = folder / 'draft_content.json'
    D = C.read_draft(root)
    files = matching_drafts(folder, D.get('id'))
    changed, sample, names = apply(D, a.start, a.end, a.min_gap, a.track)
    print(f'프로젝트: {folder.name} · 트랙 {names} · 바뀌는 자막 {changed}개 (시작 {a.start:+g}초, 끝 {a.end:+g}초, 최소 간격 {a.min_gap}초)')
    for s in sample:
        print('  ' + s)
    if a.dry_run:
        print('(dry-run: 파일은 바꾸지 않았습니다)')
        return
    name = a.name or f'{folder.name}_shifted_{time.strftime("%Y%m%d_%H%M%S")}'
    if name in ('', '.', '..') or '/' in name or '\\' in name or name == folder.name:
        C.die('새 프로젝트에는 원본과 다른 한 단계의 폴더 이름을 지정해 주세요.')
    cc = C.find_capcut_dir(a.capcut_dir) if a.install else (folder.parent if (folder.parent / 'root_meta_info.json').exists()
                                                           else C.find_capcut_dir(a.capcut_dir, required=False))
    if cc is None:
        C.die('CapCut 프로젝트 폴더를 찾지 못했습니다. --capcut-dir 로 지정해 주세요.')
    dest = cc / name
    if dest.exists():
        C.die(f'같은 이름의 CapCut 프로젝트가 있습니다. 덮어쓰지 않습니다: {dest}')
    stage_parent = Path(a.stage_dir).resolve() if a.stage_dir else (Path.cwd() / 'capcut_staging').resolve()
    stage = stage_parent / name
    if stage == folder or folder in stage.parents:
        C.die('스테이징 폴더를 원본 프로젝트 안에 만들 수 없습니다.')
    if stage.exists():
        if not a.install or not (stage / '_staging_by_capcut_build.txt').exists():
            C.die(f'스테이징 폴더가 이미 있습니다. 덮어쓰지 않습니다: {stage}')
        staged = C.read_draft(stage / 'draft_content.json')
        meta = C.read_json(stage / 'draft_meta_info.json')
        expected = copy.deepcopy(D)
        expected['id'] = staged.get('id')
        if staged != expected or meta.get('draft_id') != staged.get('id') or meta.get('draft_name') != name:
            C.die('기존 스테이징 내용이 현재 원본/수정 옵션과 다릅니다. 새 이름으로 다시 만드세요.')
        print(f'검증된 스테이징 재사용: {stage}')
    else:
        stage_parent.mkdir(parents=True, exist_ok=True)
        stage_version(folder, stage, name, dest, files, D, a.start, a.end, a.min_gap, a.track)
    print(f'새 버전 스테이징: {stage} ({len(files)}개 자막 파일 갱신, 원본 보존)')
    if a.install:
        import capcut_build
        backup_root = Path(a.backup_dir).resolve() if a.backup_dir else Path.cwd() / 'capcut_backups'
        sys.exit(capcut_build.install(stage, cc, name, backup_root))
    print('CapCut 등록이 필요하면 같은 명령에 --install을 추가해 실행하세요.')


if __name__ == '__main__':
    main()
