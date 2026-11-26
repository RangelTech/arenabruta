"""Critérios de aceite da Arena Bruta (documento §12 + decisões do Lucas na spec 45 §H)."""
from produtos_core.teste import entrar
import json
import os
import re
from pathlib import Path

os.environ["ARENA_SEM_APP"] = "1"
os.environ["RT_ADMIN_USUARIO"] = "adm"
os.environ["RT_ADMIN_SENHA"] = "senha-adm"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import jogo, ledger  # noqa: E402
from app.config import Config  # noqa: E402
from app.main import criar_app  # noqa: E402


@pytest.fixture
def amb(tmp_path):
    cfg = Config(dados=str(tmp_path), segredo_sessao="s", dev=True, pix_chave_casa="pix@arena.test")
    app = criar_app(cfg, tick_s=0.002)  # partida acelerada (mesma física, 2 ms por tick)

    def pessoa(email, apelido, nasc="1990-01-01", pix="pix-" + "x"):
        c = TestClient(app)
        entrar(c, email)
        assert c.post("/api/perfil", json={"apelido": apelido, "nascimento": nasc, "pix_chave": pix + apelido, "pix_tipo": "email"}).status_code == 200
        return c

    adm = TestClient(app)
    assert adm.post("/api/painel/entrar", json={"usuario": "adm", "senha": "senha-adm"}).status_code == 200

    def depositar(c, reais):
        d = c.post("/api/deposito", json={"valor": reais}).json()
        assert adm.post(f"/api/painel/arena/deposito/{d['id']}/confirmar").status_code == 200
        return d
    return app, pessoa, adm, depositar


def jogar(c, pid, cmds):
    with c.websocket_connect(f"/ws/partida/{pid}") as ws:
        assert json.loads(ws.receive_text())["t"] == "ok"
        for cmd in cmds:
            ws.send_text(json.dumps({"cmd": cmd}))
        while True:
            m = json.loads(ws.receive_text())
            if m["t"] == "fim":
                return m


def test_menor_de_18_bloqueado(amb):
    app, pessoa, adm, dep = amb
    c = TestClient(app)
    entrar(c, "kid@x.com")
    assert c.post("/api/perfil", json={"apelido": "Kid", "nascimento": "2012-01-01"}).status_code == 403


def test_deposito_so_entra_quando_confirmado_e_uma_vez(amb):
    app, pessoa, adm, dep = amb
    a = pessoa("a@x.com", "Peao1")
    d = a.post("/api/deposito", json={"valor": 10}).json()
    assert "pix@arena.test" in d["instrucoes"] and a.get("/api/conta").json()["saldo"]["disponivel"] == 0
    assert adm.post(f"/api/painel/arena/deposito/{d['id']}/confirmar").status_code == 200
    assert adm.post(f"/api/painel/arena/deposito/{d['id']}/confirmar").status_code == 409  # repetido não credita de novo
    assert a.get("/api/conta").json()["saldo"]["disponivel"] == 1000


def test_pvp_10_mais_10_vencedor_18_casa_2_e_saque(amb):
    app, pessoa, adm, dep = amb
    a, b = pessoa("a@x.com", "Peao1"), pessoa("b@x.com", "Peao2")
    dep(a, 10)
    dep(b, 10)
    pa = a.post("/api/fila", json={"arena": "peao"}).json()
    pb = b.post("/api/fila", json={"arena": "peao"}).json()
    assert pa["id"] == pb["id"] and pb["estado"] == "pronta" and pb["premio"] == 1800
    # B conecta primeiro (fica esperando), A conecta e joga bem; B não faz nada
    import threading
    res = {}
    t = threading.Thread(target=lambda: res.update(b=jogar(b, pb["id"], [])))
    t.start()
    import time
    time.sleep(0.2)
    res["a"] = jogar(a, pa["id"], [{"tracao": 72}, {"acel": 1}])
    t.join(10)
    assert res["a"]["vencedor"] == "a"
    sa, sb = a.get("/api/conta").json()["saldo"], b.get("/api/conta").json()["saldo"]
    assert sa["disponivel"] == 1800 and sb["disponivel"] == 0 and sa["reservado"] == sb["reservado"] == 0
    painel = adm.get("/api/painel/arena").json()
    assert painel["caixa"]["receita"] == 200 and painel["invariantes"]["soma_zero"] and not painel["invariantes"]["negativos"]
    # saca os 18 sem jogar de novo; saque precisa de aprovação
    s = a.post("/api/saque", json={"valor": 18}).json()
    assert a.get("/api/conta").json()["saldo"] == {"disponivel": 0, "reservado": 0, "saque": 1800}
    assert adm.post(f"/api/painel/arena/saque/{s['id']}/pagar", json={}).status_code == 200
    assert a.get("/api/conta").json()["saldo"]["saque"] == 0
    assert adm.get("/api/painel/arena").json()["invariantes"]["soma_zero"]


