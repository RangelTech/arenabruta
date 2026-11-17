// Garagem da Arena Bruta (estilo "editar o carro"): caminhonete no centro girando no palco, carrossel de modelos, abas de ajuste com
// cartões que passam de lado e um gráfico do motor só para ver (muda com animação conforme o acerto). Nada daqui muda a física além
// do acerto (pneu, psi, relação, mapa); pintura e modelo são só visuais. As descrições falam do item, nunca do cenário onde usar.
import * as THREE from 'three'
import { criarCaminhonete, MODELOS, ambienteMetal, TEM_PINTURA } from './caminhonetes.js'

const $ = (q, r = document) => r.querySelector(q)
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])
const IDS = Object.keys(MODELOS)
const CORES = [['#c49a46', 'Ouro do agro'], ['#111111', 'Preto piano'], ['#f2f2f2', 'Branco gelo'], ['#8a1c1c', 'Vermelho boiadeiro'], ['#1f3a5f', 'Azul noite'],
  ['#334532', 'Verde militar'], ['#b85c1e', 'Laranja ferrugem'], ['#6b6b6b', 'Grafite'], ['#5a3a22', 'Couro'], ['#d8c38f', 'Areia'], ['#0f5c4a', 'Verde pasto'], ['#7a1f5c', 'Vinho']]
const OPCOES = {
  pneu: [['liso', 'Liso de estrada', 'A/T leve', 'Composto macio e sulcos rasos: muita borracha encostada no chão. Roda leve, preciso e silencioso.'],
    ['misto', 'Misto', 'A/T', 'Blocos médios e ombro reforçado. O equilíbrio entre agarrar, durar e rodar macio.'],
    ['cravo', 'Cravo lameiro', 'M/T', 'Blocos altos e espaçados que mordem e se limpam sozinhos. Pneu bruto, feito para enfiar a caminhonete onde ninguém entra.']],
  relacao: [['curta', 'Curta', 'arrancada', 'Muita força nas primeiras marchas e giro que sobe rápido. Pede mão rápida no câmbio.'],
    ['media', 'Média', 'equilíbrio', 'O meio-termo entre o tranco da saída e o fôlego no fim.'],
    ['longa', 'Longa', 'fôlego', 'Menos trocas e força que cresce no fim do puxão. Exige paciência e pé firme.']],
  mapa: [['torque', 'Torque', 'força embaixo', 'Entrega tudo no giro baixo. Esticar demais esquenta o motor mais cedo.'],
    ['potencia', 'Potência', 'força em cima', 'Acorda no giro alto e aguenta mais rotação antes de esquentar.']],
}
const ABAS = [['modelo', 'Máquina'], ['pintura', 'Pintura'], ['pneu', 'Pneu'], ['psi', 'Calibragem'], ['relacao', 'Relação'], ['mapa', 'Mapa do motor']]
const descPsi = (p) => p <= 21 ? 'Pneu murcho: muita área de contato, flanco trabalhando e resposta macia.' : p <= 33 ? 'Pressão de equilíbrio: contato e firmeza na medida.' : 'Pneu duro: pouca área no chão, resposta seca e rápida.'

let estado = null, palco = null, graf = null

