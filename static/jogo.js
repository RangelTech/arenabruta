// App da Arena Bruta: lobby, partida 3D ao vivo (WebSocket, servidor autoritativo), carteira Pix, ranking e perfil.
import { criarCena, MODELOS } from '/s/arena3d.js'
const MODELO_IDS = Object.keys(MODELOS)
const corInt = (h, pad) => (/^#[0-9a-f]{6}$/i.test(h || '') ? parseInt(h.slice(1), 16) : pad)
const modeloDe = (g) => (typeof g?.modelo === 'number' ? MODELO_IDS[g.modelo % MODELO_IDS.length] : (MODELOS[g?.modelo] ? g.modelo : null))

const $ = (q, r = document) => r.querySelector(q)
const $$ = (q, r = document) => [...r.querySelectorAll(q)]
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
const brl = (c) => 'R$ ' + (c / 100).toFixed(2).replace('.', ',')
// Arroba (@): a moeda do jogo, 1 @ = R$ 1,00 (par a par). O saldo, as entradas e os prêmios aparecem em arrobas.
const ar = (c) => (c / 100).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ' @'
const arHtml = (c) => `<span class="arroba">${ar(c).replace(' @', '')}<i>@</i></span>`
let conta = null, modo = 'combate', arenasCache = [], infoArenas = null, cena = null, ws = null, partida = null, lado = 'a', ultimaArena = null
let toastT = 0
const toast = (t) => { const el = $('#toast'); el.textContent = t; el.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => (el.hidden = true), 4500) }
async function api(metodo, url, corpo) {
  const r = await fetch(url, { method: metodo, headers: corpo ? { 'Content-Type': 'application/json' } : {}, body: corpo ? JSON.stringify(corpo) : undefined })
  let j = {}
  try { j = await r.json() } catch {}
  if (r.status === 401) { location.href = '/?entrar=1'; return new Promise(() => {}) }  // indo para o login: espera a troca de página, sem erro solto
  if (!r.ok) throw Object.assign(new Error(typeof j.detail === 'string' ? j.detail : 'Não deu certo. Tente de novo.'), { status: r.status })
  return j
}

// ---------------- vistas ----------------
function irVista(v) {
  $$('.vistas button').forEach((b) => b.classList.toggle('on', b.dataset.v === v))
  $$('.vista').forEach((s) => s.classList.toggle('on', s.id === 'v-' + v))
  if (v !== 'partida') history.replaceState(null, '', '#' + v)
  ;({ lobby: carregarLobby, box: carregarBox, carteira: carregarCarteira, ranking: carregarRanking, perfil: carregarPerfil })[v]?.()
}
$$('.vistas button').forEach((b) => (b.onclick = () => irVista(b.dataset.v)))
$('#saldo-topo').onclick = () => irVista('carteira')
addEventListener('hashchange', () => { const v = location.hash.slice(1); if ($('#v-' + v) && v !== 'partida') irVista(v) })

async function carregarConta() {
  conta = await api('GET', '/api/conta')
  $('#saldo-topo').innerHTML = arHtml(conta.saldo.disponivel)
  if (conta.perfil) $('#nivel-txt').textContent = `Nível ${conta.perfil.nivel} · ${conta.perfil.vitorias} vitórias · ${conta.perfil.xp} XP`
  return conta
}

