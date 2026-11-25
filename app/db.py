"""Banco da Arena Bruta: SQLite num volume (/data). Dinheiro SEMPRE em centavos inteiros. Hora em epoch (s).

Razão contábil de partidas dobradas (append-only): cada transação tem lançamentos que somam ZERO; o saldo de uma conta é a
soma dos lançamentos dela. Nada é editado: correção = lançamento compensatório. Ver app/ledger.py.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
import threading
import time
from contextlib import contextmanager

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, criado REAL NOT NULL,
  plano TEXT NOT NULL DEFAULT 'teste', ativo_ate REAL NOT NULL DEFAULT 0, pedido TEXT);
CREATE TABLE IF NOT EXISTS codigos (email TEXT PRIMARY KEY, hash TEXT NOT NULL, expira REAL NOT NULL, tentativas INTEGER NOT NULL DEFAULT 0, enviado REAL NOT NULL);
CREATE TABLE IF NOT EXISTS sessoes (hash TEXT PRIMARY KEY, usuario INTEGER NOT NULL, expira REAL NOT NULL);
CREATE TABLE IF NOT EXISTS assinaturas (usuario INTEGER PRIMARY KEY, plano TEXT NOT NULL, ativo_ate REAL NOT NULL, pedido TEXT);

CREATE TABLE IF NOT EXISTS perfis (usuario INTEGER PRIMARY KEY, apelido TEXT NOT NULL, nascimento TEXT NOT NULL, pix_chave TEXT NOT NULL DEFAULT '',
  pix_tipo TEXT NOT NULL DEFAULT '', nivel INTEGER NOT NULL DEFAULT 1, xp INTEGER NOT NULL DEFAULT 0, vitorias INTEGER NOT NULL DEFAULT 0,
  derrotas INTEGER NOT NULL DEFAULT 0, autoexclusao_ate REAL NOT NULL DEFAULT 0, limite_dep_dia INTEGER NOT NULL DEFAULT 0, criado REAL NOT NULL);

-- razão contábil (centavos)
CREATE TABLE IF NOT EXISTS contas (id TEXT PRIMARY KEY, tipo TEXT NOT NULL, usuario INTEGER);   -- ex.: u:7:disp, u:7:reserva, casa:receita
CREATE TABLE IF NOT EXISTS transacoes (id INTEGER PRIMARY KEY, chave TEXT UNIQUE NOT NULL, tipo TEXT NOT NULL, ref TEXT NOT NULL DEFAULT '',
  criado REAL NOT NULL, descricao TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS lancamentos (id INTEGER PRIMARY KEY, transacao INTEGER NOT NULL, conta TEXT NOT NULL, valor INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS lanc_conta ON lancamentos(conta);

-- depósitos e saques (estado independente da razão)
CREATE TABLE IF NOT EXISTS depositos (id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, valor INTEGER NOT NULL, estado TEXT NOT NULL,
  provedor TEXT NOT NULL, externo TEXT NOT NULL DEFAULT '', copia_cola TEXT NOT NULL DEFAULT '', criado REAL NOT NULL, confirmado REAL, obs TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS saques (id INTEGER PRIMARY KEY, usuario INTEGER NOT NULL, valor INTEGER NOT NULL, estado TEXT NOT NULL,
  pix_chave TEXT NOT NULL, pix_tipo TEXT NOT NULL, criado REAL NOT NULL, decidido REAL, obs TEXT NOT NULL DEFAULT '');

-- partidas (estado do jogo e da liquidação separados)
CREATE TABLE IF NOT EXISTS partidas (id INTEGER PRIMARY KEY, jogo TEXT NOT NULL, arena TEXT NOT NULL, modo TEXT NOT NULL,   -- treino | combate
  entrada INTEGER NOT NULL, jog_a INTEGER NOT NULL, jog_b INTEGER, bot_nivel INTEGER, estado TEXT NOT NULL,                -- fila|jogando|terminada|cancelada
  vencedor TEXT, resultado TEXT NOT NULL DEFAULT '', liquidada INTEGER NOT NULL DEFAULT 0, criado REAL NOT NULL, fim REAL,
  entradas_a TEXT NOT NULL DEFAULT '', entradas_b TEXT NOT NULL DEFAULT '');

CREATE TABLE IF NOT EXISTS ajustes (chave TEXT PRIMARY KEY, valor TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS alertas (id INTEGER PRIMARY KEY, tipo TEXT NOT NULL, texto TEXT NOT NULL, usuario INTEGER, criado REAL NOT NULL, visto INTEGER NOT NULL DEFAULT 0);
"""


class BancoSQLite:
    def __init__(self, caminho: str):
        self._trava = threading.RLock()
        self.con = sqlite3.connect(caminho, check_same_thread=False, isolation_level=None)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(ESQUEMA)
        _migrar_esquema(self)

    @contextmanager
    def tx(self):
        with self._trava:
            self.con.execute("BEGIN IMMEDIATE")
            try:
                yield self.con
                self.con.execute("COMMIT")
            except BaseException:
                self.con.execute("ROLLBACK")
                raise

    def exec(self, sql: str, args: tuple = ()):
        with self._trava:
            return self.con.execute(sql, args)

    def um(self, sql: str, args: tuple = ()) -> dict | None:
        with self._trava:
            r = self.con.execute(sql, args).fetchone()
        return dict(r) if r else None

    def todos(self, sql: str, args: tuple = ()) -> list[dict]:
        with self._trava:
            return [dict(r) for r in self.con.execute(sql, args).fetchall()]


def agora() -> float:
    return time.time()


def Banco(caminho: str):
    """Postgres central (banco `produtos`, schema do produto) quando PRODUTOS_DATABASE_URL existe; senão o SQLite de antes
    (plano de volta). Spec 57, seção 8. PRODUTOS_SCHEMA_TESTE=1 dá um schema novo por instância (testes isolados)."""
    dsn = os.environ.get("PRODUTOS_DATABASE_URL")
    if not dsn:
        return BancoSQLite(caminho)
    from produtos_core.banco_pg import Banco as BancoPG
    schema = os.environ.get("PRODUTOS_SCHEMA", "arenabruta")
    if os.environ.get("PRODUTOS_SCHEMA_TESTE"):
        schema = "teste_" + uuid.uuid4().hex[:10]
    b = BancoPG(dsn, schema, ESQUEMA)
    _migrar_esquema(b)
    return b


def _migrar_esquema(self):
    """Migrações de coluna e tabela (rodam no SQLite e no Postgres; spec 57)."""
    # v0.1.4: "visto" = última vez que quem espera na fila consultou a partida (fila fantasma não pareia)
    # v0.2 (motor v3, spec 46): cenário/piso, acerto de cada lado, perfil do bot; Box e Garagem no perfil
    for tab, col, tipo in (("partidas", "piso", "TEXT"), ("partidas", "cenario", "TEXT"), ("partidas", "acerto_a", "TEXT"), ("partidas", "acerto_b", "TEXT"),
                           ("partidas", "bot_perfil", "TEXT"), ("perfis", "acerto", "TEXT"), ("perfis", "garagem", "TEXT")):
        if col not in [r[1] for r in self.con.execute(f"PRAGMA table_info({tab})")]:
            self.con.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {tipo}")
    if "visto" not in [r[1] for r in self.con.execute("PRAGMA table_info(partidas)")]:
        self.con.execute("ALTER TABLE partidas ADD COLUMN visto REAL NOT NULL DEFAULT 0")
        self.con.commit()