// ---------------- palco 3D: a caminhonete no centro, girando ----------------
function criarPalco(canvas) {
  const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
  r.setPixelRatio(Math.min(2, devicePixelRatio || 1)); r.toneMapping = THREE.ACESFilmicToneMapping; r.shadowMap.enabled = true
  const cena = new THREE.Scene(); cena.environment = ambienteMetal(r)   // fundo transparente: atrás fica a foto do galpão
  const chao = new THREE.Mesh(new THREE.CircleGeometry(9, 64), new THREE.ShadowMaterial({ opacity: 0.6 }))   // só a sombra no chão da foto
  chao.rotation.x = -Math.PI / 2; chao.receiveShadow = true; cena.add(chao)
  const anel = new THREE.Mesh(new THREE.RingGeometry(4.6, 4.68, 96), new THREE.MeshBasicMaterial({ color: 0xe2c27e, transparent: true, opacity: 0.55 })); anel.rotation.x = -Math.PI / 2; anel.position.y = 0.01; cena.add(anel)
  cena.add(new THREE.HemisphereLight(0xfff2dd, 0x221a12, 0.7))
  const topo = new THREE.SpotLight(0xffffff, 260, 30, 0.6, 0.5); topo.position.set(0, 12, 2); topo.castShadow = true; topo.shadow.mapSize.set(2048, 2048); cena.add(topo)
  const lado = new THREE.DirectionalLight(0xffc27a, 1.4); lado.position.set(-8, 4, 6); cena.add(lado)
  const contra = new THREE.DirectionalLight(0x9ab8ff, 0.8); contra.position.set(8, 3, -8); cena.add(contra)
  const cam = new THREE.PerspectiveCamera(32, 1, 0.1, 100)
  const piv = new THREE.Group(); cena.add(piv)
  let carro = null, ang = 0.7, arrastando = false, x0 = 0, auto = true
  canvas.addEventListener('pointerdown', (e) => { arrastando = true; x0 = e.clientX; auto = false; canvas.setPointerCapture(e.pointerId) })
  canvas.addEventListener('pointermove', (e) => { if (arrastando) { ang += (e.clientX - x0) * 0.01; x0 = e.clientX } })
  canvas.addEventListener('pointerup', () => { arrastando = false; setTimeout(() => (auto = true), 2500) })
  function tamanho() { const w = canvas.clientWidth || 800, h = canvas.clientHeight || 450; r.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix() }
  function mostrar(modelo, cor) {
    if (carro) piv.remove(carro.g)
    carro = criarCaminhonete(modelo, cor, true)
    carro.g.position.set(0, 0, 0)
    piv.add(carro.g)
  }
  let raf = 0
  const quadro = () => {
    if (canvas.offsetParent) {   // só desenha com a aba visível
      if (auto) ang += 0.004
      piv.rotation.y = ang
      cam.position.set(Math.sin(0.4) * 9.2, 3.1, Math.cos(0.4) * 9.2); cam.lookAt(0, 1.15, 0)
      tamanho(); r.render(cena, cam)
    }
    raf = requestAnimationFrame(quadro)
  }
  quadro()
  return { mostrar, parar: () => cancelAnimationFrame(raf) }
}

