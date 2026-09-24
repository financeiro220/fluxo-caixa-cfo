"""
f360_api.py - Módulo F360 modular para busca de Parcelas de Despesas e Fluxo de Receitas.
"""
import requests
import pandas as pd
import re
from datetime import datetime, date, timedelta

BASE = "https://financas.f360.com.br"
JANELA_DIAS = 30

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

def _so_digitos(s):
    return re.sub(r"\D", "", str(s or ""))

def _fmt_cnpj(c):
    d = _so_digitos(c)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}" if len(d) == 14 else str(c)

def _listar(jwt, tipo, ini, fim, tipo_datas, cnpjs):
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
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
            
        corpo = r.json()
        if isinstance(corpo, dict) and corpo.get("Ok") is False:
            raise RuntimeError(f"F360 retornou erro: {str(corpo)[:300]}")
            
        res = corpo.get("Result") or {}
        saida.extend(res.get("Parcelas", []))
        total = res.get("QuantidadeDePaginas", 1) or 1
        pagina += 1
    return saida

def _da_rede(p, digitos):
    insc = ((p.get("DadosDoTitulo") or {}).get("Empresa") or {}).get("Inscricao")
    return _so_digitos(insc) in digitos

def _normaliza(parcelas, mapa_cnpj, tipo_mov_forçado="DESPESA"):
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
        
        # Identificação de Receita vs Despesa
        tipo_item = str(p.get("Tipo") or tit.get("Tipo") or "").lower()
        if "receita" in tipo_item or "receber" in tipo_item:
            tipo_mov = "RECEITA"
        elif "despesa" in tipo_item or "pagar" in tipo_item:
            tipo_mov = "DESPESA"
        else:
            tipo_mov = tipo_mov_forçado

        rateio = p.get("Rateio") or [{}]
        soma = sum(abs(float(r.get("Valor") or 0)) for r in rateio)

        for r in rateio:
            peso = abs(float(r.get("Valor") or 0)) / soma if soma else 1 / len(rateio)
            linhas.append({
                "ParcelaId": p.get("ParcelaId"),
                "Número": p.get("Numero") or tit.get("NumeroDoTitulo", ""),
                "Tipo_Movimento": tipo_mov,
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

    df["Vencimento_dt"] = df["Liquidacao_dt"].where(
        (df["Status_Clean"] == "REALIZADO") & df["Liquidacao_dt"].notna(),
        df["Vencimento_real"],
    )
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df

def buscar_parcelas_f360(jwt, d_ini, d_fim, mapa_cnpj, tipo="Despesa",
                         incluir_liquidacao=True, progresso=None, log=None):
    """Busca despesas ou receitas na API."""
    log = log if log is not None else []
    digitos = {_so_digitos(c) for c in mapa_cnpj}
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    tipos_data = ["Vencimento"] + (["Liquidação"] if incluir_liquidacao else [])
    janelas = list(_janelas(d_ini, d_fim))

    unicas, passo, total = {}, 0, len(janelas) * len(tipos_data)
    for td in tipos_data:
        for ini, fim in janelas:
            rotulo = f"{tipo} - {td} {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
            try:
                itens = _listar(jwt, tipo, ini, fim, td, cnpjs)
                log.append(f"{rotulo}: {len(itens)} itens encontrados")
                if not itens:
                    todos = _listar(jwt, tipo, ini, fim, td, [])
                    itens = [p for p in todos if _da_rede(p, digitos)]
                    log.append(f"   sem filtro de empresas: {len(todos)} itens, {len(itens)} filtrados")
            except Exception as e:
                log.append(f"{rotulo}: ERRO -> {e}")
                if td == "Vencimento":
                    raise
                itens = []
            for p in itens:
                unicas[p.get("ParcelaId")] = p
            passo += 1
            if progresso:
                progresso(passo / total)

    tipo_mov_forçado = "RECEITA" if tipo == "Receita" else "DESPESA"
    return _normaliza(list(unicas.values()), mapa_cnpj, tipo_mov_forçado=tipo_mov_forçado)