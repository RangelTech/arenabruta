// Cena 3D da Arena Bruta (three.js): duas caminhonetes puxando a corrente na poeira do pôr do sol.
// criarCena(canvas, { modo: 'heroi' | 'jogo' }) -> { atualizar(estado), destruir() }
// estado = { pos (-10000..10000), a:{rpm,forca,acel,temp,fervendo,patinou}, b:{...} }  (só visual: quem decide é o servidor)
import * as THREE from 'three'
import { criarCaminhonete, ambienteMetal, MODELOS } from './caminhonetes.js'
export { MODELOS }

const COR = { carvao: 0x121212, ouro: 0xc49a46, couro: 0x63402a, militar: 0x334532, bege: 0xe9dbc4 }

function texturaChao() {
  const c = document.createElement('canvas'); c.width = c.height = 512
  const g = c.getContext('2d')
  g.fillStyle = '#7a5a3a'; g.fillRect(0, 0, 512, 512)
  // grão e marcas de pneu (padrão fixo: nada aleatório, para a cena ficar sempre igual)
  for (let i = 0; i < 9000; i++) {
    const x = (i * 97) % 512, y = (i * 389 + (i >> 3) * 13) % 512
    const v = 90 + ((i * 53) % 70)
    g.fillStyle = `rgba(${v + 40},${v + 10},${v - 25},0.35)`
    g.fillRect(x, y, 2, 2)
  }
  g.strokeStyle = 'rgba(40,25,15,.35)'; g.lineWidth = 10
  for (let k = 0; k < 4; k++) { g.beginPath(); g.moveTo(0, 150 + k * 60); g.bezierCurveTo(170, 120 + k * 64, 340, 190 + k * 52, 512, 150 + k * 60); g.stroke() }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.repeat.set(10, 10); t.anisotropy = 4
  return t
}