// ---------------- gráfico do motor (só visual, animado) ----------------
function torque(mapa, rpm) {   // mesma forma das curvas do motor (0..1)
  const [a, b, cai] = mapa === 'potencia' ? [4800, 5800, 600] : [2800, 3800, 150]
  if (rpm < a) return Math.max(120, 120 + (rpm - 800) * 880 / (a - 800)) / 1000
  if (rpm <= b) return 1
  return Math.max(cai, 1000 - (rpm - b) * (1000 - cai) / (7000 - b)) / 1000
}
function criarGrafico(canvas) {
  const g = canvas.getContext('2d')
  const atual = { pico: 3300, larg: 1500, forca: 1, limiar: 5200, contato: 0.6, rigidez: 0.5, bloco: 0.5, mapa: 'torque' }
  const alvo = { ...atual }
  const cor = (v) => { // azul -> verde -> amarelo -> vermelho (como mapa de eficiência)
    const p = [[0, [20, 40, 140]], [0.35, [40, 170, 210]], [0.55, [80, 200, 90]], [0.75, [235, 220, 60]], [0.9, [240, 140, 40]], [1, [215, 50, 40]]]
    for (let i = 1; i < p.length; i++) if (v <= p[i][0]) { const [a, ca] = p[i - 1], [b, cb] = p[i], t = (v - a) / (b - a); return ca.map((x, k) => Math.round(x + (cb[k] - x) * t)) }
    return p.at(-1)[1]
  }
  let chave = ''
  function desenhar() {
    let muda = 0
    for (const k of ['pico', 'larg', 'forca', 'limiar', 'contato', 'rigidez', 'bloco']) { const d = (alvo[k] - atual[k]) * 0.12; atual[k] += d; muda = Math.max(muda, Math.abs(d)) }
    const k2 = alvo.mapa + muda.toFixed(4)
    if (muda < 0.01 && chave === k2) { requestAnimationFrame(desenhar); return }   // parado: não redesenha
    chave = k2
    const W = canvas.width, H = canvas.height, L = 46, R = 14, T = 14, B = 34, w = W - L - R, h = H - T - B
    g.clearRect(0, 0, W, H); g.fillStyle = '#100e0c'; g.fillRect(0, 0, W, H)
    const xr = (rpm) => L + (rpm - 800) / 6200 * w, yv = (v) => T + h - v * h
    // envelope: curva de torque (com a relação) e o mapa de eficiência por baixo dela
    const curva = []
    for (let rpm = 800; rpm <= 7000; rpm += 50) curva.push([rpm, torque(alvo.mapa, rpm) * (0.7 + 0.25 * atual.forca)])
    const img = g.createImageData(w, h)
    for (let px = 0; px < w; px += 1) {
      const rpm = 800 + px / w * 6200, tope = torque(alvo.mapa, rpm) * (0.7 + 0.25 * atual.forca)
      for (let py = 0; py < h; py += 1) {
        const carga = 1 - py / h
        if (carga > tope) continue
        const e = Math.exp(-(((rpm - atual.pico) / atual.larg) ** 2) - (((carga - 0.72 * tope) / 0.38) ** 2))
        const [rr, gg, bb] = cor(Math.min(1, e * 1.05))
        const i = (py * w + px) * 4; img.data[i] = rr; img.data[i + 1] = gg; img.data[i + 2] = bb; img.data[i + 3] = 215
      }
    }
    g.putImageData(img, L, T)
    // faixa onde o motor esquenta
    g.fillStyle = 'rgba(217,88,59,.16)'; g.fillRect(xr(atual.limiar), T, xr(7000) - xr(atual.limiar), h)
    g.fillStyle = '#d9583b'; g.font = '11px Inter, sans-serif'; g.fillText('esquenta', xr(atual.limiar) + 4, T + 12)
    // torque (linha dourada) e potência (laranja tracejada)
    g.lineWidth = 2.5; g.strokeStyle = '#ffe3a0'; g.beginPath(); curva.forEach(([rpm, v], i) => (i ? g.lineTo(xr(rpm), yv(v)) : g.moveTo(xr(rpm), yv(v)))); g.stroke()
    let pmax = 0; const pot = curva.map(([rpm, v]) => { const p = v * rpm; pmax = Math.max(pmax, p); return [rpm, p] })
    g.setLineDash([6, 5]); g.strokeStyle = '#ff9a3c'; g.beginPath(); pot.forEach(([rpm, p], i) => (i ? g.lineTo(xr(rpm), yv(p / pmax * 0.95)) : g.moveTo(xr(rpm), yv(p / pmax * 0.95)))); g.stroke(); g.setLineDash([])
    // eixos
    g.strokeStyle = '#3a332a'; g.lineWidth = 1; g.beginPath(); g.moveTo(L, T); g.lineTo(L, T + h); g.lineTo(L + w, T + h); g.stroke()
    g.fillStyle = '#857a67'; g.font = '11px Inter, sans-serif'
    for (let rpm = 1000; rpm <= 7000; rpm += 1000) g.fillText(rpm / 1000 + 'k', xr(rpm) - 7, T + h + 16)
    g.fillText('rpm', W - R - 22, T + h + 30); g.save(); g.translate(14, T + h / 2 + 22); g.rotate(-Math.PI / 2); g.fillText('carga do motor', 0, 0); g.restore()
    const tq = Math.round(62 + 30 * atual.forca), cv = Math.round(pmax / 1000 * 52 + 120)
    $('#gar-numeros').innerHTML = `<div><small>Torque máximo</small><b>${tq} kgfm</b></div><div><small>Potência máxima</small><b>${cv} cv</b></div><div><small>Pico de força</small><b>${Math.round(atual.pico / 100) * 100} rpm</b></div>`
    const barra = (n, v) => `<div class="gb"><span>${n}</span><i><b style="width:${Math.round(v * 100)}%"></b></i></div>`
    $('#gar-barras').innerHTML = barra('Área de contato', atual.contato) + barra('Rigidez do pneu', atual.rigidez) + barra('Agressividade do bloco', atual.bloco)
    requestAnimationFrame(desenhar)
  }
  desenhar()
  return {
    atualizar(ac) {   // o gráfico segue o acerto (visual; os números são de vitrine, a física do jogo é a do servidor)
      alvo.mapa = ac.mapa
      alvo.pico = ac.mapa === 'potencia' ? 5300 : 3300
      alvo.larg = { curta: 1100, media: 1500, longa: 1950 }[ac.relacao]
      alvo.forca = { curta: 1.15, media: 0.9, longa: 0.65 }[ac.relacao]
      alvo.limiar = ac.mapa === 'potencia' ? 6200 : 5200
      alvo.contato = 1 - (ac.psi - 15) / 30 * 0.8
      alvo.rigidez = 0.2 + (ac.psi - 15) / 30 * 0.8
      alvo.bloco = { liso: 0.2, misto: 0.55, cravo: 0.95 }[ac.pneu]
    },
  }
}

