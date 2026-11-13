const $ = (selector) => document.querySelector(selector);
const jobsBody = $('#jobsBody');
const detailPanel = $('#detailPanel');
const checked = new Set();
let state = {jobs: []};
let currentId = null;
let detailSignature = '';
let detailStructureSignature = '';
let replacement = null;
let polling = false;
let toastTimer;
let tableSignature = '';
const scriptDrafts = new Map();
let showCompleted = true;
try { showCompleted = localStorage.getItem('reels.showCompleted') !== 'false'; } catch {}
const fileTypes = {
  video: '.mp4,.mov,.mkv,.avi',
  script: '.md',
  music: '.mp3,.wav,.m4a,.aac,.ogg',
  outro: '.svg,.png,.jpg,.jpeg,.webp',
};

const escapeHTML = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const bytes = (value) => value >= 1048576 ? `${(value / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(value / 1024))} KB`;
const statusNames = {waiting:'대기', queued:'대기 중', editing:'편집 중', done:'완료', failed:'실패'};
const progressOf = (job) => Math.max(0, Math.min(100, Math.round(
  Number(job.progress ?? (job.status === 'done' ? 100 : 0)) || 0,
)));
const completeTime = (value) => value ? new Date(value).toLocaleString('ko-KR', {
  year:'numeric', month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', timeZone:'Asia/Seoul',
}) : '';
const scriptDraft = (job) => scriptDrafts.has(job.id) ? scriptDrafts.get(job.id) : (job.script_text || '');

function progressHTML(job, detailed = false) {
  const value = progressOf(job);
  const message = job.progress_message || (job.status === 'done' ? '편집 완료' : job.status === 'waiting' ? '시작 전' : statusNames[job.status]);
  return `<div class="progress-widget ${detailed ? 'progress-detail' : ''}" data-progress-widget>
    <div class="progress-meta"><span data-progress-message>${escapeHTML(message)}</span><strong data-progress-number>${value}%</strong></div>
    <div class="progress-rail" role="progressbar" aria-label="${escapeHTML(job.name)} 편집 진행률" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${value}">
      <span class="progress-fill ${job.status === 'done' ? 'is-done' : ''}" style="transform:scaleX(${value / 100})"></span>
    </div>
  </div>`;
}

function syncProgressWidget(widget, job) {
  if (!widget) return;
  const value = progressOf(job);
  widget.querySelector('[data-progress-number]').textContent = `${value}%`;
  widget.querySelector('[data-progress-message]').textContent = job.progress_message || statusNames[job.status] || '';
  const rail = widget.querySelector('.progress-rail');
  rail.setAttribute('aria-valuenow', value);
  const fill = widget.querySelector('.progress-fill');
  fill.style.transform = `scaleX(${value / 100})`;
  fill.classList.toggle('is-done', job.status === 'done');
}

async function api(path, options = {}) {
  const init = {...options};
  if (init.body && !(init.body instanceof File)) {
    init.headers = {'Content-Type': 'application/json', ...(init.headers || {})};
    init.body = JSON.stringify(init.body);
  }
  const response = await fetch(path, init);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `요청 실패 (${response.status})`);
  return data;
}

function toast(message, bad = false) {
  const element = $('#toast');
  element.textContent = message;
  element.classList.toggle('is-error', bad);
  element.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove('show'), 3500);
}

function filesOf(job, kind) { return job.files.filter(file => file.kind === kind); }
function summary(job, kind) {
  const files = filesOf(job, kind);
  return files.length ? files.map(file => file.name).join(', ') : '없음';
}
function extraSummary(job) {
  const parts = [];
  if ((job.script_text || '').trim()) parts.push('직접 대본');
  if (filesOf(job, 'script').length) parts.push('대본 파일');
  if (filesOf(job, 'music').length) parts.push('배경음');
  if (filesOf(job, 'outro').length) parts.push('엔딩 이미지');
  return parts.join(' · ') || '없음';
}