def test_saldo_nunca_negativo_e_saque_recusado_devolve(amb):
    app, pessoa, adm, dep = amb
    a = pessoa("a@x.com", "Peao1")
    dep(a, 10)
    assert a.post("/api/fila", json={"arena": "cowboy"}).status_code == 402  # entrada R$ 18 > saldo
    assert a.post("/api/saque", json={"valor": 11}).status_code == 402
    s = a.post("/api/saque", json={"valor": 10}).json()
    adm.post(f"/api/painel/arena/saque/{s['id']}/recusar", json={})
    assert a.get("/api/conta").json()["saldo"]["disponivel"] == 1000


def test_contra_competidor_da_casa_sem_adversario(amb, monkeypatch):
    app, pessoa, adm, dep = amb
    a = pessoa("a@x.com", "Peao1")
    dep(a, 10)
    p = a.post("/api/fila", json={"arena": "peao"}).json()
    assert p["estado"] == "fila"
    import app.main as M
    monkeypatch.setattr(M, "ESPERA_HUMANO_S", 0)
    v = a.get(f"/api/partida/{p['id']}").json()
    perfil = jogo.perfil_da_partida(p["id"])
    assert v["estado"] == "pronta" and "nivel" not in v["rival"] and v["rival"]["apelido"] == jogo.PERFIS[perfil]["nome"]  # PvP: perfil, sem nível
    assert v["cenario"]["piso"] == "terra" and v["ele"]["acerto"]["pneu"] in jogo.PNEUS  # a arena mostra o acerto do rival
    fim = jogar(a, p["id"], [])  # parado, perde para o bot
    assert fim["vencedor"] == "b"
    painel = adm.get("/api/painel/arena").json()
    assert painel["caixa"]["bots"] == 1000 and painel["invariantes"]["soma_zero"]
    r = a.get(f"/api/partida/{p['id']}/replay").json()
    assert r["confere"]  # o replay refaz o mesmo resultado


def test_tetos_da_casa_fecham_a_fila_de_bot(amb, monkeypatch):
    app, pessoa, adm, dep = amb
    a = pessoa("a@x.com", "Peao1")
    dep(a, 10)
    adm.post("/api/painel/arena/ajustes", json={"teto_exposicao": 500})  # menor que a entrada: nenhum bot
    import app.main as M
    monkeypatch.setattr(M, "ESPERA_HUMANO_S", 0)
    p = a.post("/api/fila", json={"arena": "peao"}).json()
    assert a.get(f"/api/partida/{p['id']}").json()["estado"] == "fila"  # continua esperando humano
    assert a.post(f"/api/partida/{p['id']}/sair").status_code == 200
    assert a.get("/api/conta").json()["saldo"]["disponivel"] == 1000  # saiu da fila: entrada devolvida


def test_motor_deterministico_1000_vezes():
    ent = [[3, {"acel": 1}], [40, {"marcha": 1}], [90, {"marcha": 1}], [150, {"marcha": 1}]]
    bot = jogo.ficha_bot("tecnico", "lama")
    base = jogo.simular(ent, bot_b=bot, acerto_a={"pneu": "cravo", "psi": 18}, piso="lama")
    for _ in range(1000):
        r = jogo.simular(ent, bot_b=bot, acerto_a={"pneu": "cravo", "psi": 18}, piso="lama")
        assert (r["vencedor"], r["posicao"], r["ticks"]) == (base["vencedor"], base["posicao"], base["ticks"])


def test_sem_aleatoriedade_no_codigo_do_jogo():
    """Regra do jurídico: nada de random/semente/relógio na lógica de partida (motor e bots)."""
    fonte = (Path(__file__).resolve().parent.parent / "app" / "jogo.py").read_text(encoding="utf-8")
    codigo = re.sub(r'"""[\s\S]*?"""', "", fonte)  # tira os comentários de documentação
    codigo = "\n".join(l.split("#")[0] for l in codigo.splitlines())
    for proibido in ("import random", "random.", "Math.random", "secrets", "uuid", "time.", "hash("):
        assert proibido not in codigo, proibido


def test_regulamento_publica_perfis_e_pisos(amb):
    app, pessoa, adm, dep = amb
    r = TestClient(app).get("/api/regulamento/niveis").json()
    assert len(r["perfis"]) == 6 and r["espera_humano_s"] == 15 and set(r["pisos"]) == set(jogo.PISOS)
    assert [jogo.perfil_da_partida(n) for n in range(7)] == jogo.ORDEM_PERFIS + [jogo.ORDEM_PERFIS[0]]  # rodízio fixo