// ---------------- telas ----------------
function desenharAba() {
  const a = estado.aba, box = $('#gar-opcoes')
  document.querySelectorAll('.gar-abas button').forEach((b) => b.classList.toggle('on', b.dataset.aba === a))
  if (a === 'modelo') {
    box.innerHTML = `<div class="gar-trilho">${IDS.map((k) => `<button class="gar-card ${k === estado.modelo ? 'on' : ''}" data-modelo="${k}"><b>${esc(MODELOS[k].nome)}</b><small>4x4 · ${TEM_PINTURA[k] === false ? 'cor de fábrica' : 'pintura livre'}</small></button>`).join('')}</div>`
  } else if (a === 'pintura') {
    const pode = TEM_PINTURA[estado.modelo] !== false
    box.innerHTML = `<div class="gar-trilho">${CORES.map(([c, n]) => `<button class="gar-card cor ${c === estado.cor ? 'on' : ''}" data-cor="${c}" ${pode ? '' : 'disabled'}><i style="background:${c}"></i><b>${esc(n)}</b></button>`).join('')}
      <label class="gar-card cor livre"><input type="color" id="gar-cor" value="${estado.cor}" ${pode ? '' : 'disabled'}><b>Cor livre</b></label></div>
      ${pode ? '' : '<p class="mut gar-obs">Esta caminhonete vem com a pintura de fábrica.</p>'}`
  } else if (a === 'psi') {
    box.innerHTML = `<div class="gar-psi"><b class="bebas" id="gar-psi-v">${estado.acerto.psi} psi</b><input type="range" id="gar-psi" min="15" max="45" value="${estado.acerto.psi}"><p class="mut" id="gar-psi-d">${descPsi(estado.acerto.psi)}</p></div>`
  } else {
    box.innerHTML = `<div class="gar-trilho">${OPCOES[a].map(([k, t, s, d]) => `<button class="gar-card op ${estado.acerto[a] === k ? 'on' : ''}" data-op="${k}"><b>${esc(t)}</b><small>${esc(s)}</small><p>${esc(d)}</p></button>`).join('')}</div>`
  }
  ligarAba()
  resumo()
}
function ligarAba() {
  const box = $('#gar-opcoes')
  box.querySelectorAll('[data-modelo]').forEach((b) => (b.onclick = () => { estado.modelo = b.dataset.modelo; trocarCarro(); desenharAba() }))
  box.querySelectorAll('[data-cor]').forEach((b) => (b.onclick = () => { estado.cor = b.dataset.cor; trocarCarro(); desenharAba() }))
  const livre = $('#gar-cor'); if (livre) livre.oninput = (e) => { estado.cor = e.target.value; trocarCarro() }
  box.querySelectorAll('[data-op]').forEach((b) => (b.onclick = () => { estado.acerto[estado.aba] = b.dataset.op; graf.atualizar(estado.acerto); desenharAba() }))
  const psi = $('#gar-psi'); if (psi) psi.oninput = (e) => { estado.acerto.psi = +e.target.value; $('#gar-psi-v').textContent = e.target.value + ' psi'; $('#gar-psi-d').textContent = descPsi(+e.target.value); graf.atualizar(estado.acerto); resumo() }
  const on = box.querySelector('.on'); on?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'smooth' })
}
function trocarCarro() {
  palco.mostrar(estado.modelo, parseInt(estado.cor.slice(1), 16))
  const i = IDS.indexOf(estado.modelo)
  $('#gar-nome').textContent = MODELOS[estado.modelo].nome; $('#gar-pos').textContent = `4x4 · ${i + 1}/${IDS.length}`
}
function resumo() {
  const a = estado.acerto, n = (t, k) => OPCOES[t].find((o) => o[0] === k)?.[1]
  $('#gar-resumo').textContent = `${MODELOS[estado.modelo].nome} · pneu ${n('pneu', a.pneu)} · ${a.psi} psi · relação ${n('relacao', a.relacao)} · mapa ${n('mapa', a.mapa)}`
}
function andar(d) { const i = (IDS.indexOf(estado.modelo) + d + IDS.length) % IDS.length; estado.modelo = IDS[i]; trocarCarro(); if (estado.aba === 'modelo') desenharAba() }

