"""
f360_api.py - Integração Total com a API Pública F360.
- Correção de parser de datas ISO8601 (Evita inversão de dias e meses).
- Busca retroativa profunda (60 dias) para Cartões.
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta

import pandas as pd
import requests

BASE = "https://financas.f360.com.br"
JANELA_DIAS = 30

CARTOES_ENDPOINT = "ParcelasDeCartoesPublicAPI/ListarParcelasDeCartoes"
SALDOS_ENDPOINT = "ExtratoBancarioPublicAPI/ListarSaldosDasContas"

IDS_CONTAS_BORELLI = {
    "17": "17 Pantanal Itaú",
    "51": "51 Estação Itaú",
    "61": "61 Itaú Goiabeiras",
    "52": "52 RT",
    "36": "36 MJL"
}

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

def _num(v):
    if v is None:
        return 0.0
    if isinstance(v, str):
        s = re.sub(r"[^\d,.\-]", "", v)
        if not s:
            return 0.0
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        try:
            return float(s)
        except ValueError:
            return 0.0
    try:
        x = float(v)
        return 0.0 if pd.isna(x) else x
    except (TypeError, ValueError):
        return 0.0

def _data(v):
    if v is None or pd.isna(v): 
        return pd.NaT
    if isinstance(v, str):
        s = v.strip()
        if not s: return pd.NaT
        # Tenta data brasileira clássica
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            d, m_m, y = m.groups()
            return pd.to_datetime(f"{y}-{m_m}-{d}", errors="coerce")
        # Identifica ISO Date (ex: 2026-09-08) sem inverter dias
        if re.match(r"^\d{4}-\d{2}-\d{2}", s):
            return pd.to_datetime(s, errors="coerce")
        return pd.to_datetime(s, dayfirst=True, errors="coerce")
    return pd.to_datetime(v, errors="coerce")

def _mapear_conta_para_loja(conta_str):
    c = str(conta_str or "").strip()
    c_upper = c.upper()
    if "17" in c or "PANTANAL" in c_upper: return "17 Pantanal Itaú"
    elif "51" in c or "ESTAÇÃO" in c_upper or "ESTACAO" in c_upper: return "51 Estação Itaú"
    elif "61" in c or "GOIABEIRAS" in c_upper: return "61 Itaú Goiabeiras"
    elif "52" in c or "RT" in c_upper: return "52 RT"
    elif "36" in c or "MJL" in c_upper: return "36 MJL"
    return c or "17 Pantanal Itaú"

def buscar_saldos_bancarios_f360(jwt, d_ini, d_fim, log=None):
    log = log if log is not None else []
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/{SALDOS_ENDPOINT}"
    params = {"inicio": d_ini.isoformat(), "fim": d_fim.isoformat()}
    try:
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200:
            log.append(f"Aviso API Saldos HTTP {r.status_code}")
            return {}
        corpo = r.json()
        res = corpo.get("Result") if isinstance(corpo, dict) else corpo
        saldos_por_conta = {}
        if isinstance(res, list):
            for item in res:
                conta_nome = _mapear_conta_para_loja(item.get("Conta") or item.get("NomeConta"))
                data_saldo = _data(item.get("Data") or item.get("DataDoSaldo"))
                valor_saldo = _num(item.get("SaldoFinal") or item.get("Saldo"))
                if pd.notna(data_saldo):
                    saldos_por_conta[(conta_nome, data_saldo.day)] = valor_saldo
        return saldos_por_conta
    except Exception:
        return {}

def _listar_titulos(jwt, tipo, ini, fim, tipo_datas, cnpjs):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/ParcelasDeTituloPublicAPI/ListarParcelasDeTitulos"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {"pagina": pagina, "tipo": tipo, "inicio": ini.isoformat(), "fim": fim.isoformat(), "tipoDatas": tipo_datas, "status": "Todos"}
        if cnpjs: params["empresas"] = ",".join(cnpjs)
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code}")
        corpo = r.json()
        if isinstance(corpo, dict) and corpo.get("Ok") is False: raise RuntimeError("Erro F360")
        res = corpo.get("Result") or {}
        saida.extend(res.get("Parcelas", []))
        total = res.get("QuantidadeDePaginas", 1) or 1
        pagina += 1
    return saida

def _normaliza_titulos(parcelas, mapa_cnpj, tipo_padrao="DESPESA"):
    linhas = []
    for p in parcelas:
        status = str(p.get("Status", ""))
        s_low = status.lower()
        if p.get("Cancelada") or "cancelad" in s_low or "baixad" in s_low:
            continue
        tit = p.get("DadosDoTitulo") or {}
        fornecedor = (tit.get("ClienteFornecedor") or {}).get("Nome", "") or ""
        realizado = "liquidado" in s_low or "conciliado" in s_low or pd.notna(p.get("Liquidacao"))
        bruto = float(p.get("ValorBruto") or 0)
        conta_raw = str(p.get("Conta") or "")
        conta_loja = _mapear_conta_para_loja(conta_raw)

        tipo_item = str(p.get("Tipo") or tit.get("Tipo") or "").lower()
        if "receita" in tipo_item or "receber" in tipo_item: tipo_mov = "RECEITA"
        elif "despesa" in tipo_item or "pagar" in tipo_item: tipo_mov = "DESPESA"
        else: tipo_mov = tipo_padrao

        rateio = p.get("Rateio") or [{}]
        soma = sum(abs(float(r.get("Valor") or 0)) for r in rateio)
        for r in rateio:
            peso = abs(float(r.get("Valor") or 0)) / soma if soma else 1 / len(rateio)
            linhas.append({
                "ParcelaId": p.get("ParcelaId"), "Número": p.get("Numero") or tit.get("NumeroDoTitulo", ""),
                "Tipo_Movimento": tipo_mov, "Origem": "Título", "Detalhe": p.get("MeioDePagamento") or "Não informado",
                "Empresa": conta_loja, "Conta": conta_raw, "Cliente / Fornecedor": fornecedor,
                "Plano de Contas": r.get("PlanoDeContas") or "Outros", "Valor": bruto * peso,
                "Valor_Bruto": bruto * peso, "Status": status, "Status_Clean": "REALIZADO" if realizado else "PENDENTE",
                "Vencimento_real": p.get("Vencimento"), "Liquidacao_raw": p.get("Liquidacao"),
            })
    df = pd.DataFrame(linhas)
    if df.empty: return df
    df["Vencimento_real"] = df["Vencimento_real"].apply(_data)
    df["Liquidacao_dt"] = df["Liquidacao_raw"].apply(_data)
    df = df.drop(columns=["Liquidacao_raw"])
    df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df

_ALIAS = {
    "empresa": ["empresa", "nomeempresa", "cnpjempresa", "cnpj"], "adquirente": ["adquirente", "nomeadquirente"],
    "bandeira": ["bandeira"], "venda": ["dtvenda", "datavenda", "datadavenda"], "vencimento": ["vencim", "vencimento", "datavencimento"],
    "bruto": ["vbruto", "valorbruto"], "liquido": ["vliquido", "valorliquido"], "conta": ["conta", "contaliquidacao", "contadeliquidacao"],
    "liquidacao": ["liquid", "liquidacao", "dataliquidacao"], "id": ["id", "parcelaid", "cartaoid"], "modalidade": ["modalidade"],
}

def _k(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())

def _pega(reg, chave):
    for nome, v in reg.items():
        if _k(nome) in _ALIAS[chave]:
            if v is None or (not isinstance(v, (dict, list, str)) and pd.isna(v)) or v == "": continue
            if isinstance(v, dict): return v.get("Inscricao") or v.get("Nome") or ""
            return v
    return None

def _achata(reg, saida=None):
    saida = {} if saida is None else saida
    for k, v in reg.items():
        saida.setdefault(k, v)
        if isinstance(v, dict): _achata(v, saida)
    return saida

def _normaliza_cartoes(registros, mapa_cnpj):
    linhas = []
    for i, reg in enumerate(registros):
        reg = _achata(reg)
        if str(reg.get("Cancelada")).lower() == "true" or str(reg.get("Cancelado")).lower() == "true": continue
        conta_raw = str(_pega(reg, "conta") or "")
        conta_loja = _mapear_conta_para_loja(conta_raw)
        adq = str(_pega(reg, "adquirente") or "Cartão").strip()
        band = str(_pega(reg, "bandeira") or "").strip()
        modal = str(_pega(reg, "modalidade") or "").strip()
        detalhe = adq if (not modal or modal.lower() == adq.lower()) else f"{adq} - {modal}"
        bruto = _num(_pega(reg, "bruto"))
        v_liq = _pega(reg, "liquido")
        liquido = _num(v_liq) if v_liq is not None else bruto

        linhas.append({
            "ParcelaId": str(_pega(reg, "id") or f"CARTAO_{i}"), "Número": f"{adq} {band}".strip(), "Tipo_Movimento": "RECEITA",
            "Origem": "Cartão", "Detalhe": detalhe, "Empresa": conta_loja, "Conta": conta_raw,
            "Cliente / Fornecedor": f"{adq} ({band})" if band and band.lower() != adq.lower() else adq,
            "Plano de Contas": f"Receita de Vendas ({adq})", "Valor": liquido, "Valor_Bruto": bruto,
            "Data_Venda": _data(_pega(reg, "venda")), "Vencimento_real": _data(_pega(reg, "vencimento")),
            "Liquidacao_dt": _data(_pega(reg, "liquidacao")),
        })
    df = pd.DataFrame(linhas)
    if df.empty: return df
    for c in ("Data_Venda", "Vencimento_real", "Liquidacao_dt"): df[c] = pd.to_datetime(df[c], errors="coerce")
    df["Status_Clean"] = df["Liquidacao_dt"].notna().map({True: "REALIZADO", False: "PENDENTE"})
    df["Status"] = df["Status_Clean"].map({"REALIZADO": "Liquidado", "PENDENTE": "A receber"})
    df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df

def _listar_cartoes_api(jwt, tipo, ini, fim, tipo_datas, cnpjs):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/{CARTOES_ENDPOINT}"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {"pagina": pagina, "tipo": tipo, "inicio": ini.isoformat(), "fim": fim.isoformat(), "tipoDatas": tipo_datas, "status": "Todos"}
        if cnpjs: params["empresas"] = ",".join(cnpjs)
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code} em Cartões")
        corpo = r.json()
        if isinstance(corpo, dict) and corpo.get("Ok") is False: raise RuntimeError("Erro F360")
        res = corpo.get("Result") if isinstance(corpo, dict) else corpo
        if isinstance(res, dict):
            itens = res.get("Parcelas") or []
            total = res.get("QuantidadeDePaginas", 1) or 1
        else:
            itens, total = (res or []), 1
        saida.extend(itens)
        pagina += 1
    return saida

def buscar_cartoes_f360(jwt, d_ini, d_fim, mapa_cnpj, log=None):
    log = log if log is not None else []
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    d_ini_expandido = d_ini - timedelta(days=60)
    registros, vistos = [], set()
    
    for td in ["Vencimento"]:
        for ini, fim in _janelas(d_ini_expandido, d_fim):
            try:
                itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, cnpjs)
                if not itens and cnpjs:
                    itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, [])
            except Exception:
                itens = []
            for it in itens:
                chave = str(it.get("ParcelaId") or json.dumps(it, sort_keys=True, default=str))
                if chave not in vistos:
                    registros.append(it)
                    vistos.add(chave)
    return _normaliza_cartoes(registros, mapa_cnpj)

def buscar_parcelas_f360(jwt, d_ini, d_fim, mapa_cnpj, tipo="Despesa", incluir_liquidacao=True, progresso=None, log=None):
    log = log if log is not None else []
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    tipos_data = ["Vencimento"] + (["Liquidação"] if incluir_liquidacao else [])
    janelas = list(_janelas(d_ini, d_fim))

    unicas = {}
    for td in tipos_data:
        for ini, fim in janelas:
            try:
                itens = _listar_titulos(jwt, tipo, ini, fim, td, cnpjs)
                if not itens:
                    todos = _listar_titulos(jwt, tipo, ini, fim, td, [])
                    itens = [p for p in todos if _da_rede(p, {_so_digitos(c) for c in mapa_cnpj})]
            except Exception:
                itens = []
            for p in itens: unicas[p.get("ParcelaId")] = p

    df_titulos = _normaliza_titulos(list(unicas.values()), mapa_cnpj, tipo_padrao="RECEITA" if tipo == "Receita" else "DESPESA")

    if tipo == "Receita":
        try:
            df_cartoes = buscar_cartoes_f360(jwt, d_ini, d_fim, mapa_cnpj, log=log)
        except Exception:
            df_cartoes = pd.DataFrame()
        partes = [d for d in (df_titulos, df_cartoes) if d is not None and not d.empty]
        return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()

    return df_titulos