function renderTable() {
  const visibleJobs = state.jobs.filter(job => showCompleted || job.status !== 'done');
  const visibleIds = new Set(visibleJobs.map(job => job.id));
  for (const id of checked) if (!visibleIds.has(id)) checked.delete(id);
  if (currentId && !visibleIds.has(currentId)) currentId = null;
  $('#jobCount').textContent = showCompleted ? state.jobs.length : `${visibleJobs.length} / 전체 ${state.jobs.length}`;
  $('#completedCount').textContent = state.jobs.filter(job => job.status === 'done').length;
  $('#emptyJobs').hidden = visibleJobs.length > 0;
  $('#emptyJobs').textContent = state.jobs.length ? '완료된 작업을 숨겼습니다. 완료 작업 표시를 켜면 다시 볼 수 있습니다.' : '아직 작업이 없습니다. 영상 파일을 선택하거나 끌어다 놓으세요.';
  const signature = JSON.stringify(visibleJobs.map(job => [
    job.id, job.name, job.files, job.script_text, job.status, job.result, job.completed_at,
  ])) + currentId + JSON.stringify([...checked]);
  if (signature !== tableSignature) {
    jobsBody.innerHTML = visibleJobs.map(job => `
    <tr class="job-row ${job.id === currentId ? 'active' : ''}" data-id="${job.id}">
      <td><input type="checkbox" aria-label="${escapeHTML(job.name)} 선택" data-check="${job.id}" ${checked.has(job.id) ? 'checked' : ''}></td>
      <td><div class="job-title" title="${escapeHTML(job.name)}">${escapeHTML(job.name)}</div></td>
      <td><div class="file-summary ${filesOf(job, 'video').length ? '' : 'muted'}" title="${escapeHTML(summary(job, 'video'))}">${escapeHTML(summary(job, 'video'))}</div></td>
      <td><div class="file-summary ${extraSummary(job) === '없음' ? 'muted' : ''}" title="${escapeHTML(extraSummary(job))}">${escapeHTML(extraSummary(job))}</div></td>
      <td><span class="status ${job.status}"><span class="dot"></span>${statusNames[job.status] || job.status}</span>${progressHTML(job)}${job.completed_at ? `<time class="completed-time" datetime="${escapeHTML(job.completed_at)}">완료 ${escapeHTML(completeTime(job.completed_at))}</time>` : ''}</td>
      <td>${job.status === 'done' ? `<button type="button" class="row-result" data-open="${job.id}">영상 열기</button>` : '<span class="muted">—</span>'}</td>
    </tr>`).join('');
    tableSignature = signature;
  } else {
    for (const job of state.jobs) {
      const row = [...jobsBody.querySelectorAll('tr[data-id]')].find(item => item.dataset.id === job.id);
      if (row) syncProgressWidget(row.querySelector('[data-progress-widget]'), job);
    }
  }
  $('#selectedCount').textContent = checked.size;
  $('#runSelected').disabled = checked.size === 0;
}

function fileCards(job, kind) {
  const list = filesOf(job, kind);
  if (!list.length) return '<p class="help">첨부된 파일이 없습니다.</p>';
  const locked = ['queued', 'editing'].includes(job.status);
  return `<ul class="file-list">${list.map(file => `<li class="file-item">
    <div><span class="file-name">${escapeHTML(file.name)}</span><small>${bytes(file.size)} · SHA256 ${file.sha256.slice(0, 8)}</small></div>
    <div class="file-actions"><button type="button" data-replace="${file.id}" data-kind="${file.kind}" ${locked ? 'disabled' : ''}>교체</button><button type="button" data-remove="${file.id}" ${locked ? 'disabled' : ''}>제거</button></div>
  </li>`).join('')}</ul>`;
}

