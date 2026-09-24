"""
f360_api.py - Parcelas de título (com Vencimento e Liquidação) via API pública F360.

Endpoint: GET /ParcelasDeTituloPublicAPI/ListarParcelasDeTitulos
Limites do F360: 100 itens por página, janela máxima de 31 dias por consulta.
"""
import re
from datetime import timedelta

import pandas as pd
import requests

BASE = "https://financas.f360.com.br"
JANELA_DIAS = 30  # margem de segurança sobre o limite de 31 dias


def autenticar_f360(token_api):
    try:
        r = requests.post(
            f"{BASE}/PublicLoginAPI/DoLogin",
            json={"token": token_api},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        if r.status_code == 200:
            res = r.json()
            if isinstance(res, dict):
                return res.get("Token") or res.get("Result") or res.get("token")
            return res
    except requests.RequestException:
        pass
    return None


def _janelas(d_ini, d_fim):
    atual = d_ini
    while atual <= d_fim:
        fim = min(atual + timedelta(days=JANELA_DIAS - 1), d_fim)
        yield atual, fim
        atual = fim + timedelta(days=1)


def _listar(jwt, tipo, ini, fim, tipo_datas, cnpjs):
    """Percorre todas as páginas de uma janela de até 31 dias."""
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/ParcelasDeTituloPublicAPI/ListarParcelasDeTitulos"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {
            "pagina": pagina,
            "tipo": tipo,  # Despesa | Receita | Ambos
            "inicio": ini.isoformat(),
            "fim": fim.isoformat(),
            "tipoDatas": tipo_datas,
            "status": "Todos",
        }
        if cnpjs:
            params["empresas"] = ",".join(cnpjs)
        r = requests.get(url, headers=headers, params=params, timeout=60)
        r.raise_for_status()
        res = r.json().get("Result") or {}
        saida.extend(res.get("Parcelas", []))
        total = res.get("QuantidadeDePaginas", 1) or 1
        pagina += 1
    return saida


def _so_digitos(s):
    return re.sub(r"\D", "", str(s or ""))


def _normaliza(parcelas, mapa_cnpj):
    mapa = {_so_digitos(k): v for k, v in mapa_cnpj.items()}
    linhas = []
    for p in parcelas:
        status = str(p.get("Status", ""))
        s_low = status.lower()
        if p.get("Cancelada") or "cancelad" in s_low or "baixad" in s_low:
            continue

        tit = p.get("DadosDoTitulo") or {}
        cnpj = _so_digitos((tit.get("Empresa") or {}).get("Inscricao"))
        empresa = mapa.get(cnpj, cnpj or "N/D")
        fornecedor = (tit.get("ClienteFornecedor") or {}).get("Nome", "") or ""
        realizado = "liquidado" in s_low or "conciliado" in s_low

        bruto = float(p.get("ValorBruto") or 0)
        rateio = p.get("Rateio") or [{}]
        soma = sum(abs(float(r.get("Valor") or 0)) for r in rateio)

        for r in rateio:
            peso = abs(float(r.get("Valor") or 0)) / soma if soma else 1 / len(rateio)
            linhas.append({
                "ParcelaId": p.get("ParcelaId"),
                "Número": p.get("Numero") or tit.get("NumeroDoTitulo", ""),
                "Tipo": p.get("Tipo"),
                "Empresa": empresa,
                "Cliente / Fornecedor": fornecedor,
                "Plano de Contas": r.get("PlanoDeContas") or "Outros",
                "Valor": bruto * peso,
                "Status": status,
                "Status_Clean": "REALIZADO" if realizado else "PENDENTE",
                "Vencimento_real": p.get("Vencimento"),
                "Liquidacao_raw": p.get("Liquidacao"),
            })

    df = pd.DataFrame(linhas)
    if df.empty:
        return df

    df["Vencimento_real"] = pd.to_datetime(df["Vencimento_real"], errors="coerce")
    df["Liquidacao_dt"] = pd.to_datetime(df["Liquidacao_raw"], errors="coerce")
    df = df.drop(columns=["Liquidacao_raw"])

    # Data de caixa: liquidação se já pago, senão vencimento.
    # Mantém o nome Vencimento_dt para o restante do app funcionar sem alterações.
    df["Vencimento_dt"] = df["Liquidacao_dt"].where(
        (df["Status_Clean"] == "REALIZADO") & df["Liquidacao_dt"].notna(),
        df["Vencimento_real"],
    )
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df


def buscar_parcelas_f360(jwt, d_ini, d_fim, mapa_cnpj, tipo="Despesa",
                         incluir_liquidacao=True, progresso=None):
    """
    Retorna DataFrame de parcelas entre d_ini e d_fim (objetos date).
    Busca por Vencimento e, opcionalmente, por Liquidação (para pegar parcelas
    que venceram em outro mês mas foram pagas dentro do período).
    """
    cnpjs = list(mapa_cnpj.keys())
    tipos_data = ["Vencimento"] + (["Liquidação"] if incluir_liquidacao else [])
    janelas = list(_janelas(d_ini, d_fim))

    unicas, passo, total = {}, 0, len(janelas) * len(tipos_data)
    for td in tipos_data:
        for ini, fim in janelas:
            for p in _listar(jwt, tipo, ini, fim, td, cnpjs):
                unicas[p.get("ParcelaId")] = p  # dedupe entre as duas buscas
            passo += 1
            if progresso:
                progresso(passo / total)

    return _normaliza(list(unicas.values()), mapa_cnpj)