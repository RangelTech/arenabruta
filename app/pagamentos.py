"""Pagamentos da Arena Bruta: interface única para plugar o gateway Pix depois (spec 45 §H).

Hoje roda o provedor MANUAL (sem gateway): o depósito mostra a chave Pix da casa e o painel confirma quando o dinheiro cai;
o saque é aprovado no painel e pago à mão. Para ligar um gateway: escrever uma classe com os mesmos métodos
(create_deposit, query_deposit, request_withdrawal, query_withdrawal, verify_webhook, reconcile) e trocar ARENA_PAGAMENTO.
O crédito na carteira SEMPRE passa por ledger.credito_deposito (idempotente pela chave dep:<id>).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Deposito:
    externo: str
    copia_cola: str
    instrucoes: str


class ProvedorManual:
    nome = "manual"

    def __init__(self, chave: str, nome_casa: str):
        self.chave, self.nome_casa = chave, nome_casa

    def create_deposit(self, dep_id: int, valor: int, email: str) -> Deposito:
        reais = f"{valor / 100:.2f}".replace(".", ",")
        if self.chave:
            instr = (f"Faça um Pix de R$ {reais} para a chave {self.chave} ({self.nome_casa}) e toque em \"Já paguei\". "
                     f"O saldo entra assim que o pagamento for confirmado.")
        else:
            instr = (f"Depósito de R$ {reais} registrado. O nosso time confirma o Pix e libera o saldo; você recebe um e-mail "
                     f"com os dados de pagamento.")
        return Deposito(externo=f"manual-{dep_id}", copia_cola=self.chave, instrucoes=instr)

    def query_deposit(self, externo: str) -> str:
        return "pendente"  # manual: quem confirma é o painel

    def request_withdrawal(self, saque_id: int, valor: int, chave: str, tipo: str) -> str:
        return "aguardando_aprovacao"

    def query_withdrawal(self, externo: str) -> str:
        return "aguardando_aprovacao"

    def verify_webhook(self, corpo: bytes, cabecalhos: dict) -> bool:
        return False  # sem gateway, não aceita webhook de pagamento

    def reconcile(self, desde: float) -> list[dict]:
        return []


def provedor(cfg) -> ProvedorManual:
    return ProvedorManual(cfg.pix_chave_casa, cfg.pix_nome_casa)
