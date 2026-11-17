"""Razão contábil de partidas dobradas da Arena Bruta (centavos inteiros, append-only).

Contas:
  u:<id>:disp       saldo disponível do jogador
  u:<id>:reserva    entradas reservadas em partidas em andamento
  u:<id>:saque      saques pedidos aguardando aprovação/pagamento
  casa:receita      comissão da plataforma
  casa:bots         resultado da casa nas partidas contra bots (a casa é a contraparte)
  ext:pix           mundo externo (o dinheiro que entra e sai pelo Pix)
Regras: toda transação soma zero; chave única = idempotência (repetir não lança de novo); saldo do jogador nunca negativo.
"""
from __future__ import annotations

from app.db import Banco, agora

ARENAS = {  # entrada por jogador em centavos (spec 45 §H / documento §2)
    "peao": ("Peão", 1000), "cowboy": ("Cowboy", 1800), "bruto": ("Bruto", 3240),
    "fazendeiro": ("Fazendeiro", 5832), "barao": ("Barão", 10497), "rei": ("Rei do Agro", 18895),
}


class SaldoInsuficiente(Exception):
    pass


def comissao(entrada: int, pct: float) -> int:
    """Comissão sobre o total (2 entradas), arredondada para o centavo mais próximo, metade para cima."""
    total = 2 * entrada
    return (total * int(round(pct * 100)) + 5000) // 10000


def premio(entrada: int, pct: float) -> int:
    return 2 * entrada - comissao(entrada, pct)


def saldo(db: Banco, conta: str) -> int:
    r = db.um("SELECT COALESCE(SUM(valor),0) s FROM lancamentos WHERE conta=?", (conta,))
    return int(r["s"])


def saldos(db: Banco, uid: int) -> dict:
    return {"disponivel": saldo(db, f"u:{uid}:disp"), "reservado": saldo(db, f"u:{uid}:reserva"), "saque": saldo(db, f"u:{uid}:saque")}


def lancar(db: Banco, chave: str, tipo: str, partes: list[tuple[str, int]], ref: str = "", descricao: str = "",
           nao_negativas: tuple[str, ...] = ()) -> bool:
    """Grava uma transação. Devolve False se a chave já existia (idempotente). Levanta SaldoInsuficiente sem gravar nada."""
    if sum(v for _, v in partes) != 0:
        raise ValueError("transação não fecha em zero")
    with db.tx() as c:
        if c.execute("SELECT 1 FROM transacoes WHERE chave=?", (chave,)).fetchone():
            return False
        for conta in nao_negativas:
            atual = c.execute("SELECT COALESCE(SUM(valor),0) FROM lancamentos WHERE conta=?", (conta,)).fetchone()[0]
            delta = sum(v for k, v in partes if k == conta)
            if atual + delta < 0:
                raise SaldoInsuficiente(conta)
        tid = c.execute("INSERT INTO transacoes(chave,tipo,ref,criado,descricao) VALUES(?,?,?,?,?)",
                        (chave, tipo, ref, agora(), descricao)).lastrowid
        for conta, valor in partes:
            if valor:
                c.execute("INSERT OR IGNORE INTO contas(id,tipo,usuario) VALUES(?,?,?)",
                          (conta, conta.split(":")[-1] if conta.startswith("u:") else conta, int(conta.split(":")[1]) if conta.startswith("u:") else None))
                c.execute("INSERT INTO lancamentos(transacao,conta,valor) VALUES(?,?,?)", (tid, conta, valor))
    return True


# ---------- operações ----------
def credito_deposito(db: Banco, dep: dict) -> bool:
    u = dep["usuario"]
    return lancar(db, f"dep:{dep['id']}", "deposito", [("ext:pix", -dep["valor"]), (f"u:{u}:disp", dep["valor"])], ref=str(dep["id"]),
                  descricao="Depósito Pix")


def reservar(db: Banco, uid: int, valor: int, partida: int) -> bool:
    return lancar(db, f"res:{partida}:{uid}", "reserva", [(f"u:{uid}:disp", -valor), (f"u:{uid}:reserva", valor)], ref=str(partida),
                  descricao="Entrada reservada", nao_negativas=(f"u:{uid}:disp",))


def devolver(db: Banco, uid: int, valor: int, partida: int, motivo: str) -> bool:
    return lancar(db, f"dev:{partida}:{uid}", "devolucao", [(f"u:{uid}:reserva", -valor), (f"u:{uid}:disp", valor)], ref=str(partida),
                  descricao=f"Entrada devolvida ({motivo})")


def liquidar_pvp(db: Banco, partida: int, vencedor: int, perdedor: int, entrada: int, pct: float) -> bool:
    c = comissao(entrada, pct)
    return lancar(db, f"liq:{partida}", "liquidacao", [(f"u:{vencedor}:reserva", -entrada), (f"u:{perdedor}:reserva", -entrada),
                                                       (f"u:{vencedor}:disp", 2 * entrada - c), ("casa:receita", c)], ref=str(partida),
                  descricao="Prêmio da partida")


def liquidar_bot(db: Banco, partida: int, uid: int, entrada: int, pct: float, jogador_venceu: bool) -> bool:
    """Contra a casa: a casa reservou o lado dela (entrada) antes; quem vence leva o prêmio, como no PvP."""
    c = comissao(entrada, pct)
    if jogador_venceu:
        partes = [(f"u:{uid}:reserva", -entrada), ("casa:bots", -entrada), (f"u:{uid}:disp", 2 * entrada - c), ("casa:receita", c)]
    else:
        partes = [(f"u:{uid}:reserva", -entrada), ("casa:bots", entrada)]
    return lancar(db, f"liq:{partida}", "liquidacao", partes, ref=str(partida), descricao="Prêmio da partida")


def pedir_saque(db: Banco, sid: int, uid: int, valor: int) -> bool:
    return lancar(db, f"saq:{sid}", "saque_pedido", [(f"u:{uid}:disp", -valor), (f"u:{uid}:saque", valor)], ref=str(sid),
                  descricao="Saque pedido", nao_negativas=(f"u:{uid}:disp",))


def pagar_saque(db: Banco, sid: int, uid: int, valor: int) -> bool:
    return lancar(db, f"saq-pago:{sid}", "saque_pago", [(f"u:{uid}:saque", -valor), ("ext:pix", valor)], ref=str(sid), descricao="Saque pago")


def recusar_saque(db: Banco, sid: int, uid: int, valor: int) -> bool:
    return lancar(db, f"saq-volta:{sid}", "saque_recusado", [(f"u:{uid}:saque", -valor), (f"u:{uid}:disp", valor)], ref=str(sid),
                  descricao="Saque devolvido ao saldo")


def extrato(db: Banco, uid: int, limite: int = 60) -> list[dict]:
    return db.todos("""SELECT t.criado, t.tipo, t.descricao, l.valor, l.conta FROM lancamentos l JOIN transacoes t ON t.id=l.transacao
                       WHERE l.conta IN (?,?) ORDER BY t.id DESC LIMIT ?""", (f"u:{uid}:disp", f"u:{uid}:saque", limite))


def conferir(db: Banco) -> dict:
    """Invariantes: soma geral zero; nenhum jogador com disponível negativo."""
    total = db.um("SELECT COALESCE(SUM(valor),0) s FROM lancamentos")["s"]
    neg = db.todos("SELECT conta, SUM(valor) s FROM lancamentos WHERE conta LIKE 'u:%:disp' GROUP BY conta HAVING s < 0")
    return {"soma_zero": total == 0, "negativos": neg}
