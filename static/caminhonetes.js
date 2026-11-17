// Caminhonetes da Arena Bruta (three.js, geometria própria, sem arquivo externo e sem marca de terceiros).
// Estilo das grandonas americanas: cabine dupla, capô alto, grade enorme, rodado duplo atrás, luzes âmbar no teto.
// criarCaminhonete(modelo, cor, olhandoDireita) -> { g, rodas, engate, escape, nome }
// A frente fica em +x; o engate da corrente fica no para-choque traseiro.
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js'

// medidas em "metros de cena" (a cena antiga usava 5,2 de comprimento; estas têm ~6)
export const MODELOS = {
  touro3500:   { nome: 'Touro 3500',   tipo: 'pickup', dupla: true,  L: 6.2, W: 2.15, capo: 2.05, teto: 2.95, grade: 'quadrada', faroisC: false, luzesTeto: true,  chamine: true },
  brutus2500:  { nome: 'Brutus 2500',  tipo: 'pickup', dupla: false, L: 6.0, W: 2.1,  capo: 2.0,  teto: 2.9,  grade: 'dividida', faroisC: false, luzesTeto: true,  chamine: false },
  tropeiro150: { nome: 'Tropeiro 150', tipo: 'pickup', dupla: false, L: 5.8, W: 2.05, capo: 1.85, teto: 2.8,  grade: 'colmeia',  faroisC: true,  luzesTeto: false, chamine: false },
  coronel:     { nome: 'Coronel',      tipo: 'suv',    dupla: false, L: 5.6, W: 2.1,  capo: 1.9,  teto: 2.95, grade: 'vertical', faroisC: false, luzesTeto: false, chamine: false },
  tubarao:     { nome: 'Tubarão',      tipo: 'pickup', dupla: false, L: 5.7, W: 2.05, capo: 1.8,  teto: 2.75, grade: 'aberta',   faroisC: false, luzesTeto: false, chamine: false },
}

// ambiente de reflexo (sem arquivo externo): céu de pôr do sol + "softboxes"; sem isso o cromado sai preto
export function ambienteMetal(renderer) {
  const env = new THREE.Scene()
  const ceu = new THREE.ShaderMaterial({ side: THREE.BackSide, vertexShader: 'varying vec3 p; void main(){ p = position; gl_Position = projectionMatrix*modelViewMatrix*vec4(position,1.0); }',
    fragmentShader: 'varying vec3 p; void main(){ float h = normalize(p).y; vec3 c = mix(vec3(0.18,0.12,0.09), vec3(1.0,0.72,0.42), smoothstep(-0.2,0.15,h)); c = mix(c, vec3(0.55,0.6,0.75), smoothstep(0.25,0.9,h)); gl_FragColor = vec4(c,1.0); }' })
  env.add(new THREE.Mesh(new THREE.SphereGeometry(50, 32, 16), ceu))
  const luz = new THREE.MeshBasicMaterial({ color: 0xffffff })
  for (const [x, y, z, w, h] of [[0, 30, 0, 40, 6], [35, 12, 10, 4, 18], [-35, 14, -8, 4, 14]]) { const b = new THREE.Mesh(new THREE.PlaneGeometry(w, h), luz); b.position.set(x, y, z); b.lookAt(0, 0, 0); env.add(b) }
  const pm = new THREE.PMREMGenerator(renderer)
  const t = pm.fromScene(env, 0.03).texture
  pm.dispose()
  return t
}

const MAT = {
  preto: () => new THREE.MeshStandardMaterial({ color: 0x141414, metalness: 0.25, roughness: 0.7 }),
  borracha: () => new THREE.MeshStandardMaterial({ color: 0x0d0d0d, metalness: 0, roughness: 0.95 }),
  cromo: () => new THREE.MeshStandardMaterial({ color: 0xe6e6e6, metalness: 1, roughness: 0.14 }),
  vidro: () => new THREE.MeshStandardMaterial({ color: 0x0f1620, metalness: 0.9, roughness: 0.04, transparent: true, opacity: 0.88 }),
  farol: () => new THREE.MeshStandardMaterial({ color: 0xfff6dd, emissive: 0xffe2a0, emissiveIntensity: 2.2 }),
  ambar: () => new THREE.MeshStandardMaterial({ color: 0xffa21a, emissive: 0xff8a00, emissiveIntensity: 1.6 }),
  lanterna: () => new THREE.MeshStandardMaterial({ color: 0xff2414, emissive: 0xff1a0a, emissiveIntensity: 1.4 }),
}

