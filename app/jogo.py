"""Cabo de Guerra Diesel: motor 100% determinístico (regra do jurídico: ZERO aleatoriedade).

- Só inteiros, passo fixo (20 ticks/s, 30 s = 600 ticks). Mesmas entradas -> mesmo resultado, sempre (replay = refazer a conta).
- O servidor é a autoridade: o cliente manda só comandos (acelerar, marcha, tração); a física e o vencedor são calculados aqui.
- Bots: 20 níveis FIXOS e versionados (BOTS). Cada nível é uma ficha: tempo de reação, giro da troca de marcha, tração,
  limite de temperatura e erros em ticks fixos. Mesma situação -> mesma ação. Nada depende de saldo, perdas ou valor.
NUNCA usar random, secrets, uuid, time ou hash em lógica de partida (o teste test_sem_aleatoriedade varre este arquivo).
"""
from __future__ import annotations

TICKS_S = 20
DURACAO = 30 * TICKS_S
CHEGADA = 10000          # posição da corrente que dá vitória
EMPATE = 250             # |posição| abaixo disso no fim = empate (devolve tudo)
RPM_MIN, RPM_MAX = 800, 7000
ACEL = [0, 230, 170, 125, 95, 72]       # quanto o giro sobe por tick em cada marcha
RELACAO = [0, 44, 33, 25, 19, 15]      # força multiplicada pela marcha (curta = força)
TRACAO_IDEAL = 72
VERSAO_MOTOR = 1