// ---------------- lobby ----------------
$$('.troca-modo button').forEach((b) => (b.onclick = () => { modo = b.dataset.modo; $$('.troca-modo button').forEach((x) => x.classList.toggle('on', x === b)); desenharArenas() }))
async function carregarLobby() {
  await carregarConta()
  if (!arenasCache.length) { infoArenas = await api('GET', '/api/arenas'); arenasCache = infoArenas.arenas }
  desenharArenas()
}
const NOME_PNEU = { liso: 'Liso', misto: 'Misto', cravo: 'Cravo' }
const NOME_REL = { curta: 'Curta', media: 'Média', longa: 'Longa' }
const NOME_MAPA = { torque: 'Torque', potencia: 'Potência' }
const resumoAcerto = (a) => a ? `${NOME_PNEU[a.pneu]} · ${a.psi} psi · relação ${NOME_REL[a.relacao]} · mapa ${NOME_MAPA[a.mapa]}` : '—'
function desenharArenas() {
  const disp = conta?.saldo?.disponivel || 0
  const cen = infoArenas?.cenarios || {}
  $('#historia-ctrl').hidden = modo !== 'treino'
  const g = conta?.garagem || {}
  $('#seu-acerto').innerHTML = `<span><b>${esc(MODELOS[modeloDe(g) || 'fam3500'].nome)}</b> · ${esc(resumoAcerto(conta?.acerto))}</span><a class="btn btn-sec" href="#box">Ajustar no Box</a>`
  if (modo === 'treino') {
    $('#arenas').innerHTML = Object.entries(cen).map(([id, c]) => `<div class="arena"><small>${esc(c.piso_nome)}</small><h3>${esc(c.nome)}</h3>
      <div class="nums"><div><span>Modo história</span><b>Grátis</b></div></div><div class="nota">Rival no nível escolhido acima. Não vale dinheiro.</div>
      <button class="btn btn-ouro" data-cen="${id}" style="margin-top:10px">Treinar aqui</button></div>`).join('')
    $$('[data-cen]').forEach((b) => (b.onclick = () => entrarNaFila('peao', b.dataset.cen)))
    return
  }
  $('#arenas').innerHTML = arenasCache.map((a, i) => {
    const pode = disp >= a.entrada, c = cen[a.id] || {}
    return `<div class="arena ${pode ? '' : 'travada'}"><small>Arena ${i + 1} · ${esc(c.nome || '')}</small><h3>${esc(a.nome)}</h3>
      <div class="nums"><div><span>Entrada</span><b class="ent">${arHtml(a.entrada)}</b></div><div><span>Prêmio</span><b>${arHtml(a.premio)}</b></div></div>
      <div class="nota">Piso: <b>${esc(c.piso_nome || '')}</b> · comissão ${ar(a.comissao)} · perda máxima: a sua entrada</div>
      <button class="btn ${pode ? 'btn-ouro' : 'btn-sec'}" data-arena="${a.id}" style="margin-top:10px">${pode ? 'Entrar no duelo' : 'Depositar para jogar'}</button></div>`
  }).join('')
  $$('[data-arena]').forEach((b) => (b.onclick = () => {
    if ((conta?.saldo?.disponivel || 0) < arenasCache.find((a) => a.id === b.dataset.arena).entrada) return irVista('carteira')
    entrarNaFila(b.dataset.arena)
  }))
}
$('#h-nivel').oninput = (e) => { $('#h-nivel-v').textContent = e.target.value }

