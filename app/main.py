"""Arena Bruta: duelos 1x1 de habilidade (tema agro) valendo dinheiro de verdade. Spec 45 §H.

- Carteira em centavos com razão de partidas dobradas (app/ledger.py). Depósito e saque passam pelo provedor de pagamento
  (app/pagamentos.py); sem gateway, os dois são aprovados no painel /admin/arena.
- Arena de Treino (grátis, bots livres) e Arena de Combate (valendo): PvP; sem adversário humano em alguns segundos, entra um
  competidor da casa de nível fixo (tabela por experiência), se os tetos de caixa permitirem.
- Partida ao vivo por WebSocket, servidor autoritativo (app/jogo.py, determinístico). O replay refaz o resultado.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import admin, auth, jogo, ledger, mailer, pagamentos, senha_rotas
from produtos_core import acesso, armazenamento
from app.config import Config, carregar
from app.db import Banco, agora

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("arenabruta")
COOKIE = "arenabruta_s"
ESTATICO = Path(__file__).resolve().parent.parent / "static"
ESPERA_HUMANO_S = 15        # sem adversário humano nesse tempo -> competidor da casa (decisão do Lucas, spec 46 §9.6)
VIVO_S = 10                 # só pareia com quem consultou a fila nesse tempo (quem fechou a página não vira fantasma)
ABANDONO_S = 60             # vaga na fila sem consulta há mais que isso: cancelada e entrada devolvida
ESPERA_ADVERSARIO_S = 20    # PvP: adversário que não conecta nesse tempo -> começa assim mesmo (carro dele parado, regra publicada)
DEP_MIN, DEP_MAX = 1000, 500000
SAQUE_MIN = 1000
AJUSTES_PADRAO = {"teto_exposicao": 100000, "teto_perda_dia": 30000, "teto_ganho_jogador_dia": 10000, "bots_combate": 1}


def criar_app(cfg: Config | None = None, tick_s: float = 1 / jogo.TICKS_S) -> FastAPI:
    cfg = cfg or carregar()
    os.makedirs(cfg.dados, exist_ok=True)
    db = Banco(os.path.join(cfg.dados, "arenabruta.db"))
    admin.preparar(db)
    pag = pagamentos.provedor(cfg)
    app = FastAPI(title="Arena Bruta", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.db = cfg, db
    ao_vivo: dict[int, "Ao"] = {}

    # ------------------------------------------------ ajudantes
    def usuario(request: Request, obrigatorio: bool = True) -> dict | None:
        u = auth.usuario_da_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        if not u and obrigatorio:
            raise HTTPException(401, "entre na sua conta")
        return u

    def ajuste(k: str) -> int:
        r = db.um("SELECT valor FROM ajustes WHERE chave=?", (k,))
        return int(r["valor"]) if r else AJUSTES_PADRAO[k]

    def perfil(uid: int) -> dict | None:
        return db.um("SELECT * FROM perfis WHERE usuario=?", (uid,))

    def idade(nasc: str) -> int:
        try:
            d = dt.date.fromisoformat(nasc)
        except (TypeError, ValueError):
            return 0
        h = dt.date.today()
        return h.year - d.year - ((h.month, h.day) < (d.month, d.day))

    def exigir_perfil(u: dict) -> dict:
        p = perfil(u["id"])
        if not p:
            raise HTTPException(428, "complete o seu cadastro (apelido e data de nascimento)")
        if p["autoexclusao_ate"] > agora():
            raise HTTPException(403, "conta em pausa voluntária até " + dt.datetime.fromtimestamp(p["autoexclusao_ate"]).strftime("%d/%m/%Y"))
        return p

    def hoje_ini() -> float:
        h = dt.datetime.now(dt.timezone(dt.timedelta(hours=-3)))
        return h.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    def alerta(tipo: str, texto: str, uid: int | None = None) -> None:
        # não repete o mesmo alerta do mesmo jogador no mesmo dia
        if db.um("SELECT 1 FROM alertas WHERE tipo=? AND COALESCE(usuario,0)=? AND criado>?", (tipo, uid or 0, hoje_ini())):
            return
        db.exec("INSERT INTO alertas(tipo,texto,usuario,criado) VALUES(?,?,?,?)", (tipo, texto, uid, agora()))

    def perda_casa_hoje() -> int:
        r = db.um("""SELECT COALESCE(SUM(l.valor),0) s FROM lancamentos l JOIN transacoes t ON t.id=l.transacao
                     WHERE l.conta='casa:bots' AND t.criado>?""", (hoje_ini(),))
        return max(0, -int(r["s"]))

    def ganho_jogador_bots_hoje(uid: int) -> int:
        tot = 0
        for p in db.todos("SELECT entrada, vencedor FROM partidas WHERE jog_a=? AND modo='combate' AND bot_nivel IS NOT NULL AND estado='terminada' AND fim>?",
                          (uid, hoje_ini())):
            if p["vencedor"] == "a":
                tot += ledger.premio(p["entrada"], cfg.comissao_pct) - p["entrada"]
            elif p["vencedor"] == "b":
                tot -= p["entrada"]
        return tot

    def exposicao_bots() -> int:
        r = db.um("SELECT COALESCE(SUM(entrada),0) s FROM partidas WHERE modo='combate' AND bot_nivel IS NOT NULL AND estado IN ('pronta','jogando')")
        return int(r["s"])

    def pode_bot(uid: int, entrada: int) -> tuple[bool, str]:
        if not ajuste("bots_combate"):
            return False, "desligado"
        if exposicao_bots() + entrada > ajuste("teto_exposicao"):
            return False, "teto_exposicao"
        if perda_casa_hoje() >= ajuste("teto_perda_dia"):
            alerta("perda_dia", f"A casa atingiu o teto de perda do dia contra bots (R$ {perda_casa_hoje() / 100:.2f}). Fila de bot fechada até 00h.")
            return False, "teto_perda_dia"
        if ganho_jogador_bots_hoje(uid) >= ajuste("teto_ganho_jogador_dia"):
            alerta("ganho_jogador", f"Jogador {uid} atingiu o teto de ganho do dia contra bots.", uid)
            return False, "teto_ganho_jogador"
        return True, ""

    def ficha_do_bot(p: dict) -> dict | None:
        if not p["bot_nivel"]:
            return None
        perfil_bot = p.get("bot_perfil") or jogo.perfil_da_partida(p["id"])
        return jogo.ficha_bot(perfil_bot, p.get("piso") or "curral", None if p["modo"] == "combate" else p["bot_nivel"])

    def garagem_de(uid: int | None) -> dict:
        o = perfil(uid) if uid else None
        try:
            return json.loads(o["garagem"]) if o and o.get("garagem") else {}
        except (ValueError, TypeError):
            return {}

    def vista_partida(p: dict, uid: int) -> dict:
        lado = "a" if p["jog_a"] == uid else "b"
        outro = "b" if lado == "a" else "a"
        bot = ficha_do_bot(p)
        acertos = {"a": json.loads(p["acerto_a"]) if p.get("acerto_a") else None, "b": json.loads(p["acerto_b"]) if p.get("acerto_b") else None}
        if bot:
            acertos["b"] = bot["acerto"]
            rival = {"apelido": bot["nome"], "garagem": {"modelo": jogo.ORDEM_PERFIS.index(bot["perfil"]) % 9, "perfil": bot["perfil"]}}
            if p["modo"] != "combate":
                rival["nivel"] = p["bot_nivel"]  # só o modo história mostra nível
        else:
            o_id = p["jog_b"] if lado == "a" else p["jog_a"]
            o = perfil(o_id) if (p["jog_b"] and p["jog_a"]) else None
            rival = {"apelido": o["apelido"], "garagem": garagem_de(o_id)} if o else None
        nome_cena, piso = jogo.CENARIOS.get(p["arena"] if p["modo"] == "combate" else (p.get("cenario") or "treino"), jogo.CENARIOS["treino"])
        return {"id": p["id"], "arena": p["arena"], "modo": p["modo"], "entrada": p["entrada"], "estado": p["estado"], "lado": lado,
                "rival": rival, "vencedor": p["vencedor"], "premio": ledger.premio(p["entrada"], cfg.comissao_pct) if p["modo"] == "combate" else 0,
                "cenario": {"id": p.get("cenario") or p["arena"], "nome": nome_cena, "piso": p.get("piso") or piso, "piso_nome": jogo.PISOS[p.get("piso") or piso]["nome"]},
                "eu": {"acerto": acertos[lado], "garagem": garagem_de(uid)}, "ele": {"acerto": acertos[outro]}}

    # ------------------------------------------------ login (padrão dos produtos)
    @app.get("/health")
    def health():
        return {"ok": True}

    def _login(u: dict) -> JSONResponse:
        token = auth.criar_sessao(db, cfg.segredo_sessao, u["id"])
        resp = JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, token, max_age=auth.SESSAO_S, httponly=True, secure=not cfg.dev, samesite="lax", path="/")
        return resp

    acesso.registrar(app, db, enviar=lambda para, assunto, texto, html: mailer.enviar(cfg, para, assunto, texto, html),
                     login=_login, usuario=usuario, criar_usuario=lambda email: auth.usuario_por_email(db, email),
                     produto="Arena Bruta", base_url=cfg.base_url, destino="/app", cor="#7c5cff",
                     demo_email=lambda: cfg.demo_email, demo_senha=lambda: cfg.demo_senha, dev=cfg.dev)  # cadastro e login comuns (spec 57 §5A)
    armazenamento.registrar(app, armazenamento.Armazenamento(pasta_local=os.path.join(getattr(cfg, "dados", "") or ".", "arquivos")))  # MinIO (spec 57 §8.6)

    @app.post("/api/sair")
    def sair(request: Request):
        auth.encerrar_sessao(db, cfg.segredo_sessao, request.cookies.get(COOKIE))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    # ------------------------------------------------ público
    @app.get("/api/arenas")
    def arenas():
        return {"arenas": [{"id": k, "nome": n, "entrada": e, "premio": ledger.premio(e, cfg.comissao_pct), "comissao": ledger.comissao(e, cfg.comissao_pct)}
                           for k, (n, e) in ledger.ARENAS.items()],
                "comissao_pct": cfg.comissao_pct, "cenarios": {k: {"nome": n, "piso": pi, "piso_nome": jogo.PISOS[pi]["nome"]} for k, (n, pi) in jogo.CENARIOS.items()},
                "historia": [{"nivel": n} for n in range(1, 21)], "perfis": {k: v["nome"] for k, v in jogo.PERFIS.items()}}

    @app.get("/api/ranking")
    def ranking():
        return {"ranking": db.todos("SELECT apelido, nivel, xp, vitorias FROM perfis ORDER BY xp DESC, vitorias DESC LIMIT 50")}

    @app.get("/api/regulamento/niveis")
    def regulamento():
        """Tabela publicada: perfis fixos dos competidores da casa (PvP) e a escada do modo história (sem aleatoriedade)."""
        return {"versao_motor": jogo.VERSAO_MOTOR, "espera_humano_s": ESPERA_HUMANO_S,
                "perfis": [{"id": k, "nome": v["nome"], "estilo": v["estilo"], "defeito": v["defeito"]} for k, v in jogo.PERFIS.items()],
                "rodizio": "a partida de número n enfrenta o perfil n módulo 6, na ordem acima",
                "pisos": {k: {"nome": v["nome"], **{pn: {"mu": v[pn][0], "psi_ideal": v[pn][1]} for pn in jogo.PNEUS}} for k, v in jogo.PISOS.items()},
                "cenarios": {k: {"nome": n, "piso": pi} for k, (n, pi) in jogo.CENARIOS.items()}}

    # ------------------------------------------------ conta e perfil
    @app.get("/api/conta")
    def conta(request: Request):
        u = usuario(request)
        p = perfil(u["id"])
        return {"email": u["email"], "perfil": p and {k: p[k] for k in ("apelido", "nascimento", "pix_chave", "pix_tipo", "nivel", "xp", "vitorias", "derrotas", "limite_dep_dia", "autoexclusao_ate")},
                "saldo": ledger.saldos(db, u["id"]), "acerto": jogo.validar_acerto(json.loads(p["acerto"]) if p and p.get("acerto") else None),
                "garagem": garagem_de(u["id"]),
                "box": {"pneus": jogo.PNEUS, "relacoes": list(jogo.RELACOES), "mapas": {k: v["nome"] for k, v in jogo.MAPAS.items()}, "psi": [jogo.PSI_MIN, jogo.PSI_MAX]}}

    @app.post("/api/box")
    async def salvar_box(request: Request):
        """Box (fora da arena): acerto e garagem ficam no perfil; a partida tira uma foto do acerto na hora de entrar."""
        u = usuario(request)
        exigir_perfil(u)
        b = await request.json()
        ac = jogo.validar_acerto(b.get("acerto"))
        g = b.get("garagem") or {}
        garagem = {"modelo": str(g.get("modelo") or "fam3500")[:20], "cor": str(g.get("cor") or "#c49a46")[:9], "roda": str(g.get("roda") or "#d9d9d9")[:9]}
        db.exec("UPDATE perfis SET acerto=?, garagem=? WHERE usuario=?", (json.dumps(ac), json.dumps(garagem), u["id"]))
        return {"ok": True, "acerto": ac, "garagem": garagem}

    @app.post("/api/perfil")
    async def salvar_perfil(request: Request):
        u = usuario(request)
        b = await request.json()
        apelido = str(b.get("apelido") or "").strip()[:24]
        nasc = str(b.get("nascimento") or "")
        if len(apelido) < 3:
            raise HTTPException(422, "apelido com pelo menos 3 letras")
        if idade(nasc) < 18:
            raise HTTPException(403, "a Arena Bruta é só para maiores de 18 anos")
        if db.um("SELECT 1 FROM perfis WHERE lower(apelido)=lower(?) AND usuario<>?", (apelido, u["id"])):
            raise HTTPException(409, "esse apelido já tem dono")
        p = perfil(u["id"])
        if p and p["nascimento"] != nasc:
            raise HTTPException(409, "a data de nascimento não pode ser trocada; fale com o suporte")
        tipo = str(b.get("pix_tipo") or "")[:12]
        chave = str(b.get("pix_chave") or "").strip()[:80]
        if p:
            db.exec("UPDATE perfis SET apelido=?, pix_chave=?, pix_tipo=? WHERE usuario=?", (apelido, chave, tipo, u["id"]))
        else:
            db.exec("INSERT INTO perfis(usuario,apelido,nascimento,pix_chave,pix_tipo,criado) VALUES(?,?,?,?,?,?)", (u["id"], apelido, nasc, chave, tipo, agora()))
        return {"ok": True}

    @app.post("/api/limites")
    async def limites(request: Request):
        u = usuario(request)
        exigir_perfil(u)
        b = await request.json()
        if "limite_dep_dia" in b:
            db.exec("UPDATE perfis SET limite_dep_dia=? WHERE usuario=?", (max(0, int(b["limite_dep_dia"] or 0)), u["id"]))
        dias = int(b.get("pausa_dias") or 0)
        if dias in (1, 7, 30, 180):
            db.exec("UPDATE perfis SET autoexclusao_ate=? WHERE usuario=?", (agora() + dias * 86400, u["id"]))
        return {"ok": True}

    # ------------------------------------------------ carteira
    @app.get("/api/carteira")
    def carteira(request: Request):
        u = usuario(request)
        return {"saldo": ledger.saldos(db, u["id"]), "extrato": ledger.extrato(db, u["id"]),
                "depositos": db.todos("SELECT id, valor, estado, criado, copia_cola FROM depositos WHERE usuario=? ORDER BY id DESC LIMIT 10", (u["id"],)),
                "saques": db.todos("SELECT id, valor, estado, criado, obs FROM saques WHERE usuario=? ORDER BY id DESC LIMIT 10", (u["id"],))}

    @app.post("/api/deposito")
    async def depositar(request: Request):
        u = usuario(request)
        p = exigir_perfil(u)
        b = await request.json()
        valor = int(round(float(b.get("valor") or 0) * 100))
        if not DEP_MIN <= valor <= DEP_MAX:
            raise HTTPException(422, "depósito entre R$ 10,00 e R$ 5.000,00")
        if p["limite_dep_dia"]:
            hoje = db.um("SELECT COALESCE(SUM(valor),0) s FROM depositos WHERE usuario=? AND criado>? AND estado<>'cancelado'", (u["id"], hoje_ini()))["s"]
            if hoje + valor > p["limite_dep_dia"]:
                raise HTTPException(403, "passa do seu limite diário de depósito (você mesmo definiu em Limites)")
        did = db.exec("INSERT INTO depositos(usuario,valor,estado,provedor,criado) VALUES(?,?,?,?,?)", (u["id"], valor, "pendente", pag.nome, agora())).lastrowid
        d = pag.create_deposit(did, valor, u["email"])
        db.exec("UPDATE depositos SET externo=?, copia_cola=? WHERE id=?", (d.externo, d.copia_cola, did))
        return {"id": did, "valor": valor, "instrucoes": d.instrucoes, "copia_cola": d.copia_cola, "estado": "pendente"}

    @app.post("/api/deposito/{did}/paguei")
    def paguei(did: int, request: Request):
        u = usuario(request)
        d = db.um("SELECT * FROM depositos WHERE id=? AND usuario=?", (did, u["id"]))
        if not d:
            raise HTTPException(404, "depósito não encontrado")
        db.exec("UPDATE depositos SET obs='cliente informou pagamento' WHERE id=? AND estado='pendente'", (did,))
        return {"ok": True}

    @app.post("/api/saque")
    async def sacar(request: Request):
        u = usuario(request)
        p = exigir_perfil(u)
        if not p["pix_chave"]:
            raise HTTPException(428, "cadastre a sua chave Pix (no seu nome) no perfil antes de sacar")
        b = await request.json()
        valor = int(round(float(b.get("valor") or 0) * 100))
        if valor < SAQUE_MIN:
            raise HTTPException(422, "saque mínimo de R$ 10,00")
        sid = db.exec("INSERT INTO saques(usuario,valor,estado,pix_chave,pix_tipo,criado) VALUES(?,?,?,?,?,?)",
                      (u["id"], valor, "pendente", p["pix_chave"], p["pix_tipo"], agora())).lastrowid
        try:
            ledger.pedir_saque(db, sid, u["id"], valor)
        except ledger.SaldoInsuficiente:
            db.exec("DELETE FROM saques WHERE id=?", (sid,))
            raise HTTPException(402, "saldo disponível insuficiente")
        pag.request_withdrawal(sid, valor, p["pix_chave"], p["pix_tipo"])
        return {"id": sid, "estado": "pendente", "aviso": "Saque pedido. Ele é conferido e pago no seu Pix; você acompanha aqui."}

    # ------------------------------------------------ fila e partidas
    @app.post("/api/fila")
    async def fila(request: Request):
        u = usuario(request)
        p = exigir_perfil(u)
        b = await request.json()
        modo = "treino" if b.get("modo") == "treino" else "combate"
        arena = str(b.get("arena") or "peao")
        if arena not in ledger.ARENAS:
            raise HTTPException(422, "arena inválida")
        if db.um("SELECT 1 FROM partidas WHERE (jog_a=? OR jog_b=?) AND estado IN ('fila','pronta','jogando')", (u["id"], u["id"])):
            raise HTTPException(409, "você já está numa partida")
        meu_acerto = json.dumps(jogo.validar_acerto(json.loads(p["acerto"]) if p.get("acerto") else None))  # foto do Box na entrada
        if modo == "treino":
            # modo história / treino (grátis): escolhe cenário e nível 1..20 do rival; perfil por rodízio
            nivel = max(1, min(20, int(b.get("nivel") or 1)))
            cen = str(b.get("cenario") or "treino")
            cen = cen if cen in jogo.CENARIOS else "treino"
            pid = db.exec("INSERT INTO partidas(jogo,arena,modo,entrada,jog_a,bot_nivel,estado,criado,cenario,piso,acerto_a) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                          ("cabo-de-guerra", arena, "treino", 0, u["id"], nivel, "pronta", agora(), cen, jogo.CENARIOS[cen][1], meu_acerto)).lastrowid
            db.exec("UPDATE partidas SET bot_perfil=? WHERE id=?", (jogo.perfil_da_partida(pid), pid))
            return vista_partida(db.um("SELECT * FROM partidas WHERE id=?", (pid,)), u["id"])
        entrada = ledger.ARENAS[arena][1]
        limpar_abandonos()
        # procura alguém esperando na mesma arena (PvP primeiro, sempre), e que esteja mesmo esperando agora
        alvo = db.um("SELECT * FROM partidas WHERE modo='combate' AND arena=? AND estado='fila' AND jog_b IS NULL AND jog_a<>? AND MAX(visto, criado)>? ORDER BY criado LIMIT 1",
                     (arena, u["id"], agora() - VIVO_S))
        if alvo:
            try:
                ledger.reservar(db, u["id"], entrada, alvo["id"])
            except ledger.SaldoInsuficiente:
                raise HTTPException(402, "saldo insuficiente para esta arena")
            db.exec("UPDATE partidas SET jog_b=?, acerto_b=?, estado='pronta' WHERE id=? AND jog_b IS NULL", (u["id"], meu_acerto, alvo["id"]))
            return vista_partida(db.um("SELECT * FROM partidas WHERE id=?", (alvo["id"],)), u["id"])
        nome_cena, piso_arena = jogo.CENARIOS[arena]
        pid = db.exec("INSERT INTO partidas(jogo,arena,modo,entrada,jog_a,estado,criado,visto,cenario,piso,acerto_a) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                      ("cabo-de-guerra", arena, "combate", entrada, u["id"], "fila", agora(), agora(), arena, piso_arena, meu_acerto)).lastrowid
        try:
            ledger.reservar(db, u["id"], entrada, pid)
        except ledger.SaldoInsuficiente:
            db.exec("UPDATE partidas SET estado='cancelada' WHERE id=?", (pid,))
            raise HTTPException(402, "saldo insuficiente para esta arena")
        return vista_partida(db.um("SELECT * FROM partidas WHERE id=?", (pid,)), u["id"])

    @app.get("/api/partida/{pid}")
    def ver_partida(pid: int, request: Request):
        u = usuario(request)
        p = db.um("SELECT * FROM partidas WHERE id=? AND (jog_a=? OR jog_b=?)", (pid, u["id"], u["id"]))
        if not p:
            raise HTTPException(404, "partida não encontrada")
        if p["estado"] == "fila" and p["jog_a"] == u["id"]:
            db.exec("UPDATE partidas SET visto=? WHERE id=?", (agora(), pid))
        # ninguém apareceu: entra um competidor da casa de nível fixo (se os tetos deixarem)
        if p["estado"] == "fila" and agora() - p["criado"] >= ESPERA_HUMANO_S:
            ok, motivo = pode_bot(p["jog_a"], p["entrada"])
            if ok:
                # PvP sem nível: entra um PERFIL da casa (rodízio fixo pela partida), sempre na força cheia (bot_nivel = 20)
                db.exec("UPDATE partidas SET bot_nivel=20, bot_perfil=?, estado='pronta' WHERE id=? AND estado='fila'", (jogo.perfil_da_partida(pid), pid))
                p = db.um("SELECT * FROM partidas WHERE id=?", (pid,))
        return vista_partida(p, u["id"])

    def limpar_abandonos() -> None:
        for p in db.todos("SELECT * FROM partidas WHERE estado='fila' AND MAX(visto, criado)<?", (agora() - ABANDONO_S,)):
            db.exec("UPDATE partidas SET estado='cancelada', fim=? WHERE id=? AND estado='fila'", (agora(), p["id"]))
            if p["entrada"]:
                ledger.devolver(db, p["jog_a"], p["entrada"], p["id"], "saiu da página na fila")

    @app.post("/api/partida/{pid}/sair")
    def sair_fila(pid: int, request: Request):
        u = usuario(request)
        p = db.um("SELECT * FROM partidas WHERE id=? AND jog_a=? AND estado='fila'", (pid, u["id"]))
        if not p:
            raise HTTPException(409, "só dá para sair enquanto procura adversário")
        db.exec("UPDATE partidas SET estado='cancelada', fim=? WHERE id=?", (agora(), pid))
        if p["entrada"]:
            ledger.devolver(db, u["id"], p["entrada"], pid, "saiu da fila")
        return {"ok": True}

    @app.get("/api/partidas")
    def minhas(request: Request):
        u = usuario(request)
        ps = db.todos("SELECT * FROM partidas WHERE (jog_a=? OR jog_b=?) AND estado IN ('terminada','cancelada') ORDER BY id DESC LIMIT 20", (u["id"], u["id"]))
        return {"partidas": [vista_partida(p, u["id"]) | {"fim": p["fim"], "resultado": json.loads(p["resultado"] or "{}").get("posicao")} for p in ps]}

    @app.get("/api/partida/{pid}/replay")
    def replay(pid: int, request: Request):
        u = usuario(request)
        p = db.um("SELECT * FROM partidas WHERE id=? AND (jog_a=? OR jog_b=?) AND estado='terminada'", (pid, u["id"], u["id"]))
        if not p:
            raise HTTPException(404, "replay não encontrado")
        r = refazer(p)
        return {"vencedor": r["vencedor"], "confere": r["vencedor"] == p["vencedor"], "quadros": r["quadros"]}

    def refazer(p: dict, entradas_a: list | None = None, entradas_b: list | None = None) -> dict:
        """Replay oficial: refaz a conta com o motor da versão em que a partida foi jogada."""
        ea = entradas_a if entradas_a is not None else json.loads(p["entradas_a"] or "[]")
        eb = entradas_b if entradas_b is not None else json.loads(p["entradas_b"] or "[]")
        motor = json.loads(p["resultado"] or "{}").get("motor") if p.get("resultado") else None
        if motor == 2 or (motor is None and not p.get("piso") and p.get("estado") == "terminada"):
            from app import jogo_v2
            return jogo_v2.simular(ea, eb, p["bot_nivel"])
        return jogo.simular(ea, eb, ficha_do_bot(p), json.loads(p["acerto_a"] or "null"), json.loads(p["acerto_b"] or "null"), p.get("piso") or "curral")

    # ------------------------------------------------ partida ao vivo (WebSocket)
    class Ao:
        """Uma partida rodando no servidor: física em passo fixo, comandos dos dois lados, transmissão do estado."""

        def __init__(self, p: dict):
            self.p = p
            piso = p.get("piso") or "curral"
            self.bot = ficha_do_bot(p)
            self.carros = {"a": jogo.novo_carro(json.loads(p["acerto_a"] or "null"), piso),
                           "b": jogo.novo_carro(self.bot["acerto"] if self.bot else json.loads(p["acerto_b"] or "null"), piso)}
            self.fila = {"a": [], "b": []}
            self.entradas = {"a": [], "b": []}
            self.ws: dict[str, WebSocket] = {}
            self.pos = 0
            self.tick = -3 * jogo.TICKS_S  # contagem regressiva de 3 s
            self.tarefa = None
            self.contagem_cmd = {"a": 0, "b": 0}

        async def enviar(self, msg: dict):
            for lado, w in list(self.ws.items()):
                try:
                    await w.send_text(json.dumps(msg))
                except Exception:  # noqa: BLE001
                    self.ws.pop(lado, None)

        def pronto_para_comecar(self) -> bool:
            return "a" in self.ws and (self.p["bot_nivel"] or "b" in self.ws)

        async def comecar(self):
            # bot ou os dois conectados: começa na hora; PvP com um ausente: espera até ESPERA_ADVERSARIO_S e começa
            # assim mesmo (quem não conectou fica com o carro parado, como na regra de queda publicada)
            t0 = time.monotonic()
            while not self.pronto_para_comecar() and time.monotonic() - t0 < ESPERA_ADVERSARIO_S:
                await asyncio.sleep(0.25)
            if not self.ws:
                ao_vivo.pop(self.p["id"], None)
                return
            await self.rodar()

        async def rodar(self):
            db.exec("UPDATE partidas SET estado='jogando' WHERE id=?", (self.p["id"],))
            inicio = time.monotonic()
            passo = 0
            while True:
                if self.tick >= 0:
                    t = self.tick
                    for lado in ("a", "b"):
                        for cmd in self.fila[lado]:
                            jogo.aplicar(self.carros[lado], cmd)
                            self.entradas[lado].append([t, cmd])
                        self.fila[lado] = []
                    if self.bot:
                        jogo.aplicar(self.carros["b"], jogo.piloto(self.bot["piloto"], t, self.carros["b"]))
                    fa, fb = jogo.passo_carro(self.carros["a"]), jogo.passo_carro(self.carros["b"])
                    self.pos = max(-jogo.CHEGADA, min(jogo.CHEGADA, self.pos + jogo.puxao(fa, fb)))
                    if t % 2 == 0:
                        await self.enviar({"t": "estado", "tick": t, "pos": self.pos,
                                           "a": {k: self.carros["a"][k] for k in ("rpm", "marcha", "temp", "forca", "fervendo", "patinou", "acel")},
                                           "b": {k: self.carros["b"][k] for k in ("rpm", "marcha", "temp", "forca", "fervendo", "patinou", "acel")}})
                    if abs(self.pos) >= jogo.CHEGADA or t + 1 >= jogo.DURACAO:
                        break
                elif self.tick % jogo.TICKS_S == 0:
                    await self.enviar({"t": "contagem", "n": -self.tick // jogo.TICKS_S})
                self.tick += 1
                passo += 1
                atraso = inicio + passo * tick_s - time.monotonic()
                await asyncio.sleep(max(0.0, atraso))  # sempre cede a vez (recebe comandos entre os ticks)
            await self.encerrar()

        async def encerrar(self):
            p = self.p
            # o resultado oficial é o replay das entradas gravadas (garante que ao vivo == replay)
            r = refazer(p, self.entradas["a"], self.entradas["b"])
            venc = r["vencedor"]
            db.exec("UPDATE partidas SET estado='terminada', vencedor=?, resultado=?, fim=?, entradas_a=?, entradas_b=? WHERE id=?",
                    (venc, json.dumps({"posicao": r["posicao"], "ticks": r["ticks"], "motor": r["motor"]}), agora(),
                     json.dumps(self.entradas["a"]), json.dumps(self.entradas["b"]), p["id"]))
            liquidar(p, venc)
            await self.enviar({"t": "fim", "vencedor": venc, "posicao": r["posicao"], "premio": ledger.premio(p["entrada"], cfg.comissao_pct) if p["modo"] == "combate" else 0})
            ao_vivo.pop(p["id"], None)

    def liquidar(p: dict, venc: str) -> None:
        a, b, e = p["jog_a"], p["jog_b"], p["entrada"]
        for uid, ganhou in ((a, venc == "a"), (b, venc == "b")):
            if uid:
                xp = 30 if ganhou else 10 if venc != "empate" else 15
                db.exec("""UPDATE perfis SET xp=xp+?, vitorias=vitorias+?, derrotas=derrotas+?, nivel=MIN(20, 1 + (xp+?)/100) WHERE usuario=?""",
                        (xp, 1 if ganhou else 0, 1 if (venc != "empate" and not ganhou) else 0, xp, uid))
        if p["modo"] != "combate":
            db.exec("UPDATE partidas SET liquidada=1 WHERE id=?", (p["id"],))
            return
        if venc == "empate":
            ledger.devolver(db, a, e, p["id"], "empate")
            if b:
                ledger.devolver(db, b, e, p["id"], "empate")
        elif p["bot_nivel"]:
            ledger.liquidar_bot(db, p["id"], a, e, cfg.comissao_pct, venc == "a")
            if perda_casa_hoje() >= ajuste("teto_perda_dia"):
                alerta("perda_dia", f"A casa passou do teto de perda do dia contra bots: R$ {perda_casa_hoje() / 100:.2f}.")
            if venc == "a" and ganho_jogador_bots_hoje(a) >= ajuste("teto_ganho_jogador_dia"):
                alerta("ganho_jogador", f"{perfil(a)['apelido']} ganhou R$ {ganho_jogador_bots_hoje(a) / 100:.2f} contra bots hoje.", a)
        else:
            ledger.liquidar_pvp(db, p["id"], a if venc == "a" else b, b if venc == "a" else a, e, cfg.comissao_pct)
        db.exec("UPDATE partidas SET liquidada=1 WHERE id=?", (p["id"],))

    @app.websocket("/ws/partida/{pid}")
    async def ws_partida(ws: WebSocket, pid: int):
        u = auth.usuario_da_sessao(db, cfg.segredo_sessao, ws.cookies.get(COOKIE))
        p = db.um("SELECT * FROM partidas WHERE id=?", (pid,)) if u else None
        if not u or not p or u["id"] not in (p["jog_a"], p["jog_b"]) or p["estado"] not in ("pronta", "jogando"):
            await ws.close(code=4004)
            return
        await ws.accept()
        lado = "a" if p["jog_a"] == u["id"] else "b"
        ao = ao_vivo.get(pid)
        if not ao:
            ao = ao_vivo[pid] = Ao(p)
        ao.ws[lado] = ws
        await ws.send_text(json.dumps({"t": "ok", "lado": lado, "partida": vista_partida(p, u["id"])}))
        if not ao.tarefa:
            ao.tarefa = asyncio.create_task(ao.comecar())
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                cmd = jogo.validar_cmd(msg.get("cmd") or {})
                if cmd:
                    # comandos da contagem regressiva valem no tick 0 (o jogador já pode segurar o acelerador no "3, 2, 1")
                    ao.contagem_cmd[lado] += 1
                    if ao.contagem_cmd[lado] > 12 * (max(0, ao.tick) // jogo.TICKS_S + 3):  # mais comandos que um humano consegue
                        alerta("automacao", f"Comandos demais na partida {pid} (possível robô).", u["id"])
                        continue
                    ao.fila[lado].append(cmd)
        except (WebSocketDisconnect, ValueError, RuntimeError):
            ao.ws.pop(lado, None)
            # caiu: o carro dele para de acelerar (regra publicada); a partida segue até o fim
            ao.fila[lado].append({"acel": 0})

    # ------------------------------------------------ painel da casa (/admin/arena)
    adm = admin.rotas(db, cfg.segredo_sessao, """SELECT u.email, u.criado, p.apelido plano, 0 ativo_ate, 1 ativo
        FROM usuarios u LEFT JOIN perfis p ON p.usuario=u.id ORDER BY u.criado DESC""", seguro=not cfg.dev)
    app.include_router(adm)

    @app.get("/api/painel/arena")
    def painel_resumo(request: Request):
        adm.checar(request)
        return {
            "caixa": {"receita": ledger.saldo(db, "casa:receita"), "bots": ledger.saldo(db, "casa:bots"), "perda_hoje": perda_casa_hoje(),
                      "exposicao": exposicao_bots(), "custodia": -ledger.saldo(db, "ext:pix")},
            "ajustes": {k: ajuste(k) for k in AJUSTES_PADRAO},
            "depositos": db.todos("SELECT d.*, u.email FROM depositos d JOIN usuarios u ON u.id=d.usuario WHERE d.estado='pendente' ORDER BY d.id"),
            "saques": db.todos("SELECT s.*, u.email, p.apelido FROM saques s JOIN usuarios u ON u.id=s.usuario LEFT JOIN perfis p ON p.usuario=s.usuario WHERE s.estado='pendente' ORDER BY s.id"),
            "alertas": db.todos("SELECT * FROM alertas ORDER BY visto, id DESC LIMIT 50"),
            "nao_vistos": db.um("SELECT COUNT(*) n FROM alertas WHERE visto=0")["n"],
            "partidas_hoje": db.um("SELECT COUNT(*) n FROM partidas WHERE criado>?", (hoje_ini(),))["n"],
            "invariantes": ledger.conferir(db),
        }

    @app.post("/api/painel/arena/deposito/{did}/{acao}")
    def painel_deposito(did: int, acao: str, request: Request):
        adm.checar(request)
        d = db.um("SELECT * FROM depositos WHERE id=?", (did,))
        if not d or d["estado"] != "pendente":
            raise HTTPException(409, "depósito não está pendente")
        if acao == "confirmar":
            ledger.credito_deposito(db, d)
            db.exec("UPDATE depositos SET estado='confirmado', confirmado=? WHERE id=?", (agora(), did))
        elif acao == "cancelar":
            db.exec("UPDATE depositos SET estado='cancelado', confirmado=? WHERE id=?", (agora(), did))
        else:
            raise HTTPException(400, "ação inválida")
        return {"ok": True}

    @app.post("/api/painel/arena/saque/{sid}/{acao}")
    async def painel_saque(sid: int, acao: str, request: Request):
        adm.checar(request)
        s = db.um("SELECT * FROM saques WHERE id=?", (sid,))
        if not s or s["estado"] != "pendente":
            raise HTTPException(409, "saque não está pendente")
        b = await request.json() if (await request.body()) else {}
        if acao == "pagar":
            ledger.pagar_saque(db, sid, s["usuario"], s["valor"])
            db.exec("UPDATE saques SET estado='pago', decidido=?, obs=? WHERE id=?", (agora(), str(b.get("obs") or "pago via Pix")[:200], sid))
        elif acao == "recusar":
            ledger.recusar_saque(db, sid, s["usuario"], s["valor"])
            db.exec("UPDATE saques SET estado='recusado', decidido=?, obs=? WHERE id=?", (agora(), str(b.get("obs") or "recusado")[:200], sid))
        else:
            raise HTTPException(400, "ação inválida")
        return {"ok": True}

    @app.post("/api/painel/arena/ajustes")
    async def painel_ajustes(request: Request):
        adm.checar(request)
        b = await request.json()
        for k in AJUSTES_PADRAO:
            if k in b:
                db.exec("INSERT INTO ajustes(chave,valor) VALUES(?,?) ON CONFLICT(chave) DO UPDATE SET valor=excluded.valor", (k, str(int(b[k]))))
        return {"ok": True}

    @app.post("/api/painel/arena/alertas/vistos")
    def painel_vistos(request: Request):
        adm.checar(request)
        db.exec("UPDATE alertas SET visto=1")
        return {"ok": True}

    # ------------------------------------------------ páginas
    app.mount("/s", StaticFiles(directory=ESTATICO), name="estatico")

    @app.get("/", response_class=HTMLResponse)
    def inicio():
        return FileResponse(ESTATICO / "index.html")

    @app.get("/app", response_class=HTMLResponse)
    def pagina_app():
        return FileResponse(ESTATICO / "app.html")

    @app.get("/sobre", response_class=HTMLResponse)
    def sobre():
        return FileResponse(ESTATICO / "sobre.html")

    @app.get("/regulamento", response_class=HTMLResponse)
    def pagina_regulamento():
        return FileResponse(ESTATICO / "regulamento.html")

    @app.get("/admin", response_class=HTMLResponse)
    def pagina_admin():
        return FileResponse(ESTATICO / "admin.html")

    @app.get("/admin/arena", response_class=HTMLResponse)
    def pagina_admin_arena():
        return FileResponse(ESTATICO / "admin-arena.html")

    return app


app = criar_app() if os.environ.get("ARENA_SEM_APP") != "1" else None
