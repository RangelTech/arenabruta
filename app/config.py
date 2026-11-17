"""Configuração da Arena Bruta por variáveis de ambiente (segredos em /opt/platform/secrets/arenabruta.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Config:
    dados: str = "/data"
    base_url: str = "https://arena.rangeltech.net"
    segredo_sessao: str = "dev"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_senha: str = ""
    smtp_from: str = "Arena Bruta <contato@rangeltech.net>"
    demo_email: str = ""
    demo_senha: str = ""
    # pagamentos: "manual" (sem gateway: depósito e saque aprovados no painel). Trocar por um gateway = novo provedor.
    pagamento: str = "manual"
    pix_chave_casa: str = ""          # chave Pix da casa mostrada no depósito manual
    pix_nome_casa: str = "Rangel Tech"
    comissao_pct: float = 10.0
    dev: bool = False


def carregar() -> Config:
    e = os.environ.get
    return Config(
        dados=e("ARENA_DADOS", "/data"),
        base_url=e("ARENA_BASE_URL", "https://arena.rangeltech.net").rstrip("/"),
        segredo_sessao=e("ARENA_SEGREDO_SESSAO", "dev"),
        smtp_host=e("SMTP_HOST", ""),
        smtp_port=int(e("SMTP_PORT", "587") or 587),
        smtp_user=e("SMTP_USER", ""),
        smtp_senha=e("SMTP_PASSWORD", ""),
        smtp_from=e("ARENA_SMTP_FROM", "Arena Bruta <contato@rangeltech.net>"),
        demo_email=e("ARENA_DEMO_EMAIL", ""),
        demo_senha=e("ARENA_DEMO_SENHA", ""),
        pagamento=e("ARENA_PAGAMENTO", "manual"),
        pix_chave_casa=e("ARENA_PIX_CHAVE", ""),
        pix_nome_casa=e("ARENA_PIX_NOME", "Rangel Tech"),
        comissao_pct=float(e("ARENA_COMISSAO_PCT", "10") or 10),
        dev=e("ARENA_DEV", "") == "1",
    )