def torque(rpm: int) -> int:
    """Curva de torque do diesel: pico entre 3.800 e 4.800 rpm (0 a 1000)."""
    if rpm < 3800:
        return max(120, 120 + (rpm - RPM_MIN) * 880 // (3800 - RPM_MIN))
    if rpm <= 4800:
        return 1000
    return max(150, 1000 - (rpm - 4800) * 850 // (RPM_MAX - 4800))


def novo_carro() -> dict:
    return {"rpm": RPM_MIN, "marcha": 1, "temp": 0, "acel": 0, "tracao": 50, "fervendo": 0, "forca": 0, "patinou": 0}


def aplicar(c: dict, cmd: dict) -> None:
    """Comando do jogador/bot já validado: acel 0/1, marcha +1/-1, tracao 0..100."""
    if "acel" in cmd:
        c["acel"] = 1 if cmd["acel"] else 0
    if cmd.get("marcha") in (1, -1):
        nova = min(5, max(1, c["marcha"] + cmd["marcha"]))
        if nova != c["marcha"]:
            # troca de marcha: o giro cai (ou sobe) na proporção das relações
            c["rpm"] = max(RPM_MIN, min(RPM_MAX, c["rpm"] * RELACAO[nova] // RELACAO[c["marcha"]]))
            c["marcha"] = nova
    if "tracao" in cmd:
        c["tracao"] = max(0, min(100, int(cmd["tracao"])))


def passo_carro(c: dict) -> int:
    if c["acel"]:
        c["rpm"] = min(RPM_MAX, c["rpm"] + ACEL[c["marcha"]])
    else:
        c["rpm"] = max(RPM_MIN, c["rpm"] - 160)
    # temperatura: sobe acima de 6.000 rpm, esfria devagar; a 1000 o motor ferve e perde metade da força por 3 s
    if c["rpm"] > 6000:
        c["temp"] = min(1000, c["temp"] + (c["rpm"] - 6000) // 40)
    else:
        c["temp"] = max(0, c["temp"] - 4)
    if c["temp"] >= 1000 and not c["fervendo"]:
        c["fervendo"] = 3 * TICKS_S
    if c["fervendo"]:
        c["fervendo"] -= 1
        if not c["fervendo"]:
            c["temp"] = 600
    bruta = torque(c["rpm"]) * RELACAO[c["marcha"]] if c["acel"] else torque(c["rpm"]) * RELACAO[c["marcha"]] // 6
    # aderência: tração longe do ideal faz patinar (perde força); com muita força e pouca tração, patina mais
    desvio = abs(c["tracao"] - TRACAO_IDEAL)
    ader = max(35, 100 - desvio * 3 // 2)
    c["patinou"] = 1 if ader < 70 and c["acel"] else 0
    f = bruta * ader // 100
    if c["fervendo"]:
        f //= 2
    c["forca"] = f
    return f


# ---------------- bots: 20 níveis fixos (ficha versionada) ----------------
def _ficha(n: int) -> dict:
    """Interpolação fixa entre o nível 1 (iniciante) e o 20 (lenda). Só inteiros: nada muda entre execuções."""
    k = n - 1  # 0..19
    return {
        "nivel": n,
        "reacao": 24 - k,                         # ticks até começar a acelerar (1,2 s -> 0,25 s)
        "troca": 3400 + k * 105,                  # giro em que sobe a marcha (3.400 -> 5.395)
        "tracao": 34 + k * 38 // 19,              # 34 -> 72 (ideal)
        "temp_max": 500 + k * 21,                 # tira o pé ao passar desta temperatura
        "esfria": 18 - k * 14 // 19,              # ticks com o pé fora para esfriar
        "erros": [60, 120, 170, 230, 290, 340, 400, 460, 510, 560][: max(0, 10 - k * 10 // 19)],  # ticks FIXOS de vacilo (10 -> 0)
        "vacilo": 26 - k * 18 // 19,              # duração de cada vacilo em ticks (26 -> 8)
    }


BOTS = {n: _ficha(n) for n in range(1, 21)}
NOMES_BOT = ["Zé do Diesel", "Tião Bruto", "Chico Laçador", "Juca da Serra", "Bento Ferradura", "Nego Poeira", "Dito Tratorista",
             "Galego do Rodeio", "Valdir Caminhão", "Toninho Peão", "Baiano 4x4", "Cabeça de Boi", "Neno do Atoleiro", "Pedrão Cowboy",
             "Lázaro Diesel", "Coronel Bigode", "Barão do Barro", "Rei da Estrada", "Lenda do Interior", "Mestre do Agro"]


def bot_cmd(f: dict, tick: int, eu: dict) -> dict:
    """Ação do bot a partir só do tick e do estado do PRÓPRIO carro (determinístico)."""
    cmd: dict = {}
    if tick == 0:
        cmd["tracao"] = f["tracao"]
    vacilando = any(e <= tick < e + f["vacilo"] for e in f["erros"])
    esfriando = eu.get("_esfria_ate", -1) > tick
    if not esfriando and eu["temp"] >= f["temp_max"]:
        eu["_esfria_ate"] = tick + f["esfria"]
        esfriando = True
    cmd["acel"] = 1 if (tick >= f["reacao"] and not vacilando and not esfriando) else 0
    if eu["rpm"] >= f["troca"] and eu["marcha"] < 5:
        cmd["marcha"] = 1
    return cmd


def nivel_bot_para(nivel_jogador: int) -> int:
    """Tabela fixa (publicada no regulamento): o jogador enfrenta o bot do nível dele."""
    return max(1, min(20, nivel_jogador))


# ---------------- simulação completa (replay e partida contra bot) ----------------
def validar_cmd(cmd: dict) -> dict:
    out = {}
    if "acel" in cmd:
        out["acel"] = 1 if cmd.get("acel") else 0
    if cmd.get("marcha") in (1, -1):
        out["marcha"] = cmd["marcha"]
    if "tracao" in cmd:
        try:
            out["tracao"] = max(0, min(100, int(cmd["tracao"])))
        except (TypeError, ValueError):
            pass
    return out


def simular(entradas_a: list, entradas_b: list | None = None, bot_b: int | None = None, ate: int = DURACAO) -> dict:
    """entradas = [[tick, {cmd}], ...] em ordem. Lado B = jogador (entradas_b) ou bot (bot_b = nível)."""
    a, b = novo_carro(), novo_carro()
    ia = ib = 0
    entradas_b = entradas_b or []
    pos = 0
    quadros = []
    for t in range(ate):
        while ia < len(entradas_a) and entradas_a[ia][0] <= t:
            aplicar(a, validar_cmd(entradas_a[ia][1])); ia += 1
        if bot_b:
            aplicar(b, bot_cmd(BOTS[bot_b], t, b))
        else:
            while ib < len(entradas_b) and entradas_b[ib][0] <= t:
                aplicar(b, validar_cmd(entradas_b[ib][1])); ib += 1
        fa, fb = passo_carro(a), passo_carro(b)
        pos += (fa - fb) // 40
        pos = max(-CHEGADA, min(CHEGADA, pos))
        if t % 2 == 0:
            quadros.append([t, pos, a["rpm"], a["marcha"], a["temp"], b["rpm"], b["marcha"], b["temp"]])
        if abs(pos) >= CHEGADA:
            break
    venc = "a" if pos >= EMPATE else "b" if pos <= -EMPATE else "empate"
    return {"vencedor": venc, "posicao": pos, "ticks": t + 1, "motor": VERSAO_MOTOR, "quadros": quadros}