export function criarCena(canvas, opcoes = {}) {
  const modo = opcoes.modo || 'jogo'
  const reduzir = matchMedia('(prefers-reduced-motion: reduce)').matches
  const r = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false })
  r.setPixelRatio(Math.min(2, devicePixelRatio || 1))
  r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap
  r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 1.05
  const cena = new THREE.Scene()
  cena.environment = ambienteMetal(r)  // reflexo para o cromado e a pintura metálica
  cena.background = new THREE.Color(0x2a1a12)
  cena.fog = new THREE.Fog(0x3a2418, 30, 95)
  // céu de pôr do sol (esfera com gradiente)
  const ceuMat = new THREE.ShaderMaterial({ side: THREE.BackSide, uniforms: {}, vertexShader: 'varying vec3 p; void main(){ p = position; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
    fragmentShader: 'varying vec3 p; void main(){ float h = normalize(p).y; vec3 c = mix(vec3(0.95,0.55,0.22), vec3(0.16,0.09,0.12), smoothstep(-0.05,0.45,h)); c = mix(c, vec3(1.0,0.78,0.42), smoothstep(0.0,0.06,0.06-abs(h-0.02))*0.6); gl_FragColor = vec4(c,1.0); }' })
  cena.add(new THREE.Mesh(new THREE.SphereGeometry(200, 32, 16), ceuMat))
  const cam = new THREE.PerspectiveCamera(modo === 'heroi' ? 34 : 40, 1, 0.1, 400)
  cena.add(new THREE.HemisphereLight(0xffe2b8, 0x4a3020, 1.15))
  const contra = new THREE.DirectionalLight(0xff9a4a, 1.1); contra.position.set(10, 8, -30); cena.add(contra)  // luz de contorno do pôr do sol
  const sol = new THREE.DirectionalLight(0xffc27a, 2.4)
  sol.position.set(-22, 26, 28); sol.castShadow = true
  sol.shadow.mapSize.set(2048, 2048); Object.assign(sol.shadow.camera, { left: -30, right: 30, top: 20, bottom: -20, far: 120 })
  cena.add(sol)
  const chao = new THREE.Mesh(new THREE.PlaneGeometry(220, 220), new THREE.MeshStandardMaterial({ map: texturaChao(), roughness: 1 }))
  chao.rotation.x = -Math.PI / 2; chao.receiveShadow = true; cena.add(chao)
  // faixa central (linha de vitória dos dois lados) e cercas de rodeio
  const linha = (x, cor) => { const m = new THREE.Mesh(new THREE.PlaneGeometry(0.35, 9), new THREE.MeshStandardMaterial({ color: cor, emissive: cor, emissiveIntensity: 0.35 })); m.rotation.x = -Math.PI / 2; m.position.set(x, 0.02, 0); cena.add(m) }
  linha(0, 0xe9dbc4); linha(-10, COR.ouro); linha(10, COR.ouro)
  const madeira = new THREE.MeshStandardMaterial({ color: 0x5a3a22, roughness: 0.9 })
  for (const z of [-7.5]) {  // só a cerca do fundo: a da frente tapava a cena
    for (let x = -36; x <= 36; x += 4) { const p = new THREE.Mesh(new THREE.BoxGeometry(0.25, 1.6, 0.25), madeira); p.position.set(x, 0.8, z); p.castShadow = true; cena.add(p) }
    for (const y of [0.55, 1.25]) { const t = new THREE.Mesh(new THREE.BoxGeometry(72, 0.18, 0.12), madeira); t.position.set(0, y, z); cena.add(t) }
  }
  let A = criarCaminhonete(opcoes.modeloA || 'fam3500', opcoes.corA ?? COR.ouro, false)   // a da esquerda puxa para a esquerda (pos > 0)
  let B = criarCaminhonete(opcoes.modeloB || 's150', opcoes.corB ?? COR.militar, true)
  cena.add(A.g, B.g)
  // piso de cada cenário (spec 46 §4): cor do chão e da névoa
  const PISO = { curral: [0x7a5a3a, 0x3a2418], terra: [0x9a6a44, 0x4a2c18], compactada: [0x8a6a50, 0x3a2a20], lama: [0x4e3c2a, 0x2a2420],
                 areia_arena: [0xc9a878, 0x3a2c22], praia: [0xead6a6, 0x7a6a5a], arena: [0x8a5a3a, 0x24161a] }
  function trocar(o = {}) {
    if (o.modeloA || o.corA != null) { cena.remove(A.g); A = criarCaminhonete(o.modeloA || 'fam3500', o.corA ?? COR.ouro, false); cena.add(A.g) }
    if (o.modeloB || o.corB != null) { cena.remove(B.g); B = criarCaminhonete(o.modeloB || 's150', o.corB ?? COR.militar, true); cena.add(B.g) }
    const p = PISO[o.piso]
    if (p) { chao.material.color.setHex(p[0]).multiplyScalar(1.6); cena.fog.color.setHex(p[1]); cena.background.setHex(p[1]) }
  }
  if (opcoes.piso) trocar({ piso: opcoes.piso })
  // corrente: elos alternados entre os engates
  const elos = []
  const eloGeo = new THREE.TorusGeometry(0.16, 0.05, 8, 16)
  const aco = new THREE.MeshStandardMaterial({ color: 0x9a9a9a, metalness: 1, roughness: 0.35 })
  for (let i = 0; i < 26; i++) { const e = new THREE.Mesh(eloGeo, aco); e.castShadow = true; cena.add(e); elos.push(e) }
  // poeira e fumaça (partículas com ciclo fixo)
  // partícula redonda e esfumaçada (sem textura o ponto sai quadrado e a fumaça parecia uma caixa preta voando)
  const bolinha = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 64
    const g = c.getContext('2d'), gr = g.createRadialGradient(32, 32, 0, 32, 32, 32)
    gr.addColorStop(0, 'rgba(255,255,255,1)'); gr.addColorStop(0.45, 'rgba(255,255,255,.55)'); gr.addColorStop(1, 'rgba(255,255,255,0)')
    g.fillStyle = gr; g.fillRect(0, 0, 64, 64)
    return new THREE.CanvasTexture(c)
  })()
  function nuvem(cor, n, tam) {
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(n * 3), 3))
    const mat = new THREE.PointsMaterial({ color: cor, size: tam * 1.6, map: bolinha, transparent: true, opacity: 0.5, depthWrite: false, sizeAttenuation: true })
    const pts = new THREE.Points(geo, mat); cena.add(pts)
    return { pts, n, vida: new Float32Array(n), base: new Float32Array(n * 3) }
  }
  const poeiraA = nuvem(0xc9a07a, 160, 0.55), poeiraB = nuvem(0xc9a07a, 160, 0.55)
  const fumacaA = nuvem(0x1a1a1a, 70, 0.9), fumacaB = nuvem(0x1a1a1a, 70, 0.9)

  let estado = { pos: 0, a: { rpm: 900, forca: 0, acel: 0, temp: 0 }, b: { rpm: 900, forca: 0, acel: 0, temp: 0 } }
  let posVis = 0, t0 = performance.now(), raf = 0, sem = 0
  function tamanho() {
    const w = canvas.clientWidth || innerWidth, h = canvas.clientHeight || innerHeight
    r.setSize(w, h, false); cam.aspect = w / h; cam.updateProjectionMatrix()
  }
  addEventListener('resize', tamanho); tamanho()

  function emitir(nv, origem, forca, sobe) {
    const p = nv.pts.geometry.attributes.position.array
    for (let i = 0; i < nv.n; i++) {
      nv.vida[i] -= 0.016 * (1 + forca)
      if (nv.vida[i] <= 0 && forca > 0.05) {
        sem = (sem * 1103515245 + 12345) & 0x7fffffff  // sequência fixa (efeito visual, nunca entra no jogo)
        const j = (sem % 1000) / 1000
        nv.vida[i] = 1; nv.base[i * 3] = origem.x + (j - 0.5) * 0.8; nv.base[i * 3 + 1] = origem.y; nv.base[i * 3 + 2] = origem.z + (j - 0.5) * 1.6
      }
      const v = Math.max(0, nv.vida[i]), k = 1 - v
      p[i * 3] = nv.base[i * 3] + (sobe ? k * 0.6 : (origem.lado || 1) * k * 2.4)
      p[i * 3 + 1] = nv.base[i * 3 + 1] + k * (sobe ? 3.2 : 1.2)
      p[i * 3 + 2] = nv.base[i * 3 + 2] + Math.sin(i + k * 3) * k * 0.6
    }
    nv.pts.geometry.attributes.position.needsUpdate = true
    nv.pts.material.opacity = 0.15 + Math.min(0.5, forca * 0.6)
  }

  function quadro() {
    const t = (performance.now() - t0) / 1000
    let e = estado
    if (modo === 'heroi') {  // vai e volta sozinho: cabo de guerra eterno na landing
      const s = Math.sin(t * 0.55) * 0.55 + Math.sin(t * 1.7) * 0.12
      e = { pos: s * 5200, a: { rpm: 4300 + Math.sin(t * 2) * 900, forca: 0.8, acel: 1, temp: 300 }, b: { rpm: 4100 + Math.cos(t * 2.2) * 900, forca: 0.8, acel: 1, temp: 300 } }
    }
    posVis += (e.pos - posVis) * 0.18
    const desloc = posVis / 10000 * 10  // a corrente anda até 10 m para cada lado
    const vib = (c) => (c.acel ? Math.sin(t * (c.rpm / 60)) * 0.02 : 0)
    // positivo = corrente puxada para a esquerda (lado A ganhando)
    A.g.position.x = -6.4 - desloc
    B.g.position.x = 6.4 - desloc
    A.g.position.y = vib(e.a) + 0.0; B.g.position.y = vib(e.b)
    A.g.rotation.z = (e.a.acel ? 0.035 : 0); B.g.rotation.z = -(e.b.acel ? 0.035 : 0)
    const giro = (c) => (c.acel ? 0.25 + c.rpm / 9000 : 0.04)
    A.rodas.forEach((w) => (w.rotation.z += giro(e.a)))   // a roda inteira gira (banda de rodagem e raios)
    B.rodas.forEach((w) => (w.rotation.z -= giro(e.b)))
    // corrente esticada com leve barriga
    const pa = new THREE.Vector3(), pb = new THREE.Vector3()
    A.engate.getWorldPosition(pa); B.engate.getWorldPosition(pb)
    const tensao = Math.min(1, (e.a.forca > 2 ? e.a.forca / 44000 : e.a.forca || 0) + (e.b.forca > 2 ? e.b.forca / 44000 : e.b.forca || 0))
    elos.forEach((el, i) => {
      const k = i / (elos.length - 1)
      el.position.lerpVectors(pa, pb, k)
      el.position.y -= Math.sin(k * Math.PI) * (0.35 - tensao * 0.3)
      el.rotation.set(i % 2 ? Math.PI / 2 : 0, 0, 0)
    })
    // força do servidor vem em unidades do motor (até ~44.000); na landing já vem de 0 a 1
    const norma = (f) => Math.min(1, f > 2 ? f / 44000 : f || 0)
    const fA = norma(e.a.forca), fB = norma(e.b.forca)
    if (!reduzir) {
      emitir(poeiraA, { x: A.g.position.x + 1.6, y: 0.4, z: 0, lado: 1 }, e.a.acel ? 0.4 + fA : 0, false)
      emitir(poeiraB, { x: B.g.position.x - 1.6, y: 0.4, z: 0, lado: -1 }, e.b.acel ? 0.4 + fB : 0, false)
      const pe = new THREE.Vector3()
      A.escape.getWorldPosition(pe); emitir(fumacaA, pe, e.a.acel ? 0.25 + Math.min(1, (e.a.temp || 0) / 700) : 0, true)
      B.escape.getWorldPosition(pe); emitir(fumacaB, pe, e.b.acel ? 0.25 + Math.min(1, (e.b.temp || 0) / 700) : 0, true)
    }
    // câmera de cinema: lateral baixa, acompanha a corrente e respira
    const cx = -desloc * 0.6
    if (modo === 'heroi') cam.position.set(cx + 7 + Math.sin(t * 0.12) * 3, 4.2 + Math.sin(t * 0.3) * 0.3, 16 + Math.cos(t * 0.12) * 1.5)
    else cam.position.set(cx, 5.2, 20.5)
    cam.lookAt(cx, 1.6, 0)
    r.render(cena, cam)
    raf = requestAnimationFrame(quadro)
  }
  quadro()
  return {
    atualizar(s) { estado = s },
    trocar,
    tamanho,
    destruir() { cancelAnimationFrame(raf); r.dispose() },
  }
}