// ---------------- partida ----------------
let ultimoCen = null
async function entrarNaFila(arena, cenario) {
  if (!conta.perfil) { toast('Complete o seu perfil (apelido e data de nascimento) antes de jogar.'); return irVista('perfil') }
  ultimaArena = arena; ultimoCen = cenario || null
  try {
    partida = await api('POST', '/api/fila', modo === 'treino' ? { arena, modo, cenario, nivel: +$('#h-nivel').value } : { arena, modo })
  } catch (e) { return toast(e.message) }
  abrirPartida()
}
function abrirPartida() {
  $$('.vista').forEach((s) => s.classList.toggle('on', s.id === 'v-partida'))
  $('#resultado').hidden = true
  $('#nome-a').textContent = conta.perfil?.apelido || 'Você'
  if (!cena) cena = criarCena($('#cena3d'), { modo: 'jogo' })
  else cena.tamanho()
  cena.atualizar({ pos: 0, a: { rpm: 800, forca: 0, acel: 0, temp: 0 }, b: { rpm: 800, forca: 0, acel: 0, temp: 0 } })
  montarArena()
  if (partida.estado === 'fila') esperarAdversario()
  else conectar()
}
async function esperarAdversario() {
  $('#espera').hidden = false
  const id = partida.id, t0 = Date.now()
  const conta15 = () => { const s = Math.max(0, 15 - Math.floor((Date.now() - t0) / 1000)); $('#espera-txt').textContent = s ? `Procurando adversário… ${s} s` : 'Procurando adversário…' }
  conta15(); const rel = setInterval(conta15, 500)
  while (partida && partida.id === id && partida.estado === 'fila') {
    await new Promise((r) => setTimeout(r, 1500))
    try { partida = await api('GET', `/api/partida/${id}`) } catch { break }
  }
  clearInterval(rel)
  if (partida && partida.estado === 'pronta') { montarArena(); conectar() }
}
$('#sair-fila').onclick = async () => {
  try { await api('POST', `/api/partida/${partida.id}/sair`); toast('Você saiu da fila. A entrada voltou para o saldo.') } catch (e) { toast(e.message) }
  partida = null
  irVista('lobby')
}
function conectar() {
  $('#espera').hidden = false
  $('#espera-txt').textContent = 'Adversário encontrado. Esquentando os motores…'
  $('#nome-b').textContent = partida.rival?.apelido || 'Rival'
  ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + `/ws/partida/${partida.id}`)
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data)
    if (m.t === 'ok') { lado = m.lado; partida = { ...partida, ...m.partida }; montarArena(); if (lado === 'b') { $('#nome-b').textContent = conta.perfil?.apelido || 'Você'; $('#nome-a').textContent = m.partida.rival?.apelido || 'Rival' } }
    if (m.t === 'contagem') { $('#espera').hidden = true; const c = $('#contagem'); c.hidden = false; c.textContent = m.n; somMotor(true) }
    if (m.t === 'estado') {
      $('#contagem').hidden = true; $('#espera').hidden = true
      const eu = m[lado], pos = lado === 'a' ? m.pos : -m.pos
      cena.atualizar(m)
      $('#marcador').style.left = (50 - (m.pos / 10000) * 50) + '%'
      $('#marcha-a').textContent = m.a.marcha + 'ª'; $('#marcha-b').textContent = m.b.marcha + 'ª'
      $('#relogio').textContent = Math.max(0, Math.ceil((600 - m.tick) / 20))
      $('#rpm').textContent = eu.rpm
      $('#rpm-arco').style.strokeDashoffset = 157 - 157 * Math.min(1, (eu.rpm - 800) / 6200)
      $('#temp').style.width = Math.min(100, eu.temp / 10) + '%'
      $('#aviso-motor').textContent = eu.fervendo ? 'MOTOR FERVENDO!' : eu.patinou ? 'patinando: alivie ou suba a marcha' : eu.rpm > 6000 ? 'giro alto: esquentando' : pos > 3000 ? 'arrastando o rival!' : 'temperatura'
      somRpm(eu.rpm, eu.acel)
    }
    if (m.t === 'fim') fimPartida(m)
  }
  ws.onclose = () => { somMotor(false) }
}
function enviar(cmd) { if (ws && ws.readyState === 1) ws.send(JSON.stringify({ cmd })) }
function fimPartida(m) {
  somMotor(false)
  const venci = m.vencedor === lado, empate = m.vencedor === 'empate'
  const r = $('#resultado')
  r.hidden = false
  r.classList.toggle('perdeu', !venci && !empate)
  $('#res-tit').textContent = empate ? 'EMPATE' : venci ? 'VOCÊ VENCEU' : 'NÃO FOI DESSA VEZ'
  $('#res-txt').textContent = partida.modo === 'treino' ? (venci ? 'Bom treino. Suba o nível do rival ou encare a Arena de Combate.' : 'Treino é para isso. Confira no Box o pneu e o psi para este piso e troque a marcha no giro certo do seu mapa.')
    : empate ? 'Empate: a entrada voltou inteira para o seu saldo.' : venci ? `${ar(m.premio)} caíram no seu saldo.` : 'Você perdeu a entrada desta partida. Treine e volte mais forte.'
  ws && ws.close(); ws = null
  carregarConta()
}
$('#de-novo').onclick = () => entrarNaFila(ultimaArena, ultimoCen)
$('#voltar').onclick = () => { partida = null; irVista('lobby') }

// controles: segurar o acelerador (toque, mouse ou espaço), marcha (botão ou seta), tração
const acel = $('#b-acel')
const liga = (on) => { acel.classList.toggle('on', on); enviar({ acel: on ? 1 : 0 }) }
acel.addEventListener('pointerdown', (e) => { e.preventDefault(); acel.setPointerCapture(e.pointerId); liga(true) })
acel.addEventListener('pointerup', () => liga(false)); acel.addEventListener('pointercancel', () => liga(false))
$('#b-marcha').onclick = () => enviar({ marcha: 1 })
addEventListener('keydown', (e) => {
  if (!$('#v-partida').classList.contains('on')) return
  if (e.code === 'Space' && !e.repeat) { e.preventDefault(); liga(true) }
  if (e.code === 'ArrowUp') { e.preventDefault(); enviar({ marcha: 1 }) }
  if (e.code === 'ArrowDown') { e.preventDefault(); enviar({ marcha: -1 }) }
})
addEventListener('keyup', (e) => { if (e.code === 'Space' && $('#v-partida').classList.contains('on')) liga(false) })