export function abrirGaragem({ conta, salvar }) {
  const g = conta.garagem || {}
  estado = { aba: estado?.aba || 'modelo', modelo: MODELOS[g.modelo] ? g.modelo : 'fam3500', cor: /^#[0-9a-f]{6}$/i.test(g.cor || '') ? g.cor : '#c49a46', roda: g.roda || '#d9d9d9', acerto: { ...conta.acerto } }
  if (!palco) {
    palco = criarPalco($('#gar-cena'))
    graf = criarGrafico($('#gar-graf'))
    $('.gar-abas').innerHTML = ABAS.map(([k, n]) => `<button data-aba="${k}">${n}</button>`).join('')
    $('.gar-abas').onclick = (e) => { const k = e.target.closest('[data-aba]')?.dataset.aba; if (k) { estado.aba = k; desenharAba() } }
    $('#gar-esq').onclick = () => andar(-1); $('#gar-dir').onclick = () => andar(1)
    let x0 = null
    $('#gar-cena').addEventListener('touchstart', (e) => { x0 = e.touches[0].clientX }, { passive: true })
    $('#gar-cena').addEventListener('touchend', (e) => { if (x0 == null) return; const d = e.changedTouches[0].clientX - x0; if (Math.abs(d) > 60) andar(d < 0 ? 1 : -1); x0 = null })
    $('#gar-salvar').onclick = async () => {
      $('#gar-msg').textContent = 'Salvando…'
      try { await salvar({ acerto: estado.acerto, garagem: { modelo: estado.modelo, cor: estado.cor, roda: estado.roda } }); $('#gar-msg').textContent = 'Salvo. Esta é a caminhonete que entra na arena.' }
      catch (e) { $('#gar-msg').textContent = e.message }
    }
  }
  trocarCarro(); graf.atualizar(estado.acerto); desenharAba()
}