function updateDetailLive(job) {
  const badge = detailPanel.querySelector('.detail-top .status');
  if (badge) {
    badge.className = `status ${job.status}`;
    badge.innerHTML = `<span class="dot"></span>${statusNames[job.status] || job.status}`;
  }
  syncProgressWidget(detailPanel.querySelector('[data-progress-widget]'), job);
  const completed = detailPanel.querySelector('[data-completed-time]');
  if (completed) {
    completed.hidden = !job.completed_at;
    completed.dateTime = job.completed_at || '';
    completed.textContent = job.completed_at ? `완료 시각 ${completeTime(job.completed_at)}` : '';
  }
}

function renderDetail() {
  const job = state.jobs.find(item => item.id === currentId);
  if (!job) {
    detailSignature = '';
    detailStructureSignature = '';
    detailPanel.dataset.jobId = '';
    detailPanel.innerHTML = '<div class="empty-detail"><span class="empty-symbol">▦</span><h2>작업을 선택하세요</h2><p>파일 첨부, 실행 방식, 결과를 여기서 확인합니다.</p></div>';
    return;
  }
  const signature = JSON.stringify(job) + JSON.stringify([
    state.recent_narration, state.default_script, state.voice_speed,
  ]);
  const structureSignature = JSON.stringify([
    job.id, job.name, job.mode, job.motion_titles, job.script_text,
    job.files, job.status, job.result, job.error, job.missing,
    job.completed_at, state.recent_narration, state.default_script, state.voice_speed,
  ]);
  if (signature === detailSignature) return;
  const active = document.activeElement;
  const editing = detailPanel.dataset.jobId === job.id && detailPanel.contains(active)
    && active.matches('#jobName, #scriptText');
  if (editing && structureSignature === detailStructureSignature) {
    detailSignature = signature;
    updateDetailLive(job);
    return;
  }
  const focusState = editing ? {
    id: active.id, start: active.selectionStart, end: active.selectionEnd,
    scrollTop: active.scrollTop,
  } : null;
  detailSignature = signature;
  detailStructureSignature = structureSignature;
  detailPanel.dataset.jobId = job.id;
  const locked = ['queued', 'editing'].includes(job.status);
  const missing = job.missing.length;
  const draft = scriptDraft(job);
  const scriptChanged = draft !== (job.script_text || '');
  const modeHelp = job.mode === 'recent'
    ? `최근 생성된 음성을 재사용합니다. ${state.recent_narration ? escapeHTML(state.recent_narration.split(/[\\/]/).pop()) : '기존 음성이 없습니다.'} 직접 대본을 저장하거나 파일을 첨부하면 대본으로 생성으로 바뀝니다.`
    : `직접 입력한 대본을 우선 사용합니다. 비워 두면 첨부 파일, 그다음 프로젝트 기본 대본을 사용합니다. ${state.default_script ? '기본 대본 있음' : '기본 대본 없음'}`;
  detailPanel.innerHTML = `
    <div class="detail-top"><div><p class="section-kicker">파일과 설정</p><h2>작업 상세</h2><p>ID ${job.id}</p></div><span class="status ${job.status}"><span class="dot"></span>${statusNames[job.status]}</span></div>
    ${progressHTML(job, true)}
    <time class="detail-completed" data-completed-time datetime="${escapeHTML(job.completed_at || '')}" ${job.completed_at ? '' : 'hidden'}>${job.completed_at ? `완료 시각 ${escapeHTML(completeTime(job.completed_at))}` : ''}</time>
    ${job.status === 'done' ? `<section class="detail-section result-section"><h3>완성 영상</h3><video class="result-preview" controls playsinline preload="metadata" poster="/api/jobs/${job.id}/poster" src="/api/jobs/${job.id}/video"></video><p class="result-path">${escapeHTML(job.result)}</p></section>` : ''}
    <label class="field-label" for="jobName">작업 이름</label><input id="jobName" class="text-field" type="text" maxlength="120" value="${escapeHTML(job.name)}" ${locked ? 'disabled' : ''}>
    <label class="field-label" for="narrationMode">음성 사용 방식</label><select id="narrationMode" class="select-field" ${locked ? 'disabled' : ''}><option value="recent" ${job.mode === 'recent' ? 'selected' : ''}>최근 생성 나레이션 사용</option><option value="script" ${job.mode === 'script' ? 'selected' : ''}>대본으로 나레이션 생성</option></select>
    <p class="help">${modeHelp}</p>
    <label class="inline-check"><input id="motionTitles" type="checkbox" ${job.motion_titles ? 'checked' : ''} ${locked ? 'disabled' : ''}> 상단 소제목·훅 표시</label>
    <p class="help voice-note">기본 음성 속도 ${state.voice_speed || '—'}배 · 하단 발화 자막 자동 동기화</p>
    <section class="detail-section"><h3>원본 영상 · 필수</h3><div id="detailDrop" class="drop-zone detail-drop" tabindex="0" role="button"><strong>이 작업에 영상을 끌어다 놓기</strong>또는 클릭해 여러 파일 선택</div>${fileCards(job, 'video')}</section>
    <section class="detail-section script-section" data-drop-kind="script">
      <h3>대본 입력 · 선택</h3>
      <label class="field-label compact" for="scriptText">직접 붙여넣기</label>
      <textarea id="scriptText" class="script-text" maxlength="12000" spellcheck="false" placeholder="여기에 대본을 붙여넣으세요.\n\n### 오프닝\n> 훅: 상단에 보일 문구\n내레이션으로 읽을 문장" ${locked ? 'disabled' : ''}>${escapeHTML(draft)}</textarea>
      <div class="script-actions"><button type="button" class="button small secondary" data-save-script ${locked || !scriptChanged ? 'disabled' : ''}>대본 저장</button><span id="scriptSaveState" class="help" aria-live="polite">${scriptChanged ? '저장하지 않은 변경 사항' : draft.trim() ? '저장됨 · 직접 대본 우선 사용' : '입력 대본 없음'}</span><span id="scriptCount" class="char-count">${draft.length.toLocaleString('ko-KR')} / 12,000자</span></div>
      <p class="help">저장한 대본은 등록된 윤소연 원장 목소리로 읽습니다. <code>&gt; 훅: 문구</code>는 상단에만 표시됩니다.</p>
      <div class="attachment-row"><button type="button" class="button small ghost" data-add-script ${locked ? 'disabled' : ''}>대본.md 첨부</button><span>직접 대본을 비우면 사용 · 이 영역에 끌어다 놓기</span></div>
      ${fileCards(job, 'script')}
    </section>
    <section class="detail-section" data-drop-kind="music"><h3>배경음 · 선택</h3><div class="attachment-row"><button type="button" class="button small ghost" data-add-music ${locked ? 'disabled' : ''}>배경음 파일 첨부</button><span>MP3 · WAV · M4A · AAC · OGG</span></div><p class="help">이 영역에 끌어다 놓을 수 있습니다. 목소리가 잘 들리도록 낮은 음량으로 영상 길이에 맞춰 넣습니다.</p>${fileCards(job, 'music')}</section>
    <section class="detail-section" data-drop-kind="outro"><h3>마지막 화면 이미지 · 선택</h3><div class="attachment-row"><button type="button" class="button small ghost" data-add-outro ${locked ? 'disabled' : ''}>SVG 또는 이미지 첨부</button><span>SVG · PNG · JPG · WEBP</span></div><p class="help">이 영역에 끌어다 놓을 수 있습니다. 투명 배경 PNG나 SVG 로고를 권장합니다. SVG는 2MB 이하로 만들고 외부 이미지·폰트 참조 없이 저장하세요. 변환에는 Chrome 또는 Edge가 필요합니다. 첨부가 없으면 로고 폴더의 이미지를 찾고, 그것도 없으면 COSMICO 텍스트로 마무리합니다.</p>${fileCards(job, 'outro')}</section>
    ${missing ? `<p class="notice warn">필요한 파일: ${escapeHTML(job.missing.join(', '))}</p>` : `<p class="notice ready">${job.status === 'done' ? '편집 완료' : job.status === 'editing' ? '편집 중입니다' : job.status === 'queued' ? '편집 순서를 기다리고 있습니다' : '편집 준비 완료'}</p>`}
    ${job.error ? `<p class="notice fail">실패 원인: ${escapeHTML(job.error)}</p>` : ''}
    <div class="detail-actions">${job.status === 'failed' ? '<button type="button" class="button primary" data-retry>이 작업 다시 실행</button>' : ''}${job.status === 'done' ? '<button type="button" class="button primary" data-open-detail>영상 열기</button>' : ''}</div>
    `;
  if (focusState) {
    const restored = detailPanel.querySelector(`#${focusState.id}`);
    if (restored && !restored.disabled) {
      restored.focus({preventScroll:true});
      restored.setSelectionRange(focusState.start, focusState.end);
      restored.scrollTop = focusState.scrollTop;
    }
  }
}

