/* Trang Quy trình: kéo thả các khối (Ý tưởng, AI viết kịch bản, Vẽ ảnh, Giọng đọc, Dựng video, Thumbnail, Xuất...) rồi nối dây thành dây chuyền.
 * Bấm Chạy: từng khối sáng lên, xong hiện kết quả ngay trên khối (ảnh, video, thumbnail). Câu chuyện tạo ra mở được ở Kể chuyện để sửa tay.
 * Địa chỉ: #/flow | #/flow/<mã> */
import { S, api, busy, confirmDialog, debounce, el, emptyState, enc, fillVoiceSelect, fmtAgo, fmtDur, icon, showError, toast, uploadFile, videoModal, voiceHooks } from './core.js';
import { openMyVoices } from './myvoices.js';

const NODE_W = 236;
const HEAD_H = 40;
const PORT_H = 26;
const KIND_COLOR = { text: '#8FB3FF', images: '#5CD6A9', story: '#FFB224', video: '#FF7A7A', image: '#C99BFF' };
const KIND_LABEL = { text: 'Chữ', images: 'Ảnh', story: 'Câu chuyện', video: 'Video', image: 'Thumbnail' };
const STATE_LABEL = { waiting: 'Chờ', running: 'Đang chạy', done: 'Xong', error: 'Lỗi', stopped: 'Đã dừng' };
let REG = null;

async function registry() {
  if (!REG) REG = await api('GET', '/api/workflow/nodes');
  return REG;
}

export async function viewWorkflow(main, alive, arg) {
  const reg = await registry();
  if (!alive()) return null;
  if (!arg) return listPage(main, alive, reg);
  return editorPage(main, alive, reg, arg);
}

// ------------------------------------------------------------------ danh sách
async function listPage(main, alive, reg) {
  main.classList.add('view-pad');
  const { items } = await api('GET', '/api/workflows');
  if (!alive()) return null;
  const create = (tid, btn) => busy(btn, async () => {
    const w = await api('POST', '/api/workflows', { template: tid });
    location.hash = `#/flow/${enc(w.id)}`;
  });
  const tplCards = reg.templates.map((t) => {
    const b = el('button', { class: 'wf-tpl', onclick: () => create(t.id, b) },
      el('div', { class: 'wf-tpl-chain' }, t.id === 'blank' ? icon('plus') : chainIcons(templateChain(t.id, reg))),
      el('b', { text: t.name }), el('span', { class: 'dim small', text: t.desc }));
    return b;
  });
  const list = items.length ? el('div', { class: 'wf-list' }, items.map((w) => {
    const del = el('button', { class: 'btn btn-xs btn-icon btn-ghost', title: 'Xóa quy trình', 'aria-label': 'Xóa quy trình', onclick: (e) => { e.preventDefault(); busy(del, async () => {
      if (!await confirmDialog('Xóa quy trình?', `"${w.name}" sẽ bị xóa. Câu chuyện và video đã tạo vẫn còn.`, { okText: 'Xóa', danger: true })) return;
      await api('DELETE', `/api/workflows/${enc(w.id)}`);
      location.reload();
    }); } }, icon('trash'));
    return el('a', { class: 'wf-card', href: `#/flow/${enc(w.id)}` },
      el('div', { class: 'wf-card-chain' }, chainIcons(w.types, reg)),
      el('div', { class: 'wf-card-t' }, el('b', { text: w.name }), el('span', { class: 'dim small', text: `${w.nodes} khối · sửa ${fmtAgo(w.updated)}` + (w.state ? ` · lần chạy cuối: ${STATE_LABEL[w.state] || w.state}` : '') })),
      del);
  })) : null;
  main.append(
    el('div', { class: 'page-head' }, el('div', { class: 'page-head-text' },
      el('div', { class: 'eyebrow', text: 'Quy trình' }),
      el('h1', { text: 'Kéo thả thành dây chuyền làm video' }),
      el('p', { text: 'Ghép các khối: ý tưởng, AI viết kịch bản, vẽ ảnh, giọng đọc, nhạc, dựng video, thumbnail, xuất bộ đăng bài. Bấm Chạy một lần là ra video kèm thumbnail. Chạy lại không tốn thêm: phần đã làm được dùng lại.' }))),
    el('h3', { class: 'ed-head', text: 'Bắt đầu từ mẫu' }),
    el('div', { class: 'wf-tpls' }, tplCards),
    list ? el('h3', { class: 'ed-head', text: 'Quy trình của tôi' }) : '',
    list || '');
  return null;
}

