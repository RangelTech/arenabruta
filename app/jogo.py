"""Cabo de Guerra Diesel, MOTOR v3: acerto no Box (pneu, calibragem, relação, mapa) + piso de cada cenário.

Regras que não quebram (spec 45 §H, spec 46 §9):
- ZERO aleatoriedade: só inteiros, passo fixo (20 ticks/s, 30 s = 600 ticks). Mesmas entradas -> mesmo resultado (replay = refazer
  a conta). NUNCA usar random, secrets, uuid, time ou hash aqui (o teste test_sem_aleatoriedade varre este arquivo).
- O servidor é a autoridade: o cliente manda só acelerar/marcha; o acerto vem do Box (fixo durante a partida).
- MERITOCRACIA POR EQUIVALÊNCIA: os 6 estilos (3 relações x 2 mapas), pilotados no ótimo com o pneu/psi certo do piso, entregam a
  MESMA força total (tabela NORMA, gerada por calibrar(); teste: ±1%). O estilo muda COMO pilotar, não QUEM ganha.
- Bots: PERFIS (estilos diferentes, todos competitivos, um defeito fixo cada); no PvP entra o perfil por rodízio fixo.
  O modo história usa a escada 1..20 (grátis).

Física (unidades inteiras):
  força do motor  = torque_mapa(rpm) x relação(marcha) x fator_relação
  aderência máx   = μ(pneu, piso) x parábola(psi - psi_ideal) x CARGA
  se força > aderência -> PATINA: sobra 70% da aderência (atrito dinâmico)
  temperatura sobe acima do limiar do mapa; a 1000 ferve (metade da força por 3 s)
  força final     = força x NORMA[estilo][piso] / 1000   (equivalência entre estilos)
"""
from __future__ import annotations

from app.calibragem import NORMA

TICKS_S = 20
DURACAO = 30 * TICKS_S
CHEGADA = 10000          # posição da corrente que dá vitória
EMPATE = 250             # |posição| abaixo disso no fim = empate (devolve tudo)
RPM_MIN, RPM_MAX = 800, 7000
ACEL = [0, 230, 170, 125, 95, 72]       # quanto o giro sobe por tick em cada marcha (relação média)
RELACAO = [0, 44, 33, 25, 19, 15]       # força multiplicada pela marcha (curta = força)
PESO_CORRENTE = 150       # oscilação entre estilos ótimos chega a ~1,1 mi de força acumulada: 150 mantém a corrente longe da linha entre iguais (spec 46)
CARGA = 40               # aderência máxima = μ (por mil) x CARGA  (μ 1000 -> 40.000, que é a força da 1ª marcha no pico)
VERSAO_MOTOR = 3

# ---------------- Box: o acerto da caminhonete ----------------
PNEUS = {"liso": "Liso de estrada (A/T leve)", "misto": "Misto (A/T)", "cravo": "Cravo lameiro (M/T)"}
RELACOES = {"curta": (115, 115), "media": (100, 100), "longa": (87, 87)}   # (força %, subida de giro %)
MAPAS = {"torque": {"nome": "Torque (força embaixo)", "pico": (2800, 3800), "cai_ate": 150, "limiar": 5200},
         "potencia": {"nome": "Potência (força em cima)", "pico": (4800, 5800), "cai_ate": 600, "limiar": 6200}}
PSI_MIN, PSI_MAX = 15, 45
ESTILOS = [f"{r}-{m}" for r in RELACOES for m in MAPAS]            # 6 estilos equivalentes

# pisos: μ de pico (por mil) e psi ideal de cada pneu
PISOS = {
    "curral": {"nome": "Terra batida", "liso": (860, 34), "misto": (880, 30), "cravo": (850, 26)},
    "terra":  {"nome": "Terra seca e cascalho", "liso": (820, 32), "misto": (880, 28), "cravo": (860, 24)},
    "compactada": {"nome": "Terra compactada", "liso": (900, 36), "misto": (880, 32), "cravo": (800, 28)},
    "lama":   {"nome": "Lama", "liso": (450, 24), "misto": (700, 22), "cravo": (920, 18)},
    "areia_arena": {"nome": "Areia de arena", "liso": (600, 22), "misto": (760, 20), "cravo": (800, 18)},
    "praia":  {"nome": "Areia fofa de praia", "liso": (520, 18), "misto": (720, 16), "cravo": (740, 15)},
    "arena":  {"nome": "Terra de arena de rodeio", "liso": (850, 34), "misto": (880, 30), "cravo": (860, 26)},
}
# cenário de cada arena (spec 46 §4): nome da cena e piso
CENARIOS = {
    "treino": ("Curral da fazenda", "curral"),
    "peao": ("Estrada da soja", "terra"),
    "cowboy": ("Pecuária de Goiânia", "compactada"),
    "bruto": ("Atoleiro do Pantanal", "lama"),
    "fazendeiro": ("Rodeio de Jaguariúna", "areia_arena"),
    "barao": ("Praia de BC", "praia"),
    "rei": ("Arena de Barretos", "arena"),
}
ACERTO_PADRAO = {"pneu": "misto", "psi": 30, "relacao": "media", "mapa": "torque"}