async function refresh() {
  if (polling) return;
  polling = true;
  try {
    state = await api('/api/state');
    for (const id of [...checked]) if (!state.jobs.some(job => job.id === id)) checked.delete(id);
    $('#outputPath').textContent = `결과 저장: ${state.output_folder}`;
    renderTable();
    renderDetail();
  } catch (error) { toast(error.message, true); }
  finally { polling = false; }
}

async function uploadFile(jobId, kind, file, replaceId = null) {
  const query = new URLSearchParams({kind, name: file.name});
  if (replaceId) query.set('replace', replaceId);
  const response = await fetch(`/api/jobs/${jobId}/files?${query}`, {method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:file});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${file.name} 업로드 실패`);
}

async function saveDraft(jobId) {
  if (!scriptDrafts.has(jobId)) return false;
  const text = scriptDrafts.get(jobId);
  const job = state.jobs.find(item => item.id === jobId);
  if (text === (job?.script_text || '')) {
    scriptDrafts.delete(jobId);
    return false;
  }
  if (text.length > 12000) throw new Error('대본은 12,000자 이내로 입력하세요.');
  await api(`/api/jobs/${jobId}`, {method:'PATCH', body:{script_text:text}});
  scriptDrafts.delete(jobId);
  return true;
}

async function addVideos(fileList, jobId = null) {
  const files = [...fileList];
  if (!files.length) throw new Error('MP4, MOV, MKV, AVI 영상 파일을 선택하세요.');
  const unsupported = files.filter(file => !/\.(mp4|mov|mkv|avi)$/i.test(file.name));
  if (unsupported.length) throw new Error(`지원하지 않는 영상 형식: ${unsupported.map(file => file.name).join(', ')}`);
  if (jobId) {
    for (const file of files) await uploadFile(jobId, 'video', file);
  } else if ($('#groupVideos').checked) {
    const name = files.length > 1 ? `${files[0].name.replace(/\.[^.]+$/, '')} 외 ${files.length - 1}개` : files[0].name.replace(/\.[^.]+$/, '');
    const created = await api('/api/jobs', {method:'POST', body:{name}});
    currentId = created.job.id;
    for (const file of files) await uploadFile(currentId, 'video', file);
  } else {
    for (const file of files) {
      const created = await api('/api/jobs', {method:'POST', body:{name:file.name.replace(/\.[^.]+$/, '')}});
      currentId = created.job.id;
      await uploadFile(currentId, 'video', file);
    }
  }
  detailSignature = '';
  await refresh();
  toast(`${files.length}개 영상 파일을 추가했습니다.`);
}

function dropSetup(element, onFiles) {
  element.addEventListener('dragover', event => {
    if (!event.dataTransfer.types.includes('Files')) return;
    event.preventDefault(); event.stopPropagation(); element.classList.add('dragging');
  });
  element.addEventListener('dragleave', event => {event.preventDefault(); event.stopPropagation(); element.classList.remove('dragging');});
  element.addEventListener('drop', event => {
    if (!event.dataTransfer.files.length) return;
    event.preventDefault(); event.stopPropagation(); element.classList.remove('dragging');
    onFiles(event.dataTransfer.files, event);
  });
}

async function addSingle(kind, file) {
  if (!file) return;
  if (!fileTypes[kind].split(',').some(extension => file.name.toLowerCase().endsWith(extension))) {
    throw new Error(`${kind === 'music' ? '배경음' : kind === 'outro' ? '마지막 화면 이미지' : '대본'} 파일 형식을 확인하세요.`);
  }
  const job = state.jobs.find(item => item.id === currentId);
  const current = job && filesOf(job, kind)[0];
  await uploadFile(currentId, kind, file, current?.id || null);
  detailSignature = '';
  await refresh();
  toast(`${kind === 'music' ? '배경음' : kind === 'outro' ? '마지막 화면 이미지' : '대본'} 파일을 첨부했습니다.`);
}

$('#showCompleted').checked = showCompleted;
$('#showCompleted').onchange = event => {
  showCompleted = event.target.checked;
  try { localStorage.setItem('reels.showCompleted', String(showCompleted)); } catch {}
  renderTable();
  renderDetail();
};

$('#addVideos').onclick = () => $('#boardVideoInput').click();
$('#boardVideoInput').onchange = async event => {try {await addVideos(event.target.files);} catch(error) {toast(error.message, true);} event.target.value='';};
$('#detailVideoInput').onchange = async event => {try {await addVideos(event.target.files, currentId);} catch(error) {toast(error.message, true);} event.target.value='';};
$('#scriptInput').onchange = async event => {try {await addSingle('script', event.target.files[0]);} catch(error) {toast(error.message, true);} event.target.value='';};
$('#musicInput').onchange = async event => {try {await addSingle('music', event.target.files[0]);} catch(error) {toast(error.message, true);} event.target.value='';};
$('#outroInput').onchange = async event => {try {await addSingle('outro', event.target.files[0]);} catch(error) {toast(error.message, true);} event.target.value='';};
$('#replaceInput').onchange = async event => {try {if (replacement && event.target.files[0]) {await uploadFile(currentId, replacement.kind, event.target.files[0], replacement.id); detailSignature=''; await refresh(); toast('파일을 교체했습니다.');}} catch(error) {toast(error.message, true);} replacement=null; event.target.value='';};
$('#boardDrop').onclick = () => $('#boardVideoInput').click();
$('#boardDrop').onkeydown = event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); $('#boardVideoInput').click();}};
dropSetup($('#boardDrop'), files => addVideos(files).catch(error => toast(error.message, true)));
dropSetup(detailPanel, (files, event) => {
  if (!currentId) return;
  const kind = event.target.closest('[data-drop-kind]')?.dataset.dropKind || 'video';
  const task = kind === 'video' ? addVideos(files, currentId) : addSingle(kind, files[0]);
  task.catch(error => toast(error.message, true));
});

jobsBody.addEventListener('click', async event => {
  const open = event.target.closest('[data-open]');
  if (open) {try {await api(`/api/jobs/${open.dataset.open}/open`, {method:'POST'});} catch(error) {toast(error.message, true);} return;}
  if (event.target.matches('[data-check]')) return;
  const row = event.target.closest('tr[data-id]');
  if (row) {currentId = row.dataset.id; detailSignature=''; renderTable(); renderDetail();}
});
jobsBody.addEventListener('change', event => {
  const id = event.target.dataset.check;
  if (!id) return;
  if (event.target.checked) checked.add(id); else checked.delete(id);
  $('#selectedCount').textContent = checked.size;
  $('#runSelected').disabled = checked.size === 0;
});

detailPanel.addEventListener('click', async event => {
  try {
    if (event.target.closest('#detailDrop')) {$('#detailVideoInput').click(); return;}
    if (event.target.closest('[data-add-script]')) {$('#scriptInput').click(); return;}
    if (event.target.closest('[data-add-music]')) {$('#musicInput').click(); return;}
    if (event.target.closest('[data-add-outro]')) {$('#outroInput').click(); return;}
    if (event.target.closest('[data-save-script]')) {
      const text = $('#scriptText').value;
      scriptDrafts.set(currentId, text);
      await saveDraft(currentId);
      detailSignature = '';
      await refresh();
      toast(text.trim() ? '직접 입력한 대본을 저장했습니다.' : '직접 입력한 대본을 비웠습니다.');
      return;
    }
    const replace = event.target.closest('[data-replace]');
    if (replace) {replacement={id:replace.dataset.replace,kind:replace.dataset.kind}; const input=$('#replaceInput'); input.accept=fileTypes[replacement.kind] || fileTypes.video; input.click(); return;}
    const remove = event.target.closest('[data-remove]');
    if (remove) {await api(`/api/jobs/${currentId}/files/${remove.dataset.remove}`, {method:'DELETE'}); detailSignature=''; await refresh(); toast('첨부 목록에서 제거했습니다. PC의 원본은 그대로 있습니다.'); return;}
    if (event.target.closest('[data-retry]')) {await saveDraft(currentId); await api(`/api/jobs/${currentId}/queue`, {method:'POST'}); detailSignature=''; await refresh(); toast('이 작업을 다시 대기열에 넣었습니다.'); return;}
    if (event.target.closest('[data-open-detail]')) await api(`/api/jobs/${currentId}/open`, {method:'POST'});
  } catch(error) {toast(error.message, true);}
});
detailPanel.addEventListener('keydown', event => {if (event.target.id==='detailDrop' && (event.key==='Enter'||event.key===' ')) {event.preventDefault(); $('#detailVideoInput').click();}});
detailPanel.addEventListener('input', event => {
  if (event.target.id !== 'scriptText') return;
  const job = state.jobs.find(item => item.id === currentId);
  if (!job) return;
  const value = event.target.value;
  scriptDrafts.set(currentId, value);
  const changed = value !== (job.script_text || '');
  const save = detailPanel.querySelector('[data-save-script]');
  if (save) save.disabled = !changed;
  const note = $('#scriptSaveState');
  if (note) note.textContent = changed ? '저장하지 않은 변경 사항' : value.trim() ? '저장됨 · 직접 대본 우선 사용' : '입력 대본 없음';
  const count = $('#scriptCount');
  if (count) count.textContent = `${value.length.toLocaleString('ko-KR')} / 12,000자`;
});
detailPanel.addEventListener('focusout', event => {
  if (event.target.matches('#jobName, #scriptText')) setTimeout(() => {
    if (detailPanel.contains(document.activeElement)
        && document.activeElement.id === event.target.id) return;
    detailSignature = '';
    renderDetail();
  }, 0);
});
detailPanel.addEventListener('change', async event => {
  const values = event.target.id==='jobName'?{name:event.target.value}:event.target.id==='narrationMode'?{mode:event.target.value}:event.target.id==='motionTitles'?{motion_titles:event.target.checked}:null;
  if (!values) return;
  try {await api(`/api/jobs/${currentId}`, {method:'PATCH',body:values}); detailSignature=''; await refresh();} catch(error) {toast(error.message,true);}
});

$('#runSelected').onclick = async () => {
  try {
    const ids=[...checked];
    for (const id of ids) await saveDraft(id);
    await api('/api/jobs/queue', {method:'POST',body:{ids}});
    checked.clear();
    detailSignature='';
    await refresh();
    toast(`${ids.length}개 작업을 순서대로 편집합니다.`);
  } catch(error) {toast(error.message,true);}
};
$('#openFolder').onclick = async () => {
  try {await api('/api/open-folder', {method:'POST'}); toast('결과 폴더를 열었습니다.');}
  catch (error) {toast(`결과 폴더를 열 수 없습니다: ${error.message}`, true);}
};
refresh();
setInterval(refresh, 1500);