function templateChain(tid, reg) {
  const map = { ai_story: ['idea', 'ai_write', 'char_refs', 'draw', 'voice', 'music', 'render', 'thumbnail', 'export'], my_images: ['images', 'split', 'voice', 'music', 'render', 'thumbnail', 'export'],
    script_ai_images: ['script', 'ai_write', 'draw', 'voice', 'render', 'thumbnail', 'export'] };
  return map[tid] || [];
}
function chainIcons(types) {
  const reg = REG;
  return types.flatMap((t, i) => [i ? el('i', { class: 'wf-chain-arrow' }) : null, el('span', { class: 'wf-chain-ic', title: reg.nodes[t] ? reg.nodes[t].label : t }, icon(reg.nodes[t] ? reg.nodes[t].icon : 'square'))]).filter(Boolean);
}

// ------------------------------------------------------------------ trình sửa
async function editorPage(main, alive, reg, wid) {
  let w = await api('GET', `/api/workflows/${enc(wid)}`);
  if (!alive()) return null;
  main.classList.add('view-flow');
  const N = reg.nodes;
  let view = { x: 0, y: 0, z: 1 };
  let sel = null;      // { kind: 'node'|'edge', id }
  let run = w.run || null;
  let problems = w.problems || {};
  const cleanups = [];

  // ---------- lưu
  let saving = Promise.resolve();
  const saveNow = () => {
    saving = saving.then(() => api('PUT', `/api/workflows/${enc(wid)}`, { name: w.name, nodes: w.nodes, edges: w.edges })
      .then((r) => { problems = r.problems || {}; paintProblems(); })
      .catch((e) => toast('Chưa lưu được: ' + e.message, 'error')));
    return saving;
  };
  const save = debounce(saveNow, 500);

  // ---------- khung vẽ
  const world = el('div', { class: 'wf-world' });
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.classList.add('wf-wires');
  world.append(svg);
  const canvas = el('div', { class: 'wf-canvas' }, world);
  const applyView = () => {
    world.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.z})`;
    canvas.style.backgroundPosition = `${view.x}px ${view.y}px`;
    canvas.style.backgroundSize = `${24 * view.z}px ${24 * view.z}px`;
  };
  const toWorld = (cx, cy) => { const r = canvas.getBoundingClientRect(); return [(cx - r.left - view.x) / view.z, (cy - r.top - view.y) / view.z]; };
  function fitView() {
    if (!w.nodes.length) { view = { x: 40, y: 40, z: 1 }; applyView(); return; }
    const r = canvas.getBoundingClientRect();
    const xs = w.nodes.map((n) => n.x), ys = w.nodes.map((n) => n.y);
    const x0 = Math.min(...xs) - 40, y0 = Math.min(...ys) - 40;
    const x1 = Math.max(...xs) + NODE_W + 40, y1 = Math.max(...ys) + 300;
    // không thu nhỏ quá 0,7: nhỏ hơn thì chữ trong khối không đọc được; phần thừa kéo nền để xem
    const z = Math.max(0.7, Math.min(1, Math.min(r.width / (x1 - x0), r.height / (y1 - y0))));
    view = { z, x: Math.max(10, (r.width - (x1 - x0) * z) / 2) - x0 * z, y: Math.max(10, (r.height - (y1 - y0) * z) / 2) - y0 * z };
    applyView();
  }

  // ---------- khối
  const nodeEls = new Map();
  const portPos = (n, side, i) => [n.x + (side === 'out' ? NODE_W : 0), n.y + HEAD_H + 14 + i * PORT_H];
  function nodeEl(n) {
    const spec = N[n.type];
    const st = run && run.nodes ? run.nodes[n.id] : null;
    const ins = spec.inputs.map(([name, kind, req], i) => el('div', { class: 'wf-port wf-in', 'data-node': n.id, 'data-i': i, 'data-kind': kind, title: `${KIND_LABEL[kind]}${req ? '' : ' (không bắt buộc)'}` },
      el('i', { class: 'wf-dot', style: { background: KIND_COLOR[kind] } }), el('span', { text: KIND_LABEL[kind] + (req ? '' : ' (tùy chọn)') })));
    const outs = spec.outputs.map(([name, kind], i) => el('div', { class: 'wf-port wf-out', 'data-node': n.id, 'data-i': i, 'data-kind': kind, title: `Kéo từ đây để nối ${KIND_LABEL[kind]}` },
      el('span', { text: KIND_LABEL[kind] }), el('i', { class: 'wf-dot', style: { background: KIND_COLOR[kind] } })));
    const rows = Math.max(ins.length, outs.length);
    const portBox = el('div', { class: 'wf-ports', style: { height: `${rows * PORT_H + 4}px` } }, el('div', { class: 'wf-ins' }, ins), el('div', { class: 'wf-outs' }, outs));
    const del = el('button', { class: 'wf-x', title: 'Xóa khối', 'aria-label': 'Xóa khối', onclick: (e) => { e.stopPropagation(); removeNode(n.id); } }, icon('x'));
    const body = el('div', { class: 'wf-body' }, nodeBody(n, st));
    const box = el('div', {
      class: 'wf-node' + (spec.paid ? ' paid' : '') + (st ? ` st-${st.state}` : '') + (sel && sel.kind === 'node' && sel.id === n.id ? ' sel' : '') + (problems[n.id] ? ' warn' : ''),
      'data-id': n.id, style: { left: `${n.x}px`, top: `${n.y}px`, width: `${NODE_W}px` },
    }, el('div', { class: 'wf-head' }, icon(spec.icon), el('b', { text: spec.label }), spec.paid ? el('span', { class: 'wf-paid', title: 'Có tính phí theo nguồn ảnh', text: '$' }) : '', el('span', { class: 'grow' }), del),
    portBox, body);
    return box;
  }
  function nodeBody(n, st) {
    const parts = [];
    const p = n.params;
    const sum = summary(n);
    if (sum) parts.push(el('div', { class: 'wf-sum', text: sum }));
    if (problems[n.id] && !(st && st.state === 'error')) parts.push(el('div', { class: 'wf-prob' }, icon('alert'), el('span', { text: problems[n.id] })));
    if (st && st.state !== 'waiting') {
      parts.push(el('div', { class: `wf-st wf-st-${st.state}` }, el('span', { class: 'wf-st-dot' }), el('span', { text: st.message || STATE_LABEL[st.state] })));
      if (st.state === 'running') parts.push(el('div', { class: 'wf-bar' }, el('i', { class: st.progress == null ? 'indet' : '', style: st.progress == null ? {} : { width: `${Math.round(st.progress * 100)}%` } })));
    }
    const pv = st && st.preview;
    if (pv) {
      if (pv.images && pv.images.length) parts.push(el('div', { class: 'wf-strip' }, pv.images.slice(0, 6).map((u) => el('img', { src: u, alt: '', loading: 'lazy' }))));
      if (pv.title) parts.push(el('div', { class: 'wf-pv-t' }, el('b', { text: pv.title }), el('span', { class: 'dim small', text: `${pv.scenes} cảnh` + (pv.characters && pv.characters.length ? ` · ${pv.characters.join(', ')}` : '') + (pv.reused ? ' · dùng lại' : '') })));
      if (pv.video) parts.push(el('button', { class: 'wf-video', onclick: (e) => { e.stopPropagation(); videoModal(pv.video, pv.name || 'Video'); } }, icon('play'), el('span', { text: `Xem video ${fmtDur(pv.duration || 0)}` })));
      if (pv.image) parts.push(el('img', { class: 'wf-thumb', src: pv.image, alt: 'Thumbnail' }));
      if (pv.seconds) parts.push(el('div', { class: 'dim small', text: `Lời dẫn ${fmtDur(pv.seconds)}, ${pv.scenes} cảnh có lời` }));
      if (pv.music) parts.push(el('div', { class: 'dim small', text: pv.music }));
      if (pv.folder) parts.push(el('button', { class: 'btn btn-xs', onclick: (e) => { e.stopPropagation(); api('POST', `/api/workflows/${enc(wid)}/nodes/${enc(n.id)}/reveal`); } }, icon('folder'), 'Mở thư mục xuất'));
      if (pv.story) {
        const links = [el('a', { class: 'btn btn-xs btn-ghost', href: `#/story/${enc(pv.story)}`, onclick: (e) => e.stopPropagation() }, icon('edit'), 'Sửa ở Kể chuyện')];
        if (n.type === 'thumbnail') links.unshift(el('a', { class: 'btn btn-xs', href: `#/thumb/story/${enc(pv.story)}`, onclick: (e) => e.stopPropagation() }, icon('image'), 'Sửa thumbnail'));
        parts.push(el('div', { class: 'wf-links' }, links));
      }
    }
    return parts;
  }
  function summary(n) {
    const p = n.params;
    const opt = (key) => { const spec = N[n.type].params.find((x) => x.key === key); const o = spec && spec.options ? spec.options.find((x) => String(x[0]) === String(p[key])) : null; return o ? o[1] : ''; };
    switch (n.type) {
      case 'idea': return p.text ? `"${p.text.slice(0, 70)}${p.text.length > 70 ? '…' : ''}" · ${opt('seconds')}` : '';
      case 'script': return p.text ? `${p.text.length.toLocaleString('vi-VN')} ký tự` : '';
      case 'images': return p.files && p.files.length ? `${p.files.length} ảnh` : '';
      case 'ai_write': case 'split': return [opt('aspect'), opt('style')].filter(Boolean).join(' · ');
      case 'draw': case 'char_refs': return opt('provider');
      case 'voice': return [opt('engine'), p.voice ? voiceName(p.voice) : 'giọng mặc định', `${Number(p.speed || 1).toFixed(2)}x`].join(' · ');
      case 'music': return p.music ? `${p.music} · ${Math.round((p.volume || 0) * 100)}%` : 'Không nhạc';
      case 'render': return [opt('transition'), p.subs ? `phụ đề ${opt('subs')}` : 'không phụ đề', p.intro ? 'có mở đầu' : '', p.outro ? 'có kết thúc' : ''].filter(Boolean).join(' · ');
      case 'thumbnail': return [opt('aspect'), opt('style')].filter(Boolean).join(' · ');
      default: return '';
    }
  }
  const voiceName = (id) => {
    const mine = (S.voices.mine || []).find((v) => v.id === id);
    return mine ? mine.name : id;
  };

  function paintNodes() {
    for (const e of nodeEls.values()) e.remove();
    nodeEls.clear();
    for (const n of w.nodes) { const e = nodeEl(n); nodeEls.set(n.id, e); world.append(e); }
    paintWires();
  }
  function repaintNode(id) {
    const n = w.nodes.find((x) => x.id === id);
    const old = nodeEls.get(id);
    if (!n || !old) return;
    const e = nodeEl(n);
    old.replaceWith(e);
    nodeEls.set(id, e);
  }
  function paintProblems() { for (const n of w.nodes) repaintNode(n.id); paintWires(); paintRunBar(); }

  // ---------- dây
  const wirePath = (x1, y1, x2, y2) => { const d = Math.max(60, Math.abs(x2 - x1) * 0.5); return `M${x1},${y1} C${x1 + d},${y1} ${x2 - d},${y2} ${x2},${y2}`; };
  function paintWires(temp) {
    const parts = [];
    const byId = new Map(w.nodes.map((n) => [n.id, n]));
    for (const e of w.edges) {
      const a = byId.get(e.from), b = byId.get(e.to);
      if (!a || !b) continue;
      const [x1, y1] = portPos(a, 'out', e.out);
      const [x2, y2] = portPos(b, 'in', e.in);
      const kind = N[a.type].outputs[e.out][1];
      const on = sel && sel.kind === 'edge' && sel.id === e.id;
      const live = run && run.state === 'running' && run.nodes && run.nodes[a.id] && run.nodes[a.id].state === 'done' && run.nodes[b.id] && run.nodes[b.id].state === 'running';
      parts.push(`<path class="wf-hit" data-edge="${e.id}" d="${wirePath(x1, y1, x2, y2)}"/>`);
      parts.push(`<path class="wf-wire${on ? ' sel' : ''}${live ? ' live' : ''}" d="${wirePath(x1, y1, x2, y2)}" stroke="${KIND_COLOR[kind]}"/>`);
    }
    if (temp) parts.push(`<path class="wf-wire temp" d="${wirePath(...temp)}" stroke="${temp[4]}"/>`);
    svg.innerHTML = parts.join('');
  }

  // ---------- kéo thả: di chuyển khối, kéo nền, nối dây
  let drag = null;
  canvas.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const port = e.target.closest('.wf-out');
    const head = e.target.closest('.wf-head');
    const nodeBox = e.target.closest('.wf-node');
    const hit = e.target.closest('.wf-hit');
    if (e.target.closest('button, a, input, select, textarea, img.wf-thumb')) return;
    if (port) {
      const n = w.nodes.find((x) => x.id === port.dataset.node);
      drag = { mode: 'wire', from: n, out: +port.dataset.i, kind: port.dataset.kind };
      canvas.setPointerCapture(e.pointerId);
      canvas.classList.add('wiring', `wiring-${port.dataset.kind}`);
      e.preventDefault();
      return;
    }
    if (hit) { select({ kind: 'edge', id: hit.dataset.edge }); return; }
    if (nodeBox) {
      const n = w.nodes.find((x) => x.id === nodeBox.dataset.id);
      select({ kind: 'node', id: n.id });
      if (head || nodeBox) {
        const [wx, wy] = toWorld(e.clientX, e.clientY);
        drag = { mode: 'node', n, dx: wx - n.x, dy: wy - n.y, moved: false };
        canvas.setPointerCapture(e.pointerId);
      }
      return;
    }
    select(null);
    drag = { mode: 'pan', sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
    canvas.setPointerCapture(e.pointerId);
    canvas.classList.add('panning');
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    if (drag.mode === 'pan') { view.x = drag.vx + e.clientX - drag.sx; view.y = drag.vy + e.clientY - drag.sy; applyView(); return; }
    const [wx, wy] = toWorld(e.clientX, e.clientY);
    if (drag.mode === 'node') {
      drag.n.x = Math.round((wx - drag.dx) / 4) * 4;
      drag.n.y = Math.round((wy - drag.dy) / 4) * 4;
      drag.moved = true;
      const box = nodeEls.get(drag.n.id);
      box.style.left = `${drag.n.x}px`;
      box.style.top = `${drag.n.y}px`;
      paintWires();
    } else if (drag.mode === 'wire') {
      const [x1, y1] = portPos(drag.from, 'out', drag.out);
      paintWires([x1, y1, wx, wy, KIND_COLOR[drag.kind]]);
      document.querySelectorAll('.wf-in.target').forEach((x) => x.classList.remove('target'));
      const under = document.elementFromPoint(e.clientX, e.clientY);
      const pin = under && under.closest('.wf-in');
      if (pin && pin.dataset.kind === drag.kind && pin.dataset.node !== drag.from.id) pin.classList.add('target');
    }
  });
  canvas.addEventListener('pointerup', (e) => {
    if (!drag) return;
    const d = drag;
    drag = null;
    canvas.classList.remove('panning', 'wiring', ...[...canvas.classList].filter((c) => c.startsWith('wiring-')));
    if (d.mode === 'node' && d.moved) save();
    if (d.mode === 'wire') {
      document.querySelectorAll('.wf-in.target').forEach((x) => x.classList.remove('target'));
      const under = document.elementFromPoint(e.clientX, e.clientY);
      const pin = under && under.closest('.wf-in');
      if (pin && pin.dataset.node !== d.from.id) {
        if (pin.dataset.kind !== d.kind) toast(`Không nối được: khối này cần ${KIND_LABEL[pin.dataset.kind]}, dây đang mang ${KIND_LABEL[d.kind]}`, 'warn');
        else connect(d.from.id, d.out, pin.dataset.node, +pin.dataset.i);
      }
      paintWires();
    }
  });
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    const mx = e.clientX - r.left, my = e.clientY - r.top;
    const z = Math.max(0.3, Math.min(1.6, view.z * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    view.x = mx - (mx - view.x) * z / view.z;
    view.y = my - (my - view.y) * z / view.z;
    view.z = z;
    applyView();
  }, { passive: false });
  // thả khối từ bảng bên trái
  canvas.addEventListener('dragover', (e) => { if (e.dataTransfer.types.includes('text/x-wf-node')) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
  canvas.addEventListener('drop', (e) => {
    const type = e.dataTransfer.getData('text/x-wf-node');
    if (!type) return;
    e.preventDefault();
    const [x, y] = toWorld(e.clientX, e.clientY);
    addNode(type, x - NODE_W / 2, y - 20);
  });

  // mã ngẫu nhiên: khối mới không bao giờ trùng mã khối đã xóa (nếu trùng sẽ hiện kết quả chạy cũ của khối kia)
  function newNodeId() { let id; do { id = 'n' + Math.random().toString(36).slice(2, 8); } while (w.nodes.some((n) => n.id === id)); return id; }
  function addNode(type, x, y) {
    const spec = N[type];
    const params = Object.fromEntries(spec.params.map((p) => [p.key, JSON.parse(JSON.stringify(p.default))]));
    const n = { id: newNodeId(), type, x: Math.round(x), y: Math.round(y), params };
    w.nodes.push(n);
    // nối luôn với khối đang chọn nếu hợp kiểu dữ liệu: kéo thả liên tục thành dây chuyền
    const prev = sel && sel.kind === 'node' ? w.nodes.find((m) => m.id === sel.id) : null;
    if (prev) {
      const oi = N[prev.type].outputs.findIndex(([, k]) => spec.inputs.some(([, k2]) => k2 === k));
      if (oi >= 0) connect(prev.id, oi, n.id, spec.inputs.findIndex(([, k2]) => k2 === N[prev.type].outputs[oi][1]), true);
    }
    select({ kind: 'node', id: n.id });
    paintNodes();
    save();
  }
  function connect(from, out, to, inp, quiet = false) {
    w.edges = w.edges.filter((e) => !(e.to === to && e.in === inp));      // mỗi đầu vào một dây
    w.edges.push({ id: 'e' + Math.random().toString(36).slice(2, 8), from, out, to, in: inp });
    if (!quiet) { paintWires(); save(); }
  }
  function removeNode(id) {
    w.nodes = w.nodes.filter((n) => n.id !== id);
    w.edges = w.edges.filter((e) => e.from !== id && e.to !== id);
    if (sel && sel.id === id) sel = null;
    paintNodes();
    paintInspector();
    save();
  }
  function removeEdge(id) { w.edges = w.edges.filter((e) => e.id !== id); sel = null; paintWires(); paintInspector(); save(); }
  function select(s) {
    sel = s;
    document.querySelectorAll('.wf-node.sel').forEach((x) => x.classList.remove('sel'));
    if (s && s.kind === 'node' && nodeEls.get(s.id)) nodeEls.get(s.id).classList.add('sel');
    paintWires();
    paintInspector();
  }
  const keyHandler = (e) => {
    if (!main.isConnected) return;
    if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || '')) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && sel) { e.preventDefault(); if (sel.kind === 'node') removeNode(sel.id); else removeEdge(sel.id); }
  };
  document.addEventListener('keydown', keyHandler);
  cleanups.push(() => document.removeEventListener('keydown', keyHandler));

  // ---------- bảng khối bên trái
  const groups = {};
  for (const [type, spec] of Object.entries(N)) (groups[spec.group] = groups[spec.group] || []).push([type, spec]);
  const palette = el('aside', { class: 'wf-pal' }, el('p', { class: 'dim small', text: 'Kéo khối vào bàn làm việc, hoặc bấm để thêm nối tiếp khối đang chọn.' }),
    Object.entries(groups).map(([g, list]) => el('div', { class: 'wf-pal-g' }, el('span', { class: 'label', text: g }), list.map(([type, spec]) => el('div', {
      class: 'wf-pal-it' + (spec.paid ? ' paid' : ''), draggable: 'true', title: spec.help, tabindex: 0,
      ondragstart: (e) => { e.dataTransfer.setData('text/x-wf-node', type); e.dataTransfer.effectAllowed = 'copy'; },
      onclick: () => {
        const prev = sel && sel.kind === 'node' ? w.nodes.find((m) => m.id === sel.id) : null;
        const r = canvas.getBoundingClientRect();
        const [cx, cy] = toWorld(r.left + r.width / 2, r.top + r.height / 2);
        addNode(type, prev ? prev.x + NODE_W + 64 : cx - NODE_W / 2, prev ? prev.y : cy - 60);
      },
      onkeydown: (e) => { if (e.key === 'Enter') e.currentTarget.click(); },
    }, icon(spec.icon), el('span', { text: spec.label }), spec.paid ? el('i', { class: 'wf-paid', text: '$' }) : '')))));

  // ---------- bảng thiết lập bên phải
  const insp = el('aside', { class: 'wf-insp' });
  function paintInspector() {
    if (sel && sel.kind === 'edge') {
      insp.replaceChildren(el('h4', { text: 'Dây nối' }), el('p', { class: 'dim small', text: 'Bấm Xóa (hoặc phím Delete) để bỏ dây này.' }),
        el('button', { class: 'btn btn-sm btn-danger', onclick: () => removeEdge(sel.id) }, icon('trash'), 'Xóa dây'));
      return;
    }
    const n = sel && sel.kind === 'node' ? w.nodes.find((x) => x.id === sel.id) : null;
    if (!n) {
      insp.replaceChildren(el('h4', { text: 'Cách dùng' }),
        el('ul', { class: 'wf-help' },
          el('li', { text: 'Kéo khối từ bên trái vào, hoặc bấm khối để thêm nối tiếp khối đang chọn.' }),
          el('li', { text: 'Nối dây: kéo từ chấm tròn bên phải một khối sang chấm cùng màu bên trái khối khác.' }),
          el('li', { text: 'Bấm vào khối để chỉnh thiết lập. Phím Delete xóa khối hoặc dây đang chọn.' }),
          el('li', { text: 'Kéo nền để di chuyển, lăn chuột để phóng to, thu nhỏ.' }),
          el('li', { text: 'Khối có dấu $ gọi AI vẽ ảnh trả phí: trước khi chạy iContent hỏi lại kèm số ảnh, giá. Chọn nguồn Vẽ trên máy thì miễn phí, không hỏi.' })),
        el('div', { class: 'wf-legend' }, Object.entries(KIND_LABEL).map(([k, l]) => el('span', {}, el('i', { class: 'wf-dot', style: { background: KIND_COLOR[k] } }), l))));
      return;
    }
    const spec = N[n.type];
    const set = (k, v, repaint = true) => { n.params[k] = v; if (repaint) repaintNode(n.id); save(); };
    const fields = spec.params.map((p) => {
      const v = n.params[p.key];
      let input;
      if (p.type === 'textarea') input = el('textarea', { class: 'input', rows: n.type === 'script' ? 10 : 4, value: v || '', placeholder: p.placeholder || '', oninput: (e) => set(p.key, e.target.value) });
      else if (p.type === 'text') input = el('input', { class: 'input', value: v || '', placeholder: p.placeholder || '', oninput: (e) => set(p.key, e.target.value) });
      else if (p.type === 'checkbox') return el('label', { class: 'check' }, el('input', { type: 'checkbox', checked: !!v, onchange: (e) => set(p.key, e.target.checked) }), ' ' + p.label);
      else if (p.type === 'select') {
        let opts = p.options;
        if (p.key === 'provider') opts = p.options.map(([id, l]) => { const pr = (reg.image_providers || []).find((x) => x.id === id); return [id, pr ? `${l}${!pr.ready ? (pr.local ? ' (chưa tải)' : ' (chưa có key)') : pr.status === 'billing' ? ' (key chưa bật thanh toán)' : ''}` : l]; });
        input = el('select', { class: 'input', onchange: (e) => {
          set(p.key, typeof p.default === 'number' ? Number(e.target.value) : e.target.value);
          // đổi bộ giọng: giọng của bộ kia không đọc được (Edge không có giọng VieNeu): về giọng mặc định, nạp lại danh sách giọng
          if (n.type === 'voice' && p.key === 'engine') { n.params.voice = ''; save(); paintInspector(); }
        } },
          opts.map(([ov, ol]) => el('option', { value: ov, selected: String(ov) === String(v) }, ol)));
      } else if (p.type === 'range') {
        const out = el('span', { class: 'mono small', text: p.key === 'volume' ? `${Math.round(v * 100)}%` : `${Number(v).toFixed(2)}x` });
        input = el('div', { class: 'sy-range' }, el('input', { type: 'range', min: p.min, max: p.max, step: p.step, value: v, oninput: (e) => { set(p.key, Number(e.target.value)); out.textContent = p.key === 'volume' ? `${Math.round(e.target.value * 100)}%` : `${Number(e.target.value).toFixed(2)}x`; } }), out);
      } else if (p.type === 'voice') {
        const sel2 = el('select', { class: 'input', onchange: () => set('voice', sel2.value) });
        const fill = () => fillVoiceSelect(sel2, n.params.engine || 'vieneu', { current: n.params.voice || '' });
        fill();
        const hook = () => { if (!sel2.isConnected) return false; fill(); return true; };
        voiceHooks.add(hook);
        const mine = el('button', { class: 'btn btn-xs btn-icon', title: 'Giọng của tôi: thu giọng của chính bạn', 'aria-label': 'Giọng của tôi', onclick: () => openMyVoices({ onPick: (id) => { n.params.engine = 'vieneu'; set('voice', id); paintInspector(); } }) }, icon('mic'));
        input = el('div', { class: 'voice-pick' }, sel2, mine);
      } else if (p.type === 'music') {
        const msel = el('select', { class: 'input', onchange: () => set('music', msel.value) }, el('option', { value: '' }, 'Không nhạc'), (reg.music || []).map((m) => el('option', { value: m, selected: m === v }, m)));
        const up = el('input', { type: 'file', accept: 'audio/*', hidden: true, onchange: () => busy(null, async () => {
          const f = up.files[0];
          if (!f) return;
          const r = await uploadFile('music', f);
          const name = String(r.name || r.path || '').split(/[\\/]/).pop();
          reg.music = [...new Set([...(reg.music || []), name])];
          set('music', name);
          paintInspector();
        }) });
        input = el('div', { class: 'voice-pick' }, msel, el('button', { class: 'btn btn-xs', title: 'Tải nhạc từ máy', onclick: () => up.click() }, icon('upload')), up);
      } else if (p.type === 'files') {
        const grid = el('div', { class: 'wf-files' }, (v || []).map((f) => el('div', { class: 'wf-file' }, el('img', { src: `/api/workflows/${enc(wid)}/files/${enc(f)}`, alt: '' }),
          el('button', { class: 'wf-x', title: 'Bỏ ảnh', 'aria-label': 'Bỏ ảnh', onclick: () => { set('files', n.params.files.filter((x) => x !== f)); paintInspector(); } }, icon('x')))));
        const up = el('input', { type: 'file', accept: 'image/*', multiple: true, hidden: true, onchange: () => busy(addBtn, async () => {
          const files = [...up.files];
          up.value = '';
          const names = [...(n.params.files || [])];
          for (let i = 0; i < files.length; i++) {
            addBtn.lastChild.textContent = ` Đang thêm ${i + 1}/${files.length}`;
            const res = await fetch(`/api/workflows/${enc(wid)}/files`, { method: 'PUT', body: files[i] });
            if (!res.ok) { let msg = `Lỗi ${res.status}`; try { msg = (await res.json()).detail || msg; } catch (_) { /* */ } throw new Error(`${files[i].name}: ${msg}`); }
            names.push((await res.json()).name);
          }
          addBtn.lastChild.textContent = ' Thêm ảnh';
          set('files', names);
          paintInspector();
        }) });
        const addBtn = el('button', { class: 'btn btn-sm', onclick: () => up.click() }, icon('upload'), el('span', { text: ' Thêm ảnh' }));
        return el('div', { class: 'field' }, el('span', { class: 'label', text: `${p.label} (${(v || []).length}, đúng thứ tự cảnh)` }), grid, el('div', { class: 'btn-row' }, addBtn, up));
      }
      return el('label', { class: 'field' }, el('span', { class: 'label', text: p.label }), input);
    });
    const st = run && run.nodes ? run.nodes[n.id] : null;
    insp.replaceChildren(
      el('div', { class: 'wf-insp-h' }, icon(spec.icon), el('h4', { text: spec.label })),
      el('p', { class: 'dim small', text: spec.help }),
      problems[n.id] ? el('div', { class: 'wf-prob' }, icon('alert'), el('span', { text: problems[n.id] })) : '',
      st && st.state === 'error' ? el('div', { class: 'wf-err' }, el('b', { text: 'Lỗi lần chạy trước' }), el('span', { text: st.message })) : '',
      ...fields,
      el('div', { class: 'btn-row wf-insp-foot' }, el('button', { class: 'btn btn-xs btn-danger', onclick: () => removeNode(n.id) }, icon('trash'), 'Xóa khối')));
  }

  // ---------- chạy
  const nameInp = el('input', { class: 'input wf-name', value: w.name, 'aria-label': 'Tên quy trình', oninput: () => { w.name = nameInp.value; save(); } });
  const runBtn = el('button', { class: 'btn btn-primary', onclick: () => busy(runBtn, () => startRun(false)) }, icon('play'), 'Chạy');
  const stopBtn = el('button', { class: 'btn btn-danger', hidden: true, onclick: () => busy(stopBtn, async () => { await api('POST', `/api/workflows/${enc(wid)}/stop`); toast('Sẽ dừng sau bước đang chạy', 'info'); }) }, icon('stop'), 'Dừng');
  const runInfo = el('span', { class: 'dim small wf-runinfo' });
  async function startRun(confirm) {
    await saveNow();
    const r = await api('POST', `/api/workflows/${enc(wid)}/run`, { confirm });
    if (r.problems) {
      problems = r.problems;
      paintProblems();
      const first = Object.keys(problems)[0];
      select({ kind: 'node', id: first });
      toast('Còn khối chưa sẵn sàng: ' + Object.values(problems)[0], 'warn', { timeout: 6000 });
      return;
    }
    if (r.confirm) {
      const lines = r.confirm.lines.map((l) => `${l.label}: khoảng ${l.images} ${l.unit === 'clip' ? 'clip' : 'ảnh'} bằng ${l.provider_name}${l.price ? ` (${l.price})` : ''}`
        + (l.billing ? '. Lưu ý: lần trước key này bị từ chối vì chưa bật thanh toán, bước này sẽ báo lỗi nếu chưa bật' : '')).join('\n');
      const ok = await confirmDialog('Có bước trả phí', `${lines}\n\nẢnh, clip đã có thì không làm lại. Chạy tiếp?`, { okText: 'Chạy, đồng ý trả phí' });
      if (ok) await startRun(true);
      return;
    }
    run = r.run;
    paintNodes();
    paintRunBar();
    poll();
  }
  let timer = 0;
  async function poll() {
    clearTimeout(timer);
    if (!main.isConnected) return;
    try {
      const r = await api('GET', `/api/workflows/${enc(wid)}/run`);
      const before = JSON.stringify(run);
      run = r.run;
      if (JSON.stringify(run) !== before) { for (const n of w.nodes) repaintNode(n.id); paintWires(); paintRunBar(); if (sel) paintInspector(); }
      if (run && run.state === 'running') { timer = setTimeout(poll, 900); return; }
      if (run && run.state === 'done') toast('Quy trình đã chạy xong', 'success');
      else if (run && run.state === 'error') showError(new Error('Quy trình dừng vì lỗi: ' + (run.error || '').split('\n')[0]), { timeout: 9000 });
    } catch (e) { timer = setTimeout(poll, 2500); }
  }
  cleanups.push(() => clearTimeout(timer));
  function paintRunBar() {
    const running = run && run.state === 'running';
    runBtn.hidden = running;
    stopBtn.hidden = !running;
    if (!run) { runInfo.textContent = Object.keys(problems).length ? `${Object.keys(problems).length} khối chưa sẵn sàng` : 'Sẵn sàng chạy'; return; }
    const ns = Object.values(run.nodes || {});
    const done = ns.filter((x) => x.state === 'done').length;
    runInfo.textContent = running ? `Đang chạy: xong ${done}/${ns.length} khối` : run.state === 'done' ? `Lần chạy ${fmtAgo(run.at)}: xong cả ${ns.length} khối` : run.state === 'error' ? 'Lần chạy trước dừng vì lỗi' : 'Đã dừng';
  }

  main.append(
    el('div', { class: 'wf-top' },
      el('a', { class: 'btn btn-icon btn-ghost', href: '#/flow', title: 'Về danh sách quy trình', 'aria-label': 'Về danh sách' }, icon('back')),
      nameInp, el('span', { class: 'grow' }), runInfo,
      el('button', { class: 'btn btn-ghost', title: 'Xem vừa toàn bộ quy trình', onclick: fitView }, icon('full'), 'Vừa màn hình'),
      stopBtn, runBtn),
    el('div', { class: 'wf-main' }, palette, canvas, insp));
  paintNodes();
  paintInspector();
  paintRunBar();
  requestAnimationFrame(fitView);
  if (run && run.state === 'running') poll();
  return () => cleanups.forEach((f) => f());
}