// ronco do diesel (Web Audio): grave que acompanha o giro + assobio da turbina no giro alto
let audio = null
function somMotor(on) {
  try {
    if (on && !audio) {
      const ctx = new (window.AudioContext || window.webkitAudioContext)()
      const o = ctx.createOscillator(); o.type = 'sawtooth'
      const o2 = ctx.createOscillator(); o2.type = 'square'
      const filtro = ctx.createBiquadFilter(); filtro.type = 'lowpass'; filtro.frequency.value = 420
      const g = ctx.createGain(); g.gain.value = 0.05
      const turbo = ctx.createOscillator(); turbo.type = 'sine'
      const gt = ctx.createGain(); gt.gain.value = 0
      o.connect(filtro); o2.connect(filtro); filtro.connect(g); g.connect(ctx.destination); turbo.connect(gt); gt.connect(ctx.destination)
      o.start(); o2.start(); turbo.start()
      audio = { ctx, o, o2, g, turbo, gt }
    } else if (!on && audio) { audio.ctx.close(); audio = null }
  } catch {}
}
function somRpm(rpm, acelerando) {
  if (!audio) return
  const t = audio.ctx.currentTime
  audio.o.frequency.setTargetAtTime(28 + rpm / 70, t, 0.05)
  audio.o2.frequency.setTargetAtTime(14 + rpm / 140, t, 0.05)
  audio.g.gain.setTargetAtTime(acelerando ? 0.07 : 0.035, t, 0.08)
  audio.turbo.frequency.setTargetAtTime(1800 + rpm / 3, t, 0.1)
  audio.gt.gain.setTargetAtTime(acelerando && rpm > 4800 ? 0.012 : 0, t, 0.15)
}

// ---------------- carteira ----------------
async function carregarCarteira() {
  const j = await api('GET', '/api/carteira')
  $('#s-disp').innerHTML = arHtml(j.saldo.disponivel); $('#s-res').innerHTML = arHtml(j.saldo.reservado); $('#s-saq').innerHTML = arHtml(j.saldo.saque)
  $('#saldo-topo').innerHTML = arHtml(j.saldo.disponivel)
  const est = { pendente: 'aguardando confirmação', confirmado: 'confirmado', cancelado: 'cancelado', pago: 'pago', recusado: 'recusado' }
  const linhas = [
    ...j.depositos.filter((d) => d.estado === 'pendente').map((d) => `<div class="item"><span>Compra de ${ar(d.valor)} (${brl(d.valor)} no Pix) · ${est[d.estado]}</span><b>⏳</b></div>`),
    ...j.saques.filter((s) => s.estado === 'pendente').map((s) => `<div class="item"><span>Saque de ${ar(s.valor)} → ${brl(s.valor)} no Pix · em análise</span><b>⏳</b></div>`),
    ...j.extrato.map((l) => `<div class="item"><span>${new Date(l.criado * 1000).toLocaleString('pt-BR')} · ${esc(l.descricao)}</span><b class="${l.valor >= 0 ? 'mais' : 'menos'}">${l.valor >= 0 ? '+' : '−'} ${ar(Math.abs(l.valor))}</b></div>`),
  ]
  $('#extrato').innerHTML = linhas.join('') || '<p class="mut">Nenhum movimento ainda.</p>'
}
$$('#f-dep .valores button').forEach((b) => (b.onclick = () => ($('#dep-valor').value = b.dataset.v)))
$('#f-dep').onsubmit = async (e) => {
  e.preventDefault()
  try {
    const d = await api('POST', '/api/deposito', { valor: +$('#dep-valor').value })
    const box = $('#dep-info')
    box.hidden = false
    box.innerHTML = `<b>Pix de ${brl(d.valor)} → ${ar(d.valor)} na sua carteira</b><p class="mut" style="margin:6px 0">${esc(d.instrucoes)}</p>${d.copia_cola ? `<code>${esc(d.copia_cola)}</code><button type="button" class="btn btn-sec" id="copiar">Copiar chave Pix</button>` : ''}
      <button type="button" class="btn btn-ouro" id="paguei" style="margin-left:6px">Já paguei</button>`
    $('#copiar') && ($('#copiar').onclick = () => navigator.clipboard.writeText(d.copia_cola).then(() => toast('Chave copiada.')))
    $('#paguei').onclick = async () => { await api('POST', `/api/deposito/${d.id}/paguei`); toast('Obrigado! Assim que o Pix for confirmado, o saldo aparece aqui.'); carregarCarteira() }
    carregarCarteira()
  } catch (err) { toast(err.message); if (err.status === 428) irVista('perfil') }
}
$('#f-saq').onsubmit = async (e) => {
  e.preventDefault()
  try { const r = await api('POST', '/api/saque', { valor: +$('#saq-valor').value }); $('#saq-msg').textContent = r.aviso; carregarCarteira() }
  catch (err) { $('#saq-msg').textContent = err.message; if (err.status === 428) irVista('perfil') }
}