// perfil lateral da carroceria (x = comprimento, y = altura), com as caixas de roda recortadas
function perfil(m, eixoD, eixoT, raioCaixa) {
  const h = m.L / 2, base = 0.78, s = new THREE.Shape()
  const cabTras = m.tipo === 'suv' ? -h + 0.25 : -0.65
  s.moveTo(-h, base + 0.05)
  s.lineTo(-h, m.tipo === 'suv' ? m.teto - 0.35 : m.capo - 0.12)                    // traseira
  if (m.tipo === 'suv') { s.lineTo(-h + 0.25, m.teto) }                             // SUV: teto vai até o fim
  else { s.lineTo(cabTras - 0.02, m.capo - 0.12); s.lineTo(cabTras, m.teto - 0.05) } // borda da caçamba e coluna traseira da cabine
  s.lineTo(0.55, m.teto)                                                            // teto
  s.lineTo(1.35, m.capo + 0.08)                                                     // para-brisa inclinado
  s.lineTo(h - 0.18, m.capo)                                                        // capô
  s.lineTo(h, m.capo - 0.12)
  s.lineTo(h, base + 0.12)                                                          // frente
  s.lineTo(eixoD + raioCaixa, base)
  s.absarc(eixoD, base, raioCaixa, 0, Math.PI, false)                               // caixa de roda dianteira
  s.lineTo(eixoT + raioCaixa, base)
  s.absarc(eixoT, base, raioCaixa, 0, Math.PI, false)                               // caixa de roda traseira
  s.lineTo(-h, base + 0.05)
  return { s, cabTras }
}

function roda(raio, largura, dupla, lado) {
  const r = new THREE.Group()
  const borr = MAT.borracha(), cromo = MAT.cromo(), preto = MAT.preto()
  const pneu = new THREE.Mesh(new THREE.CylinderGeometry(raio, raio, largura, 32), borr)
  pneu.rotation.x = Math.PI / 2; pneu.castShadow = true; r.add(pneu)
  // banda de rodagem (gomos) para o pneu girar de forma visível
  for (let i = 0; i < 26; i++) {
    const t = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.03, largura * 0.92), borr)
    const a = (i / 26) * Math.PI * 2
    t.position.set(Math.cos(a) * raio, Math.sin(a) * raio, 0); t.rotation.z = a; r.add(t)
  }
  const prato = dupla ? 0.12 : 0.03 // roda de rodado duplo tem a "panela" funda
  const aro = new THREE.Mesh(new THREE.CylinderGeometry(raio * 0.62, raio * 0.62, 0.06, 28), cromo)
  aro.rotation.x = Math.PI / 2; aro.position.z = lado * (largura / 2 + 0.01 - prato); r.add(aro)
  const cubo = new THREE.Mesh(new THREE.CylinderGeometry(raio * 0.2, raio * 0.24, 0.12 + prato, 16), cromo)
  cubo.rotation.x = Math.PI / 2; cubo.position.z = lado * (largura / 2 + 0.02 - prato / 2); r.add(cubo)
  for (let i = 0; i < 8; i++) { // porcas e raios
    const a = (i / 8) * Math.PI * 2
    const raioRaio = new THREE.Mesh(new THREE.BoxGeometry(raio * 0.36, 0.07, 0.05), i % 2 ? preto : cromo)
    raioRaio.position.set(Math.cos(a) * raio * 0.38, Math.sin(a) * raio * 0.38, lado * (largura / 2 + 0.03 - prato)); raioRaio.rotation.z = a; r.add(raioRaio)
  }
  return r
}

