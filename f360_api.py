"""
f360_api.py - Integração Total com a API Pública F360.
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
            if isinstance(res, dict): return res.get("Token") or res.get("Result") or res.get("token")
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
    if v is None: return 0.0
    if isinstance(v, str):
        s = re.sub(r"[^\d,.\-]", "", v)
        if not s: return 0.0
        if "," in s: s = s.replace(".", "").replace(",", ".")
        try: return float(s)
        except ValueError: return 0.0
    try:
        x = float(v)
        return 0.0 if pd.isna(x) else x
    except (TypeError, ValueError): return 0.0

def _data(v):
    if v is None or pd.isna(v): return pd.NaT
    if isinstance(v, str):
        s = v.strip()
        if not s: return pd.NaT
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            d, m_m, y = m.groups()
            return pd.to_datetime(f"{y}-{m_m}-{d}", errors="coerce")
        if re.match(r"^\d{4}-\d{2}-\d{2}", s): return pd.to_datetime(s, errors="coerce")
        return pd.to_datetime(s, dayfirst=True, errors="coerce")
    return pd.to_datetime(v, errors="coerce")

def _mapear_conta_para_loja(conta_str):
    c = str(conta_str or "").strip().upper()
    if "17" in c or "PANTANAL" in c: return "17 Pantanal Itaú"
    elif "51" in c or "ESTAÇÃO" in c or "ESTACAO" in c: return "51 Estação Itaú"
    elif "61" in c or "GOIABEIRAS" in c: return "61 Itaú Goiabeiras"
    elif "52" in c or "RT" in c: return "52 RT"
    elif "36" in c or "MJL" in c: return "36 MJL"
    return str(conta_str) or "17 Pantanal Itaú"

# ==========================================
# PARCELAS DE TÍTULOS
# ==========================================
def _listar_titulos(jwt, tipo, ini, fim, tipo_datas, cnpjs):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/ParcelasDeTituloPublicAPI/ListarParcelasDeTitulos"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {
            "pagina": pagina, 
            "tipo": tipo, 
            "inicio": ini.strftime("%Y-%m-%d"), 
            "fim": fim.strftime("%Y-%m-%d"), 
            "tipoDatas": tipo_datas, 
            "status": "Todos"
        }
        if cnpjs: params["empresas"] = ",".join(cnpjs)
        
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200:
            break
        corpo = r.json()
        if isinstance(corpo, dict) and corpo.get("Ok") is False:
            break
            
        res = corpo.get("Result") or {}
        saida.extend(res.get("Parcelas", []))
        total = res.get("QuantidadeDePaginas", 1) or 1
        pagina += 1
    return saida

def _da_rede(p, digitos_cnpj):
    insc = ((p.get("DadosDoTitulo") or {}).get("Empresa") or {}).get("Inscricao")
    return _so_digitos(insc) in digitos_cnpj

def _normaliza_titulos(parcelas, mapa_cnpj, tipo_padrao="DESPESA"):
    linhas = []
    for p in parcelas:
        status = str(p.get("Status", ""))
        s_low = status.lower()
        if p.get("Cancelada") or "cancelad" in s_low or "baixad" in s_low: continue
        
        tit = p.get("DadosDoTitulo") or {}
        fornecedor = (tit.get("ClienteFornecedor") or {}).get("Nome", "") or ""
        realizado = "liquidado" in s_low or "conciliado" in s_low or pd.notna(p.get("Liquidacao"))
        bruto = float(p.get("ValorBruto") or 0)
        conta_loja = _mapear_conta_para_loja(p.get("Conta"))
        
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
                "Empresa": conta_loja, "Conta": str(p.get("Conta") or ""), "Cliente / Fornecedor": fornecedor,
                "Plano de Contas": r.get("PlanoDeContas") or "Outros", "Valor": bruto * peso,
                "Valor_Bruto": bruto * peso, "Status": status, "Status_Clean": "REALIZADO" if realizado else "PENDENTE",
                "Vencimento_real": p.get("Vencimento"), "Liquidacao_raw": p.get("Liquidacao"),
            })
    df = pd.DataFrame(linhas)
    if not df.empty:
        df["Vencimento_real"] = df["Vencimento_real"].apply(_data)
        df["Liquidacao_dt"] = df["Liquidacao_raw"].apply(_data)
        df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
        df = df.dropna(subset=["Vencimento_dt"]).copy()
        df["Dia"] = df["Vencimento_dt"].dt.day
    return df

# ==========================================
# PARCELAS DE CARTÕES
# ==========================================
_ALIAS = {"empresa": ["empresa", "cnpj"], "adquirente": ["adquirente"], "bandeira": ["bandeira"], "venda": ["dtvenda"], "vencimento": ["vencimento"], "bruto": ["vbruto", "valorbruto"], "liquido": ["vliquido", "valorliquido"], "conta": ["conta"], "liquidacao": ["liquidacao"], "id": ["id"], "modalidade": ["modalidade"]}
def _k(s): return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())
def _pega(reg, chave):
    for nome, v in reg.items():
        if _k(nome) in _ALIAS[chave] and pd.notna(v) and v != "": return v.get("Nome") if isinstance(v, dict) else v
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
        if str(reg.get("Cancelada")).lower() == "true": continue
        conta_loja = _mapear_conta_para_loja(_pega(reg, "conta"))
        adq = str(_pega(reg, "adquirente") or "Cartão").strip()
        band = str(_pega(reg, "bandeira") or "").strip()
        modal = str(_pega(reg, "modalidade") or "").strip()
        bruto = _num(_pega(reg, "bruto"))
        v_liq = _pega(reg, "liquido")
        linhas.append({
            "ParcelaId": str(_pega(reg, "id") or f"CARTAO_{i}"), "Número": f"{adq} {band}".strip(), "Tipo_Movimento": "RECEITA",
            "Origem": "Cartão", "Detalhe": adq if (not modal or modal.lower() == adq.lower()) else f"{adq} - {modal}",
            "Empresa": conta_loja, "Cliente / Fornecedor": f"{adq} ({band})" if band and band.lower() != adq.lower() else adq,
            "Plano de Contas": f"Receita de Vendas ({adq})", "Valor": _num(v_liq) if v_liq is not None else bruto, "Valor_Bruto": bruto,
            "Vencimento_real": _data(_pega(reg, "vencimento")), "Liquidacao_dt": _data(_pega(reg, "liquidacao")),
        })
    df = pd.DataFrame(linhas)
    if not df.empty:
        df["Liquidacao_dt"] = pd.to_datetime(df["Liquidacao_dt"], errors="coerce")
        df["Status_Clean"] = df["Liquidacao_dt"].notna().map({True: "REALIZADO", False: "PENDENTE"})
        df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), pd.to_datetime(df["Vencimento_real"], errors="coerce"))
        df = df.dropna(subset=["Vencimento_dt"]).copy()
        df["Dia"] = df["Vencimento_dt"].dt.day
    return df

def _listar_cartoes_api(jwt, tipo, ini, fim, tipo_datas, cnpjs):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/{CARTOES_ENDPOINT}"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {"pagina": pagina, "tipo": tipo, "inicio": ini.strftime("%Y-%m-%d"), "fim": fim.strftime("%Y-%m-%d"), "tipoDatas": tipo_datas, "status": "Todos"}
        if cnpjs: params["empresas"] = ",".join(cnpjs)
        
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200: break
        corpo = r.json()
        if isinstance(corpo, dict) and corpo.get("Ok") is False: break
        
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
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    registros, vistos = [], set()
    for td in ("Vencimento", "Liquidação"):
        for ini, fim in _janelas(d_ini - timedelta(days=30), d_fim):
            itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, cnpjs)
            # FALLBACK DE SEGURANÇA
            if not itens and cnpjs:
                itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, [])
                
            for it in itens:
                chave = str(it.get("ParcelaId") or json.dumps(it, sort_keys=True, default=str))
                if td == "Vencimento" or chave not in vistos:
                    registros.append(it)
                    vistos.add(chave)
    return _normaliza_cartoes(registros, mapa_cnpj)

def buscar_parcelas_f360(jwt, d_ini, d_fim, mapa_cnpj, tipo="Despesa", incluir_liquidacao=True, log=None):
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    digitos_cnpj = {_so_digitos(c) for c in mapa_cnpj}
    unicas = {}
    
    for td in (["Vencimento", "Liquidação"] if incluir_liquidacao else ["Vencimento"]):
        for ini, fim in _janelas(d_ini, d_fim):
            itens = _listar_titulos(jwt, tipo, ini, fim, td, cnpjs)
            # FALLBACK DE SEGURANÇA
            if not itens:
                todos = _listar_titulos(jwt, tipo, ini, fim, td, [])
                itens = [p for p in todos if _da_rede(p, digitos_cnpj)]
            for p in itens: unicas[p.get("ParcelaId")] = p
            
    df_titulos = _normaliza_titulos(list(unicas.values()), mapa_cnpj, "RECEITA" if tipo == "Receita" else "DESPESA")
    
    if tipo == "Receita":
        df_cartoes = buscar_cartoes_f360(jwt, d_ini, d_fim, mapa_cnpj, log=log)
        partes = [d for d in (df_titulos, df_cartoes) if not d.empty]
        return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()
    return df_titulos

# ==========================================
# EXCEL OFICIAL F360
# ==========================================
def processar_fluxo_de_caixa_oficial(arquivo):
    df_raw = pd.read_excel(arquivo, header=1)
    saldo_inicial = _num(df_raw.iloc[0]['Saldo']) if not df_raw.empty and "Saldo Inicial" in str(df_raw.iloc[0, 0]) else 0.0
    
    df = df_raw.iloc[1:].copy()
    df['Data'] = pd.to_datetime(df['Data'], errors='coerce')
    df = df.dropna(subset=['Data']).copy()
    
    vistos_total, novas_cols = 0, []
    for c in df.columns:
        c_str = str(c).strip()
        if "Cartões" in c_str: novas_cols.append("Cartoes")
        elif "Boleto" in c_str: novas_cols.append("Boleto")
        elif "Orçamentos (entrada)" in c_str: novas_cols.append("Orcamento_Entrada")
        elif "Outros Recebimentos" in c_str: novas_cols.append("Outros_Recebimentos")
        elif "Orçamentos (saída)" in c_str: novas_cols.append("Orcamento_Saida")
        elif "Outros Pagamentos" in c_str: novas_cols.append("Outros_Pagamentos")
        elif "Saldo" in c_str: novas_cols.append("Saldo")
        elif "Total" in c_str:
            vistos_total += 1
            novas_cols.append("Total_Entradas" if vistos_total == 1 else "Total_Saidas")
        else: novas_cols.append(c_str)
    df.columns = novas_cols
    
    for c in ["Cartoes", "Boleto", "Orcamento_Entrada", "Outros_Recebimentos", "Total_Entradas", "Orcamento_Saida", "Outros_Pagamentos", "Total_Saidas", "Saldo"]:
        if c in df.columns: df[c] = df[c].apply(_num)
            
    df['Dia'] = df['Data'].dt.day
    contas = []
    try:
        df_filtros = pd.read_excel(arquivo, sheet_name="Filtros", header=None, dtype=object)
        for _, row in df_filtros.iterrows():
            vals = [str(v) for v in row.dropna()]
            if vals and "conta" in vals[0].lower() and len(vals) > 1: contas = [c.strip() for c in vals[1].split(",") if c.strip()]
    except Exception: pass
    return df, saldo_inicial, contas