// ---------------- ranking ----------------
async function carregarRanking() {
  const [r, m] = await Promise.all([api('GET', '/api/ranking'), api('GET', '/api/partidas')])
  $('#ranking').innerHTML = r.ranking.map((p, i) => `<div class="item"><span class="pos">${i + 1}</span><b>${esc(p.apelido)}</b><span class="mut">Nível ${p.nivel}</span><span class="mut">${p.vitorias} vitórias</span></div>`).join('') || '<p class="mut">Ninguém no ranking ainda. Seja o primeiro.</p>'
  $('#minhas').innerHTML = m.partidas.map((p) => `<div class="item"><span>${p.modo === 'treino' ? 'Treino' : 'Combate'} · ${esc(p.arena)} · vs ${esc(p.rival?.apelido || '—')}</span><b class="${p.vencedor === p.lado ? 'mais' : 'menos'}">${p.estado === 'cancelada' ? 'cancelada' : p.vencedor === 'empate' ? 'empate' : p.vencedor === p.lado ? 'vitória' : 'derrota'}</b></div>`).join('') || '<p class="mut">Sem partidas ainda.</p>'
}

// ---------------- perfil ----------------
async function carregarPerfil() {
  await carregarConta()
  const f = $('#f-perfil'), p = conta.perfil
  if (p) { f.apelido.value = p.apelido; f.nascimento.value = p.nascimento; f.nascimento.readOnly = true; f.pix_tipo.value = p.pix_tipo || 'cpf'; f.pix_chave.value = p.pix_chave || ''; $('#lim-dep').value = (p.limite_dep_dia || 0) / 100 }
}
$('#f-perfil').onsubmit = async (e) => {
  e.preventDefault()
  try { await api('POST', '/api/perfil', Object.fromEntries(new FormData(e.target).entries())); $('#perfil-msg').textContent = 'Salvo.'; carregarConta() }
  catch (err) { $('#perfil-msg').textContent = err.message }
}
$('#f-lim').onsubmit = async (e) => { e.preventDefault(); try { await api('POST', '/api/limites', { limite_dep_dia: Math.round(+$('#lim-dep').value * 100) }); $('#lim-msg').textContent = 'Limite salvo.' } catch (err) { $('#lim-msg').textContent = err.message } }
$$('[data-pausa]').forEach((b) => (b.onclick = async () => {
  if (!confirm(`Pausar a conta por ${b.textContent}? Nesse tempo você não joga nem deposita (saque continua liberado).`)) return
  try { await api('POST', '/api/limites', { pausa_dias: +b.dataset.pausa }); $('#lim-msg').textContent = 'Pausa ativada.' } catch (err) { $('#lim-msg').textContent = err.message }
}))
$('#sair').onclick = async () => { await api('POST', '/api/sair'); location.href = '/' }

// ---------------- início ----------------
;(async () => {
  await carregarConta()
  if (!conta.perfil) { irVista('perfil'); toast('Bem-vindo à Arena! Crie o seu apelido para começar.'); return }
  const v = location.hash.slice(1)
  irVista($('#v-' + v) && v !== 'partida' ? v : 'lobby')
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/s/sw.js').catch(() => {})
})()