export function criarCaminhonete(modelo, cor, olhandoDireita) {
  const m = MODELOS[modelo] || MODELOS.touro3500
  const g = new THREE.Group()
  const pint = new THREE.MeshStandardMaterial({ color: cor, metalness: 0.7, roughness: 0.28 })
  const preto = MAT.preto(), cromo = MAT.cromo(), vidro = MAT.vidro()
  const add = (geo, mat, x, y, z, pai = g) => { const o = new THREE.Mesh(geo, mat); o.position.set(x, y, z); o.castShadow = o.receiveShadow = true; pai.add(o); return o }
  const h = m.L / 2, W = m.W
  const eixoD = h - 1.15, eixoT = m.tipo === 'suv' ? -h + 1.25 : -h + 1.45
  const raioRoda = m.dupla ? 0.6 : 0.58, raioCaixa = raioRoda + 0.1

  // carroceria: perfil extrudado na largura, com chanfro nas bordas
  const { s, cabTras } = perfil(m, eixoD, eixoT, raioCaixa)
  const corpo = new THREE.ExtrudeGeometry(s, { depth: W, bevelEnabled: true, bevelThickness: 0.06, bevelSize: 0.05, bevelSegments: 3, curveSegments: 20 })
  corpo.translate(0, 0, -W / 2)
  add(corpo, pint, 0, 0, 0)

  // vidros: laterais (um bloco um pouco mais largo que a carroceria), para-brisa e vigia traseira
  const jan = new THREE.Shape()
  const y0 = m.capo + 0.12, topo = m.teto - 0.1
  const xa = m.tipo === 'suv' ? -h + 0.45 : cabTras + 0.12
  jan.moveTo(xa, y0); jan.lineTo(xa, topo - 0.02); jan.lineTo(0.5, topo); jan.lineTo(1.2, y0 + 0.05); jan.lineTo(xa, y0)
  const jg = new THREE.ExtrudeGeometry(jan, { depth: W + 0.13, bevelEnabled: false }); jg.translate(0, 0, -(W + 0.13) / 2)
  add(jg, vidro, 0, 0, 0)
  // colunas entre as portas (cabine dupla) e maçanetas
  const colX = m.tipo === 'suv' ? [-0.9, 0.05] : [(xa + 0.5) / 2]
  for (const cx of colX) add(new THREE.BoxGeometry(0.12, topo - y0, W + 0.16), pint, cx, (topo + y0) / 2, 0)
  for (const cx of [0.75, colX[0] - 0.35]) for (const z of [1, -1]) add(new THREE.BoxGeometry(0.22, 0.05, 0.04), cromo, cx, m.capo - 0.05, z * (W / 2 + 0.08))
  // para-brisa
  // para-brisa: plano sobre a linha teto->capô, virado para fora (normal = (queda, avanço) normalizado)
  const pa = 1.35 - 0.55, pq = m.teto - m.capo - 0.08, pb = Math.hypot(pa, pq), nx = pq / pb, ny = pa / pb
  const para = add(new THREE.PlaneGeometry(W - 0.22, pb * 0.9), vidro, (0.55 + 1.35) / 2 + nx * 0.07, (m.teto + m.capo + 0.08) / 2 + ny * 0.07, 0)
  para.lookAt(para.position.x + nx, para.position.y + ny, 0)
  if (m.tipo === 'pickup') { // vigia traseira
    const vig = add(new THREE.PlaneGeometry(W - 0.5, 0.42), vidro, cabTras - 0.08, m.teto - 0.35, 0)
    vig.lookAt(vig.position.x - 1, vig.position.y, 0)
  }

  // caçamba: borda preta e capota marítima; SUV: rack de teto
  if (m.tipo === 'pickup') {
    add(new THREE.BoxGeometry(h + cabTras - 0.15, 0.05, W - 0.05), preto, (-h + cabTras) / 2, m.capo - 0.07, 0)
    for (const z of [1, -1]) add(new THREE.BoxGeometry(h + cabTras - 0.1, 0.08, 0.08), cromo, (-h + cabTras) / 2, m.capo - 0.05, z * (W / 2 - 0.02))
  } else {
    for (const z of [1, -1]) add(new THREE.BoxGeometry(2.6, 0.06, 0.06), cromo, -0.6, m.teto + 0.12, z * (W / 2 - 0.25))
  }

  // frente: grade (cada modelo com o seu estilo), faróis, para-choque
  const gx = h + 0.06, gy = (m.capo + 0.95) / 2 + 0.1, gh = m.capo - 1.0, gw = W * (m.grade === 'colmeia' ? 0.62 : 0.74)
  add(new THREE.BoxGeometry(0.1, gh + 0.12, gw + 0.12), cromo, gx, gy, 0)               // moldura
  add(new THREE.BoxGeometry(0.11, gh, gw), preto, gx + 0.01, gy, 0)                     // fundo
  if (m.grade === 'quadrada' || m.grade === 'aberta') for (let i = 1; i <= 3; i++) add(new THREE.BoxGeometry(0.13, 0.06, gw), cromo, gx + 0.02, gy - gh / 2 + (i * gh) / 4, 0)
  if (m.grade === 'dividida') add(new THREE.BoxGeometry(0.15, 0.16, W - 0.05), pint, gx + 0.03, gy + 0.05, 0)
  if (m.grade === 'colmeia') for (let i = 0; i < 6; i++) for (let j = 0; j < 4; j++) add(new THREE.BoxGeometry(0.13, 0.05, 0.05), cromo, gx + 0.02, gy - gh / 2 + 0.1 + j * (gh / 4), -gw / 2 + 0.1 + i * (gw / 6))
  if (m.grade === 'vertical') for (let i = 0; i < 9; i++) add(new THREE.BoxGeometry(0.13, gh, 0.04), cromo, gx + 0.02, gy, -gw / 2 + 0.08 + i * (gw / 9))
  const farol = MAT.farol()
  for (const z of [1, -1]) {
    const fz = z * (gw / 2 + (W / 2 - gw / 2) / 2 + 0.02)
    if (m.faroisC) { // faróis em "C"
      add(new THREE.BoxGeometry(0.06, 0.06, 0.32), farol, gx, gy + gh / 2 - 0.08, fz)
      add(new THREE.BoxGeometry(0.06, gh * 0.6, 0.06), farol, gx, gy, fz + z * 0.13)
      add(new THREE.BoxGeometry(0.06, 0.06, 0.32), farol, gx, gy - gh * 0.3, fz)
    } else {
      add(new THREE.BoxGeometry(0.08, gh * 0.55, W / 2 - gw / 2 - 0.08), preto, gx - 0.01, gy + gh * 0.15, fz)
      add(new THREE.BoxGeometry(0.06, 0.07, W / 2 - gw / 2 - 0.12), farol, gx + 0.03, gy + gh * 0.3, fz)
      add(new THREE.BoxGeometry(0.06, 0.12, 0.18), farol, gx + 0.03, gy + gh * 0.08, fz)
    }
  }
  add(new THREE.BoxGeometry(0.32, 0.42, W + 0.12), m.tipo === 'suv' ? cromo : cromo, h + 0.14, 1.0, 0)       // para-choque
  add(new THREE.BoxGeometry(0.2, 0.12, W - 0.4), preto, h + 0.26, 0.9, 0)                                      // entrada de ar inferior
  for (const z of [1, -1]) add(new THREE.BoxGeometry(0.06, 0.08, 0.3), MAT.ambar(), h + 0.31, 1.12, z * (W / 2 - 0.15)) // pisca

  // luzes âmbar de teto (marca das grandonas) e chaminé
  if (m.luzesTeto) for (let i = -2; i <= 2; i++) add(new THREE.BoxGeometry(0.1, 0.06, 0.14), MAT.ambar(), 0.48, m.teto + 0.03, i * 0.32)
  let escapeY = 1.0, escapeX = -h + 0.3, escapeZ = W / 2 - 0.25
  if (m.chamine) { add(new THREE.CylinderGeometry(0.08, 0.1, 1.3, 14), cromo, cabTras - 0.12, m.capo + 0.55, W / 2 - 0.12); escapeY = m.capo + 1.25; escapeX = cabTras - 0.12; escapeZ = W / 2 - 0.12 }

  // traseira: lanternas, para-choque de degrau, para-barros
  const lant = MAT.lanterna()
  for (const z of [1, -1]) {
    if (m.tipo === 'suv') add(new THREE.BoxGeometry(0.06, 1.0, 0.12), lant, -h - 0.05, m.teto - 0.95, z * (W / 2 - 0.08)) // lanternas verticais
    else add(new THREE.BoxGeometry(0.06, 0.42, 0.18), lant, -h - 0.05, m.capo - 0.45, z * (W / 2 - 0.1))
  }
  add(new THREE.BoxGeometry(0.3, 0.3, W + 0.05), cromo, -h - 0.12, 0.95, 0)
  if (m.tipo === 'pickup') add(new THREE.BoxGeometry(0.05, 0.08, 0.34), cromo, -h - 0.06, m.capo - 0.32, 0)    // puxador da tampa
  add(new THREE.BoxGeometry(0.32, 0.06, 0.6), preto, -h - 0.14, 1.12, 0)                                       // degrau

  // laterais: estribos, retrovisores de reboque, alargadores
  for (const z of [1, -1]) {
    add(new THREE.BoxGeometry(eixoD - eixoT - 1.6, 0.08, 0.32), preto, (eixoD + eixoT) / 2, 0.72, z * (W / 2 + 0.12))
    const braco = add(new THREE.BoxGeometry(0.08, 0.06, 0.38), preto, 1.18, m.capo + 0.32, z * (W / 2 + 0.2))
    add(new THREE.BoxGeometry(0.1, 0.42, 0.26), preto, 1.18, m.capo + 0.32, z * (W / 2 + 0.42))
    add(new THREE.BoxGeometry(0.03, 0.36, 0.2), cromo, 1.12, m.capo + 0.32, z * (W / 2 + 0.42))
    void braco
    // alargadores pretos sobre as caixas de roda
    for (const [ex, larg] of [[eixoD, 0.18], [eixoT, m.dupla ? 0.46 : 0.18]]) {
      const f = add(new THREE.TorusGeometry(raioCaixa + 0.05, 0.08, 8, 24, Math.PI), preto, ex, 0.78, z * (W / 2 + larg / 2 + (m.dupla && ex === eixoT ? 0.08 : 0)))
      f.scale.z = larg / 0.16
    }
    if (m.dupla) { // para-lama largo do rodado duplo: perfil arredondado com o recorte da roda
      const pf = new THREE.Shape(), x0 = eixoT - 1.0, x1 = eixoT + 1.0, yb = 0.82, yt = m.capo - 0.18, rr = 0.28
      pf.moveTo(x0, yb); pf.lineTo(x0, yt - rr); pf.quadraticCurveTo(x0, yt, x0 + rr, yt); pf.lineTo(x1 - rr, yt); pf.quadraticCurveTo(x1, yt, x1, yt - rr)
      pf.lineTo(x1, yb); pf.lineTo(eixoT + raioCaixa, yb); pf.absarc(eixoT, 0.78, raioCaixa, 0, Math.PI, false); pf.lineTo(x0, yb)
      const pg = new THREE.ExtrudeGeometry(pf, { depth: 0.36, bevelEnabled: true, bevelThickness: 0.08, bevelSize: 0.07, bevelSegments: 4, curveSegments: 18 })
      add(pg, pint, 0, 0, z > 0 ? W / 2 - 0.05 : -W / 2 + 0.05 - 0.36)
    }
  }

  // rodas: rodado duplo = duas rodas por lado atrás
  const rodas = []
  const larg = 0.42
  const pos = [[eixoD, W / 2 - 0.12], [eixoT, W / 2 - 0.12]]
  for (const [x, zz] of pos) for (const z of [1, -1]) {
    const r = roda(raioRoda, larg, false, z); r.position.set(x, raioRoda, z * zz); g.add(r); rodas.push(r)
  }
  if (m.dupla) for (const z of [1, -1]) { const r = roda(raioRoda, larg, true, z); r.position.set(eixoT, raioRoda, z * (W / 2 + 0.33)); g.add(r); rodas.push(r) }

  const engate = new THREE.Object3D(); engate.position.set(-h - 0.35, 0.85, 0); g.add(engate)
  add(new THREE.BoxGeometry(0.4, 0.1, 0.1), cromo, -h - 0.25, 0.85, 0)                                         // bola do engate
  const escape = new THREE.Object3D(); escape.position.set(escapeX, escapeY, escapeZ); g.add(escape)
  if (!olhandoDireita) g.rotation.y = Math.PI
  return { g, rodas, engate, escape, nome: m.nome }
}