def _otimo(piso, estilo):
    rel, mapa = estilo.split("-")
    ac = jogo.melhor_acerto_pneu(piso, rel, mapa)
    return jogo.melhor_pilotagem(ac, piso, jogo.NORMA[piso][estilo])[0]


def test_estilos_diferentes_no_otimo_tem_a_mesma_forca():
    """Spec 46 §9.3: meritocracia por equivalência (±1%) em todo piso."""
    for piso in jogo.PISOS:
        tot = [_otimo(piso, e) for e in jogo.ESTILOS]
        assert max(tot) - min(tot) <= max(tot) // 100, (piso, tot)


def test_pneu_e_psi_errados_custam_caro():
    for piso, errado in (("lama", "liso"), ("praia", "liso")):
        bom = _otimo(piso, "media-torque")
        ac = {"pneu": errado, "psi": jogo.PISOS[piso][errado][1], "relacao": "media", "mapa": "torque"}
        assert jogo.melhor_pilotagem(ac, piso, jogo.NORMA[piso]["media-torque"])[0] < bom * 92 // 100
        ac = dict(jogo.melhor_acerto_pneu(piso, "media", "torque")); ac["psi"] += 10
        assert jogo.melhor_pilotagem(ac, piso, jogo.NORMA[piso]["media-torque"])[0] < bom * 92 // 100


def test_bots_fortes_mas_bativeis():
    """Todo perfil fica entre 95% e 99% do ótimo: dá trabalho, mas o jogador perfeito vence."""
    for piso in ("terra", "lama", "praia"):
        ref = _otimo(piso, "media-torque")
        for pf in jogo.PERFIS:
            fb = jogo.ficha_bot(pf, piso)
            c = jogo.novo_carro(fb["acerto"], piso)
            tot = 0
            for t in range(jogo.DURACAO):
                jogo.aplicar(c, jogo.piloto(fb["piloto"], t, c))
                tot += jogo.passo_carro(c)
            assert ref * 95 // 100 <= tot <= ref * 99 // 100, (piso, pf, tot * 100 / ref)
        # o jogador que pilota no ótimo vence cada perfil
        _, p = jogo.melhor_pilotagem(jogo.melhor_acerto_pneu(piso, "media", "torque"), piso, jogo.NORMA[piso]["media-torque"])
        ent, c = [], jogo.novo_carro(jogo.melhor_acerto_pneu(piso, "media", "torque"), piso)
        ultimo = {}
        for t in range(jogo.DURACAO):
            cmd = jogo.piloto(p, t, c)
            if cmd != ultimo or "marcha" in cmd:
                ent.append([t, cmd]); ultimo = {k: v for k, v in cmd.items() if k != "marcha"}
            jogo.aplicar(c, cmd); jogo.passo_carro(c)
        for pf in jogo.PERFIS:
            r = jogo.simular(ent, bot_b=jogo.ficha_bot(pf, piso), acerto_a=jogo.melhor_acerto_pneu(piso, "media", "torque"), piso=piso)
            assert r["vencedor"] == "a", (piso, pf, r["posicao"])


def test_modo_historia_nivel_baixo_e_mais_fraco():
    def tot(n):
        fb = jogo.ficha_bot("tecnico", "terra", n); c = jogo.carro_bot(fb, "terra"); s = 0
        for t in range(jogo.DURACAO):
            jogo.aplicar(c, jogo.piloto(fb["piloto"], t, c)); s += jogo.passo_carro(c)
        return s
    forcas = [tot(n) for n in range(1, 21)]
    assert forcas == sorted(forcas) and forcas[0] < forcas[-1]  # escada de verdade: cada nível é mais forte que o anterior
    assert jogo.ficha_bot("tecnico", "terra", None)["forca"] == jogo.ficha_bot("tecnico", "terra", 20)["forca"] == 1000


def test_escada_por_tipo_de_jogador():
    """Spec 58 §3: jogador comum (troca a ~5.500 rpm, sem o segredo dos 7.000) vence os níveis baixos e perde os altos."""
    def vence(p, nivel, piso="terra"):
        ac = jogo.melhor_acerto_pneu(piso, "media", "torque")
        ent, c, ultimo = [], jogo.novo_carro(ac, piso), {}
        for t in range(jogo.DURACAO):
            cmd = jogo.piloto(p, t, c)
            if cmd != ultimo or "marcha" in cmd:
                ent.append([t, cmd]); ultimo = {k: v for k, v in cmd.items() if k != "marcha"}
            jogo.aplicar(c, cmd); jogo.passo_carro(c)
        return jogo.simular(ent, bot_b=jogo.ficha_bot("paciente", piso, nivel), acerto_a=ac, piso=piso)["vencedor"] == "a"
    medio = dict(reacao=10, troca=5200, teto_temp=900, esfria=10, erros=[300], vacilo=12)
    bom = dict(reacao=5, troca=5500, teto_temp=900, esfria=10)
    assert vence(medio, 1) and vence(medio, 5) and not vence(medio, 15) and not vence(medio, 20)
    assert vence(bom, 1) and vence(bom, 8) and not vence(bom, 18) and not vence(bom, 20)