def validar_acerto(d: dict | None) -> dict:
    d = d or {}
    out = dict(ACERTO_PADRAO)
    if d.get("pneu") in PNEUS:
        out["pneu"] = d["pneu"]
    try:
        out["psi"] = max(PSI_MIN, min(PSI_MAX, int(d.get("psi", out["psi"]))))
    except (TypeError, ValueError):
        pass
    if d.get("relacao") in RELACOES:
        out["relacao"] = d["relacao"]
    if d.get("mapa") in MAPAS:
        out["mapa"] = d["mapa"]
    return out


def estilo(acerto: dict) -> str:
    return f"{acerto['relacao']}-{acerto['mapa']}"


def mu_efetivo(acerto: dict, piso: str) -> int:
    """μ (por mil) do pneu neste piso com esta calibragem: parábola em volta do psi ideal (pouco é ruim, demais é ruim)."""
    pico, ideal = PISOS[piso][acerto["pneu"]]
    d = acerto["psi"] - ideal
    return pico * max(450, 1000 - 4 * d * d) // 1000


def torque(mapa: str, rpm: int) -> int:
    """Curva de torque do diesel (0 a 1000) para o mapa escolhido."""
    m = MAPAS[mapa]
    a, b = m["pico"]
    if rpm < a:
        return max(120, 120 + (rpm - RPM_MIN) * 880 // (a - RPM_MIN))
    if rpm <= b:
        return 1000
    return max(m["cai_ate"], 1000 - (rpm - b) * (1000 - m["cai_ate"]) // (RPM_MAX - b))


def novo_carro(acerto: dict | None = None, piso: str = "curral") -> dict:
    ac = validar_acerto(acerto)
    return {"rpm": RPM_MIN, "marcha": 1, "temp": 0, "acel": 0, "fervendo": 0, "forca": 0, "patinou": 0,
            "acerto": ac, "piso": piso, "mu": mu_efetivo(ac, piso), "norma": NORMA[piso][estilo(ac)]}


def aplicar(c: dict, cmd: dict) -> None:
    """Comando já validado: acel 0/1, marcha +1/-1 (o acerto não muda durante a partida)."""
    if "acel" in cmd:
        c["acel"] = 1 if cmd["acel"] else 0
    if cmd.get("marcha") in (1, -1):
        nova = min(5, max(1, c["marcha"] + cmd["marcha"]))
        if nova != c["marcha"]:
            c["rpm"] = max(RPM_MIN, min(RPM_MAX, c["rpm"] * RELACAO[nova] // RELACAO[c["marcha"]]))
            c["marcha"] = nova


def passo_carro(c: dict) -> int:
    ac = c["acerto"]
    forca_rel, sobe_rel = RELACOES[ac["relacao"]]
    if c["acel"]:
        c["rpm"] = min(RPM_MAX, c["rpm"] + ACEL[c["marcha"]] * sobe_rel // 100)
    else:
        c["rpm"] = max(RPM_MIN, c["rpm"] - 160)
    limiar = MAPAS[ac["mapa"]]["limiar"]
    if c["rpm"] > limiar:
        c["temp"] = min(1000, c["temp"] + (c["rpm"] - limiar) // 40)
    else:
        c["temp"] = max(0, c["temp"] - 4)
    if c["temp"] >= 1000 and not c["fervendo"]:
        c["fervendo"] = 3 * TICKS_S
    if c["fervendo"]:
        c["fervendo"] -= 1
        if not c["fervendo"]:
            c["temp"] = 600
    motor = torque(ac["mapa"], c["rpm"]) * RELACAO[c["marcha"]] * forca_rel // 100
    if not c["acel"]:
        motor //= 6
    chao = c["mu"] * CARGA
    if motor > chao and c["acel"]:
        c["patinou"] = 1
        f = chao * 70 // 100           # patinou: sobra o atrito dinâmico
    else:
        c["patinou"] = 0
        f = motor
    if c["fervendo"]:
        f //= 2
    f = f * c["norma"] // 1000
    c["forca"] = f
    return f


# ---------------- pilotagem por regras (usada pelos bots e pela calibração) ----------------
def piloto(p: dict, tick: int, eu: dict) -> dict:
    """p = {reacao, troca, teto_temp, esfria, sobe_se_patinar, erros, vacilo}. Só depende do tick e do PRÓPRIO carro."""
    cmd: dict = {}
    vacilando = any(e <= tick < e + p.get("vacilo", 0) for e in p.get("erros", ()))
    esfriando = eu.get("_esfria_ate", -1) > tick
    if not esfriando and eu["temp"] >= p["teto_temp"]:
        eu["_esfria_ate"] = tick + p["esfria"]
        esfriando = True
    cmd["acel"] = 1 if (tick >= p["reacao"] and not vacilando and not esfriando) else 0
    if eu["marcha"] < 5 and (eu["rpm"] >= p["troca"] or (p.get("sobe_se_patinar") and eu["patinou"])):
        cmd["marcha"] = 1
    return cmd


def forca_total(acerto: dict, piso: str, p: dict, norma: int | None = None) -> int:
    """Força somada nos 30 s de um carro sozinho pilotado pela regra p (base da calibração e dos testes)."""
    c = novo_carro(acerto, piso)
    if norma is not None:
        c["norma"] = norma
    total = 0
    for t in range(DURACAO):
        aplicar(c, piloto(p, t, c))
        total += passo_carro(c)
    return total


def melhor_acerto_pneu(piso: str, relacao: str, mapa: str) -> dict:
    """Pneu e psi ótimos do piso (o maior μ efetivo)."""
    melhor = None
    for pneu in PNEUS:
        ideal = PISOS[piso][pneu][1]
        ac = {"pneu": pneu, "psi": ideal, "relacao": relacao, "mapa": mapa}
        if melhor is None or mu_efetivo(ac, piso) > mu_efetivo(melhor, piso):
            melhor = ac
    return melhor


def melhor_pilotagem(acerto: dict, piso: str, norma: int = 1000) -> tuple[int, dict]:
    """Busca a melhor regra de pilotagem (grade fixa) para o acerto: é o 'ótimo' usado na equivalência."""
    melhor = (-1, None)
    for troca in range(3000, 7001, 200):
        for teto in (700, 900, 990):
            for sobe in (0, 1):
                p = {"reacao": 0, "troca": troca, "teto_temp": teto, "esfria": 10, "sobe_se_patinar": sobe}
                f = forca_total(acerto, piso, p, norma)
                if f > melhor[0]:
                    melhor = (f, p)
    return melhor


def calibrar(alvo: int | None = None) -> dict:
    """Gera a tabela NORMA: em cada piso, todo estilo pilotado no ótimo chega à mesma força total (a do melhor estilo)."""
    tabela = {}
    for piso in PISOS:
        brutos = {}
        for rel in RELACOES:
            for mapa in MAPAS:
                ac = melhor_acerto_pneu(piso, rel, mapa)
                brutos[f"{rel}-{mapa}"] = melhor_pilotagem(ac, piso, 1000)[0]
        ref = alvo or max(brutos.values())
        tabela[piso] = {e: ref * 1000 // v for e, v in brutos.items()}
    return tabela


# ---------------- bots: PERFIS (PvP) e escada do modo história ----------------
# Cada perfil = um estilo + pneu/psi certos do piso + a melhor regra de pilotagem do estilo, com UM defeito fixo (o que permite
# a um humano muito bom vencer). Nenhum perfil é o "fácil": todos ficam perto do ótimo.
PERFIS = {  # defeitos ajustados para 96%..98,5% do ótimo (forte, mas batível): ver tests/test_arena.py
    "paciente":  {"nome": "Tião Paciente",   "estilo": "longa-torque",   "defeito": {"reacao": 6}},
    "pe_pesado": {"nome": "Zé Pé Pesado",    "estilo": "curta-potencia", "defeito": {"troca_mais": 500, "reacao": 4, "erros": [150], "vacilo": 17}},
    "tecnico":   {"nome": "Doutor Diesel",   "estilo": "media-potencia", "defeito": {"teto_temp": 800, "reacao": 5, "erros": [150], "vacilo": 10}},
    "bruto":     {"nome": "Baiano 4x4",      "estilo": "curta-torque",   "defeito": {"reacao": 5, "erros": [400], "vacilo": 18}},
    "estradeiro": {"nome": "Rei da Estrada", "estilo": "longa-potencia", "defeito": {"troca_menos": 500, "reacao": 5, "erros": [450], "vacilo": 24}},
    "lacador":   {"nome": "Chico Laçador",   "estilo": "media-torque",   "defeito": {"reacao": 6, "erros": [300, 450, 480], "vacilo": 22}},
}
ORDEM_PERFIS = list(PERFIS)


def perfil_da_partida(partida_id: int) -> str:
    """Rodízio fixo (sem sorteio): a partida n enfrenta o perfil n módulo 6."""
    return ORDEM_PERFIS[partida_id % len(ORDEM_PERFIS)]


def ficha_bot(perfil: str, piso: str, nivel: int | None = None) -> dict:
    """Acerto + regra de pilotagem do bot neste piso. nivel (1..20) só no modo história: abaixo de 20 piora de forma fixa."""
    pf = PERFIS[perfil]
    rel, mapa = pf["estilo"].split("-")
    ac = melhor_acerto_pneu(piso, rel, mapa)
    _, p = melhor_pilotagem(ac, piso, NORMA[piso][pf["estilo"]])
    p = dict(p)
    d = pf["defeito"]
    p["reacao"] = d.get("reacao", 2)
    p["troca"] = min(7000, p["troca"] + d.get("troca_mais", 0) - d.get("troca_menos", 0))
    if "teto_temp" in d:
        p["teto_temp"] = min(p["teto_temp"], d["teto_temp"])
    p["erros"], p["vacilo"] = list(d.get("erros", [])), d.get("vacilo", 0)
    if nivel is not None and nivel < 20:  # modo história: mais lento e mais erros quanto menor o nível (tabela fixa)
        k = 20 - max(1, nivel)
        p["reacao"] += k
        p["troca"] = max(3000, p["troca"] - k * 60)
        p["erros"] = p["erros"] + [60 + i * 50 for i in range(k // 2)]
        p["vacilo"] = max(p["vacilo"], 6 + k)
    return {"perfil": perfil, "nome": pf["nome"], "acerto": ac, "piloto": p, "nivel": nivel}


# ---------------- comandos e simulação (replay) ----------------
def puxao(fa: int, fb: int) -> int:
    """Quanto a corrente anda neste tick. Divisão SIMÉTRICA: com // o resultado negativo arredonda para baixo e dava ~0,5 por
    tick de vantagem ao lado B (−300 em 30 s, o bastante para virar um empate)."""
    d = fa - fb
    return d // PESO_CORRENTE if d >= 0 else -((-d) // PESO_CORRENTE)


def validar_cmd(cmd: dict) -> dict:
    out = {}
    if "acel" in cmd:
        out["acel"] = 1 if cmd.get("acel") else 0
    if cmd.get("marcha") in (1, -1):
        out["marcha"] = cmd["marcha"]
    return out


def simular(entradas_a: list, entradas_b: list | None = None, bot_b: dict | None = None, acerto_a: dict | None = None,
            acerto_b: dict | None = None, piso: str = "curral", ate: int = DURACAO) -> dict:
    """entradas = [[tick, {cmd}], ...] em ordem. Lado B = jogador (entradas_b + acerto_b) ou bot (bot_b = ficha_bot(...))."""
    a = novo_carro(acerto_a, piso)
    b = novo_carro(bot_b["acerto"] if bot_b else acerto_b, piso)
    ia = ib = 0
    entradas_b = entradas_b or []
    pos = 0
    quadros = []
    t = 0
    for t in range(ate):
        while ia < len(entradas_a) and entradas_a[ia][0] <= t:
            aplicar(a, validar_cmd(entradas_a[ia][1])); ia += 1
        if bot_b:
            aplicar(b, piloto(bot_b["piloto"], t, b))
        else:
            while ib < len(entradas_b) and entradas_b[ib][0] <= t:
                aplicar(b, validar_cmd(entradas_b[ib][1])); ib += 1
        fa, fb = passo_carro(a), passo_carro(b)
        pos += puxao(fa, fb)
        pos = max(-CHEGADA, min(CHEGADA, pos))
        if t % 2 == 0:
            quadros.append([t, pos, a["rpm"], a["marcha"], a["temp"], b["rpm"], b["marcha"], b["temp"]])
        if abs(pos) >= CHEGADA:
            break
    venc = "a" if pos >= EMPATE else "b" if pos <= -EMPATE else "empate"
    return {"vencedor": venc, "posicao": pos, "ticks": t + 1, "motor": VERSAO_MOTOR, "quadros": quadros}
