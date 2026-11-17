"""Critérios de aceite da Arena Bruta (documento §12 + decisões do Lucas na spec 45 §H)."""
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
        cod = c.post("/api/entrar/codigo", json={"email": email}).json()["codigo_dev"]
        assert c.post("/api/entrar", json={"email": email, "codigo": cod}).status_code == 200
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
    cod = c.post("/api/entrar/codigo", json={"email": "kid@x.com"}).json()["codigo_dev"]
    c.post("/api/entrar", json={"email": "kid@x.com", "codigo": cod})
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
    assert v["estado"] == "pronta" and v["rival"]["nivel"] == 1 and v["rival"]["apelido"] == jogo.NOMES_BOT[0]
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
    ent = [[0, {"tracao": 70}], [3, {"acel": 1}], [40, {"marcha": 1}], [90, {"marcha": 1}], [150, {"marcha": 1}]]
    base = jogo.simular(ent, bot_b=12)
    for _ in range(1000):
        r = jogo.simular(ent, bot_b=12)
        assert (r["vencedor"], r["posicao"], r["ticks"]) == (base["vencedor"], base["posicao"], base["ticks"])


def test_sem_aleatoriedade_no_codigo_do_jogo():
    """Regra do jurídico: nada de random/semente/relógio na lógica de partida (motor e bots)."""
    fonte = (Path(__file__).resolve().parent.parent / "app" / "jogo.py").read_text(encoding="utf-8")
    codigo = re.sub(r'"""[\s\S]*?"""', "", fonte)  # tira os comentários de documentação
    codigo = "\n".join(l.split("#")[0] for l in codigo.splitlines())
    for proibido in ("import random", "random.", "Math.random", "secrets", "uuid", "time.", "hash("):
        assert proibido not in codigo, proibido


def test_bots_tem_20_niveis_fixos_e_publicos(amb):
    app, pessoa, adm, dep = amb
    r = TestClient(app).get("/api/regulamento/niveis").json()
    assert len(r["niveis"]) == 20 and r["niveis"][0]["troca"] < r["niveis"][19]["troca"]
    assert jogo.BOTS == {n: jogo._ficha(n) for n in range(1, 21)}  # ficha é função pura do nível


def test_comissao_e_premios_das_arenas():
    assert [ledger.premio(e, 10) for _, e in ledger.ARENAS.values()] == [1800, 3240, 5832, 10498, 18895, 34011]
    assert ledger.comissao(1000, 10) == 200


def test_paginas_abrem(amb):
    app, *_ = amb
    c = TestClient(app)
    for p in ("/", "/app", "/regulamento", "/admin", "/admin/arena", "/health", "/api/arenas", "/api/ranking"):
        assert c.get(p).status_code == 200, p