def test_box_salva_acerto_e_garagem_e_cor_nao_muda_fisica(amb):
    app, pessoa, adm, dep = amb
    a = pessoa("a@x.com", "Peao1")
    r = a.post("/api/box", json={"acerto": {"pneu": "cravo", "psi": 99, "relacao": "longa", "mapa": "potencia"}, "garagem": {"modelo": "s150", "cor": "#ff0000"}}).json()
    assert r["acerto"] == {"pneu": "cravo", "psi": 45, "relacao": "longa", "mapa": "potencia"}  # psi limitado a 45
    c = a.get("/api/conta").json()
    assert c["acerto"]["pneu"] == "cravo" and c["garagem"]["modelo"] == "s150"
    # a física não sabe de cor nem de modelo: só o acerto entra no motor
    assert "garagem" not in jogo.novo_carro(c["acerto"], "terra")


def test_replay_de_partida_antiga_usa_o_motor_v2():
    from app import jogo_v2
    ent = [[0, {"tracao": 70}], [3, {"acel": 1}], [40, {"marcha": 1}]]
    assert jogo_v2.simular(ent, bot_b=12)["motor"] == 2


def test_comissao_e_premios_das_arenas():
    assert [ledger.premio(e, 10) for _, e in ledger.ARENAS.values()] == [1800, 3240, 5832, 10498, 18895, 34011]
    assert ledger.comissao(1000, 10) == 200


def test_paginas_abrem(amb):
    app, *_ = amb
    c = TestClient(app)
    for p in ("/", "/app", "/regulamento", "/admin", "/admin/arena", "/health", "/api/arenas", "/api/ranking"):
        assert c.get(p).status_code == 200, p


def test_fila_fantasma_nao_pareia_e_abandono_devolve(amb, monkeypatch):
    """Quem fechou a página na fila não vira adversário fantasma; a vaga abandonada é cancelada com a entrada devolvida."""
    import app.main as M
    app, pessoa, adm, dep = amb
    a, b = pessoa("a@x.com", "Peao1"), pessoa("b@x.com", "Peao2")
    dep(a, 10)
    dep(b, 10)
    pa = a.post("/api/fila", json={"arena": "peao"}).json()
    monkeypatch.setattr(M, "VIVO_S", -1)  # "a" parou de consultar a fila (fechou a página)
    pb = b.post("/api/fila", json={"arena": "peao"}).json()
    assert pb["id"] != pa["id"] and pb["estado"] == "fila"
    monkeypatch.setattr(M, "ABANDONO_S", -1)  # passou o tempo de abandono: a próxima entrada na fila limpa as vagas velhas
    c = pessoa("c@x.com", "Peao3")
    dep(c, 10)
    c.post("/api/fila", json={"arena": "peao"})
    assert a.get(f"/api/partida/{pa['id']}").json()["estado"] == "cancelada"
    assert a.get("/api/carteira").json()["saldo"]["disponivel"] == 1000
    assert adm.get("/api/painel/arena").json()["invariantes"]["soma_zero"]


def test_pvp_comeca_mesmo_com_adversario_ausente(amb, monkeypatch):
    """PvP pareado em que um lado não conecta: começa depois da espera, com o carro ausente parado (regra de queda)."""
    import app.main as M
    monkeypatch.setattr(M, "ESPERA_ADVERSARIO_S", 0.2)
    app, pessoa, adm, dep = amb
    a, b = pessoa("a@x.com", "Peao1"), pessoa("b@x.com", "Peao2")
    dep(a, 10)
    dep(b, 10)
    pa = a.post("/api/fila", json={"arena": "peao"}).json()
    pb = b.post("/api/fila", json={"arena": "peao"}).json()
    assert pa["id"] == pb["id"]
    fim = jogar(a, pa["id"], [{"tracao": 72, "acel": 1}])  # "b" nunca conecta
    assert fim["vencedor"] == "a"
    assert adm.get("/api/painel/arena").json()["invariantes"]["soma_zero"]


def test_corrente_sem_vies_de_lado():
    """Mesmos comandos e mesmo acerto dos dois lados = posição final 0 (o arredondamento não favorece ninguém)."""
    ent = [[0, {"acel": 1}], [40, {"marcha": 1}], [100, {"marcha": 1}], [170, {"marcha": 1}], [260, {"marcha": 1}]]
    r = jogo.simular(ent, ent, None, {"relacao": "curta"}, {"relacao": "curta"}, "terra")
    assert r["posicao"] == 0 and r["vencedor"] == "empate"
    assert jogo.puxao(1, 300) == -jogo.puxao(300, 1)