// ---------------- arena: atributos dos dois lados, caminhonetes e piso ----------------
function montarArena() {
  if (!partida) return
  const meu = conta?.garagem || {}, dele = partida.rival?.garagem || {}
  const souA = lado === 'a'
  const gA = souA ? meu : dele, gB = souA ? dele : meu
  cena?.trocar?.({ modeloA: modeloDe(gA) || 'fam3500', corA: corInt(gA.cor, 0xc49a46), modeloB: modeloDe(gB) || 's150', corB: corInt(gB.cor, 0x334532), piso: partida.cenario?.piso })
  const card = (titulo, nome, g, a) => `<div class="attr"><small>${titulo}</small><b>${esc(nome)}</b><span class="carro">${esc(MODELOS[modeloDe(g) || 'fam3500'].nome)}</span>
    <ul><li>Pneu <b>${esc(NOME_PNEU[a?.pneu] || '—')}</b></li><li>Calibragem <b>${a?.psi ?? '—'} psi</b></li><li>Relação <b>${esc(NOME_REL[a?.relacao] || '—')}</b></li><li>Mapa <b>${esc(NOME_MAPA[a?.mapa] || '—')}</b></li></ul></div>`
  const c = partida.cenario || {}
  $('#atributos').innerHTML = `<div class="attr-cena"><b>${esc(c.nome || '')}</b><span>piso: ${esc(c.piso_nome || '')}</span></div>` +
    card('Você', conta.perfil?.apelido || 'Você', meu, partida.eu?.acerto) + card('Rival', partida.rival?.apelido || 'procurando…', dele, partida.ele?.acerto)
}

// ---------------- Box ----------------
let boxCena = null
const AMOSTRAS = ['#c49a46', '#1c1c1c', '#f2f2f2', '#8a1c1c', '#1f3a5f', '#334532', '#b85c1e', '#6b6b6b']
async function carregarBox() {
  await carregarConta()
  const b = conta.box, a = conta.acerto, g = conta.garagem || {}
  $('#bx-modelo').innerHTML = MODELO_IDS.map((k) => `<option value="${k}" ${k === (modeloDe(g) || 'fam3500') ? 'selected' : ''}>${esc(MODELOS[k].nome)}</option>`).join('')
  $('#bx-cor').value = g.cor || '#c49a46'; $('#bx-roda').value = g.roda || '#d9d9d9'
  $('#bx-amostras').innerHTML = AMOSTRAS.map((c) => `<button type="button" style="background:${c}" data-cor="${c}" aria-label="Pintar de ${c}"></button>`).join('')
  const radios = (id, nome, ops, atual, rotulo) => { $(id).innerHTML = `<span class="rot">${rotulo}</span>` + Object.entries(ops).map(([k, v]) => `<label><input type="radio" name="${nome}" value="${k}" ${k === atual ? 'checked' : ''}><span>${esc(v)}</span></label>`).join('') }
  radios('#bx-pneu', 'pneu', b.pneus, a.pneu, 'Pneu')
  radios('#bx-relacao', 'relacao', { curta: 'Curta (força na saída)', media: 'Média', longa: 'Longa (menos troca)' }, a.relacao, 'Relação')
  radios('#bx-mapa', 'mapa', b.mapas, a.mapa, 'Mapa do motor')
  $('#bx-psi').value = a.psi; $('#bx-psi-v').textContent = a.psi + ' psi'
  if (!boxCena) { try { boxCena = criarCena($('#box-cena'), { modo: 'heroi' }) } catch {} }
  previa()
}
function previa() {
  const m = $('#bx-modelo').value
  $('#box-nome').textContent = MODELOS[m]?.nome || ''
  boxCena?.trocar?.({ modeloA: m, corA: corInt($('#bx-cor').value, 0xc49a46), modeloB: m, corB: corInt($('#bx-cor').value, 0xc49a46), piso: 'curral' })
}
$('#bx-modelo').onchange = previa
$('#bx-cor').oninput = previa
$('#bx-amostras').onclick = (e) => { const c = e.target.dataset?.cor; if (c) { $('#bx-cor').value = c; previa() } }
$('#bx-psi').oninput = (e) => { $('#bx-psi-v').textContent = e.target.value + ' psi' }
$('#f-box').onsubmit = async (e) => {
  e.preventDefault()
  const val = (n) => $(`input[name=${n}]:checked`)?.value
  try {
    const r = await api('POST', '/api/box', { acerto: { pneu: val('pneu'), psi: +$('#bx-psi').value, relacao: val('relacao'), mapa: val('mapa') },
      garagem: { modelo: $('#bx-modelo').value, cor: $('#bx-cor').value, roda: $('#bx-roda').value } })
    conta.acerto = r.acerto; conta.garagem = r.garagem
    $('#bx-msg').textContent = 'Acerto salvo. Vale a partir da próxima partida.'
  } catch (err) { $('#bx-msg').textContent = err.message }
}
