"""
f360_api.py - Integração com a API pública do F360.
Inclui leitura exata do Rateio (sem distorção de descontos negativos).
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta

import pandas as pd
import requests
import streamlit as st  

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
            if isinstance(res, dict):
                return res.get("Token") or res.get("Result") or res.get("token")
            return res
        else:
            st.error(f"🚨 Falha de Autenticação no F360. HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        st.error(f"🚨 Erro ao tentar conectar no F360: {e}")
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
    try: return float(v) if not pd.isna(float(v)) else 0.0
    except (TypeError, ValueError): return 0.0

def _data(v):
    if v is None or (not isinstance(v, str) and pd.isna(v)): return pd.NaT
    if isinstance(v, str):
        s = v.strip()
        if not s: return pd.NaT
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            d, m_m, y = m.groups()
            return pd.to_datetime(f"{y}-{m_m}-{d}", errors="coerce")
        return pd.to_datetime(s, dayfirst=True, errors="coerce")
    ts = pd.to_datetime(v, errors="coerce")
    if pd.notna(ts) and getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_localize(None)
    return ts

EMPRESA_CONTA_PADRAO = {
    "4- PANTANAL": "17 Pantanal Itaú",
    "5- ESTAÇÃO": "51 Estação Itaú",
    "8 - GOIABEIRAS": "61 Itaú Goiabeiras",
}

def _mapear_conta_para_loja(conta_str, empresa_nome=None):
    c = str(conta_str or "").strip().upper()
    if "17" in c or "PANTANAL" in c: return "17 Pantanal Itaú"
    if "51" in c or "ESTAÇÃO" in c or "ESTACAO" in c: return "51 Estação Itaú"
    if "61" in c or "GOIABEIRAS" in c: return "61 Itaú Goiabeiras"
    if "52" in c or "RT" in c: return "52 RT"
    if "36" in c or "MJL" in c: return "36 MJL"
    if conta_str: return conta_str
    if empresa_nome and empresa_nome in EMPRESA_CONTA_PADRAO:
        return EMPRESA_CONTA_PADRAO[empresa_nome]
    return "N/D (sem conta)"

# ---------------------------------------------------------------------------
# PARCELAS DE TÍTULOS (API)
# ---------------------------------------------------------------------------
def _listar_titulos(jwt, tipo, ini, fim, tipo_datas, cnpjs):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/ParcelasDeTituloPublicAPI/ListarParcelasDeTitulos"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {
            "pagina": pagina, "tipo": tipo, "inicio": ini.isoformat(), 
            "fim": fim.isoformat(), "tipoDatas": tipo_datas, "status": "Todos"
        }
        if cnpjs: params["empresas"] = ",".join(cnpjs)
        
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

def _normaliza_titulos(parcelas, mapa_cnpj, tipo_padrao="DESPESA"):
    mapa = {_so_digitos(k): v for k, v in mapa_cnpj.items()}
    linhas = []
    
    for p in parcelas:
        status = str(p.get("Status", ""))
        s_low = status.lower()
        
        if p.get("Cancelada") or "cancelad" in s_low:
            continue

        tit = p.get("DadosDoTitulo") or {}
        fornecedor = (tit.get("ClienteFornecedor") or {}).get("Nome", "") or ""
        
        status_txt = unicodedata.normalize("NFKD", status.strip().lower()).encode("ascii", "ignore").decode()
        status_compacto = re.sub(r"[^a-z0-9]", "", status_txt)

        status_pendente = (
            status_compacto in {
                "agendado", "aberto", "abertoavencer", "abertovencidos", "aprovado",
                "pendente", "pendentesdeaprovacao", "renegociado", "naovinculadocomdda",
                "liquidadopendente", "naoliquidado",
            }
            or status_compacto.startswith("aberto")
            or status_compacto.startswith("agendado")
            or status_compacto.startswith("pendente")
            or status_compacto.startswith("liquidadopendente")
        )

        status_realizado = status_compacto in {
            "liquidado", "liquidadoall", "liquidadoconciliado", "conciliado", "baixado"
        }

        liquidacao_dt_raw = _data(p.get("Liquidacao"))
        hoje = pd.Timestamp.today().normalize()

        if status_pendente:
            realizado = False
        elif status_realizado:
            realizado = bool(pd.notna(liquidacao_dt_raw) and liquidacao_dt_raw.normalize() <= hoje)
        else:
            realizado = bool(not status.strip() and pd.notna(liquidacao_dt_raw) and liquidacao_dt_raw.normalize() <= hoje)
            
        conta_raw = str(p.get("Conta") or "")
        cnpj = _so_digitos((tit.get("Empresa") or {}).get("Inscricao"))
        empresa_nome = mapa.get(cnpj, "")
        conta_loja = _mapear_conta_para_loja(conta_raw, empresa_nome)

        tipo_item = str(p.get("Tipo") or tit.get("Tipo") or "").lower()
        if "receita" in tipo_item or "receber" in tipo_item: tipo_mov = "RECEITA"
        elif "despesa" in tipo_item or "pagar" in tipo_item: tipo_mov = "DESPESA"
        else: tipo_mov = tipo_padrao

        # FIX: Leitura exata do Rateio para não distorcer descontos
        rateio = p.get("Rateio")
        if rateio and isinstance(rateio, list) and len(rateio) > 0:
            for r in rateio:
                valor_linha = float(r.get("Valor") or 0)
                linhas.append({
                    "ParcelaId": p.get("ParcelaId"),
                    "Número": p.get("Numero") or tit.get("NumeroDoTitulo", ""),
                    "Tipo_Movimento": tipo_mov,
                    "Origem": "Título",
                    "Detalhe": p.get("MeioDePagamento") or "Não informado",
                    "Empresa": conta_loja,
                    "Empresa_Loja": empresa_nome,
                    "Conta": conta_raw,
                    "Cliente / Fornecedor": fornecedor,
                    "Plano de Contas": r.get("PlanoDeContas") or "Outros",
                    "Valor": valor_linha,
                    "Valor_Bruto": valor_linha,
                    "Status_F360": status,
                    "Status_Clean": "REALIZADO" if realizado else "PENDENTE",
                    "Vencimento_real": p.get("Vencimento"),
                    "Liquidacao_raw": p.get("Liquidacao"),
                })
        else:
            bruto = float(p.get("ValorBruto") or 0)
            linhas.append({
                "ParcelaId": p.get("ParcelaId"),
                "Número": p.get("Numero") or tit.get("NumeroDoTitulo", ""),
                "Tipo_Movimento": tipo_mov,
                "Origem": "Título",
                "Detalhe": p.get("MeioDePagamento") or "Não informado",
                "Empresa": conta_loja,
                "Empresa_Loja": empresa_nome,
                "Conta": conta_raw,
                "Cliente / Fornecedor": fornecedor,
                "Plano de Contas": "Outros",
                "Valor": bruto,
                "Valor_Bruto": bruto,
                "Status_F360": status,
                "Status_Clean": "REALIZADO" if realizado else "PENDENTE",
                "Vencimento_real": p.get("Vencimento"),
                "Liquidacao_raw": p.get("Liquidacao"),
            })

    df = pd.DataFrame(linhas)
    if df.empty: return df

    df["Vencimento_real"] = df["Vencimento_real"].apply(_data)
    df["Liquidacao_dt"] = df["Liquidacao_raw"].apply(_data)
    df = df.drop(columns=["Liquidacao_raw"])
    df["Vencimento_real"] = pd.to_datetime(df["Vencimento_real"], errors="coerce")
    df["Liquidacao_dt"] = pd.to_datetime(df["Liquidacao_dt"], errors="coerce")

    df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
    
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df

# ---------------------------------------------------------------------------
# PARCELAS DE CARTÕES (API + FILE)
# ---------------------------------------------------------------------------
_ALIAS = {
    "empresa": ["empresa", "nomeempresa", "cnpjempresa", "cnpj"],
    "adquirente": ["adquirente", "nomeadquirente"],
    "bandeira": ["bandeira"],
    "venda": ["dtvenda", "datavenda", "datadavenda"],
    "vencimento": ["vencim", "vencimento", "datavencimento"],
    "bruto": ["vbruto", "valorbruto"],
    "liquido": ["vliquido", "valorliquido"],
    "conta": ["conta", "contaliquidacao", "contadeliquidacao"],
    "liquidacao": ["liquid", "liquidacao", "dataliquidacao"],
    "id": ["id", "parcelaid", "cartaoid"],
    "modalidade": ["modalidade"],
    "status": ["status", "statusdaparcela", "situacao"],
}

def _k(s):
    return re.sub(r"[^a-z]", "", unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower())

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
    mapa = {_so_digitos(k): v for k, v in mapa_cnpj.items()}
    linhas = []
    for i, reg in enumerate(registros):
        reg = _achata(reg)
        if str(reg.get("Cancelada")).lower() == "true" or str(reg.get("Cancelado")).lower() == "true":
            continue

        conta_raw = str(_pega(reg, "conta") or "")
        empresa_raw = _pega(reg, "empresa")
        empresa_nome = mapa.get(_so_digitos(empresa_raw), "")
        conta_loja = _mapear_conta_para_loja(conta_raw, empresa_nome)
        adq = str(_pega(reg, "adquirente") or "Cartão").strip()
        band = str(_pega(reg, "bandeira") or "").strip()
        modal = str(_pega(reg, "modalidade") or "").strip()
        detalhe = adq if (not modal or modal.lower() == adq.lower()) else f"{adq} - {modal}"

        bruto = _num(_pega(reg, "bruto"))
        v_liq = _pega(reg, "liquido")
        liquido = _num(v_liq) if v_liq is not None else bruto
        
        status_raw = str(_pega(reg, "status") or "").strip()
        realizado = "liquidado" in status_raw.lower() or "conciliado" in status_raw.lower() or "baixado" in status_raw.lower()

        linhas.append({
            "ParcelaId": str(_pega(reg, "id") or f"CARTAO_{i}"),
            "Número": f"{adq} {band}".strip(),
            "Tipo_Movimento": "RECEITA",
            "Origem": "Cartão",
            "Detalhe": detalhe,
            "Empresa": conta_loja,
            "Empresa_Loja": empresa_nome,
            "Conta": conta_raw,
            "Cliente / Fornecedor": f"{adq} ({band})" if band and band.lower() != adq.lower() else adq,
            "Plano de Contas": f"Receita de Vendas ({adq})",
            "Valor": liquido,
            "Valor_Bruto": bruto,
            "Data_Venda": _data(_pega(reg, "venda")),
            "Vencimento_real": _data(_pega(reg, "vencimento")),
            "Liquidacao_dt": _data(_pega(reg, "liquidacao")),
            "Status_Clean": "REALIZADO" if realizado else "PENDENTE",
            "Status": "Liquidado" if realizado else "A receber",
            "Status_F360": status_raw,
        })

    df = pd.DataFrame(linhas)
    if df.empty: return df

    for c in ("Data_Venda", "Vencimento_real", "Liquidacao_dt"):
        df[c] = pd.to_datetime(df[c], errors="coerce")

    df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df

def _listar_cartoes_api(jwt, tipo, ini, fim, tipo_datas, cnpjs):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/{CARTOES_ENDPOINT}"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {"pagina": pagina, "tipo": tipo, "inicio": ini.isoformat(), "fim": fim.isoformat(),
                  "tipoDatas": tipo_datas, "status": "Todos"}
        if cnpjs: params["empresas"] = ",".join(cnpjs)
        
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} em Cartões: {r.text[:300]}")
        corpo = r.json()
        if isinstance(corpo, dict) and corpo.get("Ok") is False:
            raise RuntimeError(f"F360 retornou erro: {str(corpo)[:300]}")
            
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
    d_ini_expandido = d_ini - timedelta(days=30)
    registros, vistos = [], set()
    
    for td in ("Vencimento", "Liquidação"):
        for ini, fim in _janelas(d_ini_expandido, d_fim):
            try:
                itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, cnpjs)
                if not itens and cnpjs:
                    itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, [])
            except Exception as e:
                st.error(f"🚨 F360 API ERRO (Cartões): {e}")
                itens = []
            for it in itens:
                chave = str(it.get("ParcelaId") or json.dumps(it, sort_keys=True, default=str))
                if td == "Vencimento":
                    registros.append(it)
                    vistos.add(chave)
                elif chave not in vistos:
                    registros.append(it)

    return _normaliza_cartoes(registros, mapa_cnpj)

def processar_parcelas_cartoes_arquivo(arquivo, mapa_cnpj):
    nome = str(getattr(arquivo, "name", "")).lower()
    if nome.endswith(".csv"): cru = pd.read_csv(arquivo, header=None, dtype=str, sep=None, engine="python")
    else: cru = pd.read_excel(arquivo, header=None, dtype=object)

    cab = None
    for i, linha in cru.iterrows():
        ks = {_k(v) for v in linha.dropna()}
        if "adquirente" in ks and ({"vbruto", "valorbruto"} & ks):
            cab = i
            break
    if cab is None: raise ValueError("Não achei o cabeçalho (Adquirente / V. Bruto) no arquivo de cartões.")

    df = cru.iloc[cab + 1:].copy()
    df.columns = [str(c).strip() for c in cru.iloc[cab].values]
    df = df.dropna(how="all")
    df = df[df.apply(lambda r: _pega(r.to_dict(), "adquirente") is not None, axis=1)]
    return _normaliza_cartoes(df.to_dict("records"), mapa_cnpj)

# ---------------------------------------------------------------------------
# RELATÓRIO OFICIAL "DETALHES FLUXO DE CAIXA.XLSX" (EXCEL NATIVO)
# ---------------------------------------------------------------------------
def _acha_cabecalho(df_raw, tokens):
    for idx, row in df_raw.iterrows():
        vals = [str(v) for v in row.dropna()]
        texto = " | ".join(vals)
        if all(tok in texto for tok in tokens): return idx
    return None

def _ler_aba(caminho_ou_buffer, aba, tokens_cabecalho):
    df_raw = pd.read_excel(caminho_ou_buffer, sheet_name=aba, header=None, dtype=object)
    cab = _acha_cabecalho(df_raw, tokens_cabecalho)
    if cab is None: return pd.DataFrame()
    df = df_raw.iloc[cab + 1:].copy()
    df.columns = [str(c).strip() for c in df_raw.iloc[cab].values]
    df = df.dropna(how="all")
    return df.reset_index(drop=True)

def processar_detalhes_fluxo_caixa(arquivos, mapa_cnpj):
    if not isinstance(arquivos, (list, tuple)): arquivos = [arquivos]
    linhas, brutos = [], {"titulos": [], "cartoes": [], "transferencias": [], "ajustes": []}

    for arq in arquivos:
        t = _ler_aba(arq, "Parcelas de Títulos", ["Conta", "Pessoa", "Valor Bruto"])
        for _, r in t.iterrows():
            pessoa = str(r.get("Pessoa") or "").strip()
            plano = str(r.get("Plano de Contas") or "").upper().strip()
            conta_raw = str(r.get("Conta") or "").strip()
            conta_loja = _mapear_conta_para_loja(conta_raw)
            is_mutuo = any(k in plano for k in ['EMPRÉSTIMO MÚTUO', 'EMPRESTIMO MUTUO', 'MÚTUO', 'MUTUO', 'TRANSFERÊNCIA INTERCOMPANY'])
            linhas.append({
                "Origem": "Título", "Detalhe": pessoa or "Não informado", "Empresa": conta_loja,
                "Conta": conta_raw, "Cliente / Fornecedor": pessoa, "Número": r.get("Número"),
                "Plano de Contas": r.get("Plano de Contas") or "Outros", "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Líquido")), "Vencimento_real": _data(r.get("Vencimento")),
                "Liquidacao_dt": _data(r.get("Liquidação/Agendamento")), "Categoria_CFO": ("7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO" if is_mutuo else "0. RECEITAS DE VENDAS"),
            })
        brutos["titulos"].append(t)

        c = _ler_aba(arq, "Parcelas de Cartões", ["Conta", "Adquirente", "Valor Bruto"])
        for _, r in c.iterrows():
            adq = str(r.get("Adquirente") or "").strip()
            band = str(r.get("Bandeira") or "").strip()
            conta_raw = str(r.get("Conta") or "").strip()
            conta_loja = _mapear_conta_para_loja(conta_raw)
            linhas.append({
                "Origem": "Cartão", "Detalhe": f"{adq} - {band}" if band else adq, "Empresa": conta_loja,
                "Conta": conta_raw, "Cliente / Fornecedor": f"{adq} ({band})" if band else adq,
                "Número": r.get("Parcela"), "Plano de Contas": f"Receita de Vendas ({adq})",
                "Valor_Bruto": _num(r.get("Valor Bruto")), "Valor": _num(r.get("Valor Líquido")),
                "Vencimento_real": _data(r.get("Vencimento")), "Liquidacao_dt": _data(r.get("Liquidação/Agendamento")),
                "Categoria_CFO": "0. RECEITAS DE VENDAS",
            })
        brutos["cartoes"].append(c)

    df = pd.DataFrame(linhas)
    if not df.empty:
        df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
        df = df.dropna(subset=["Vencimento_dt"]).copy()
        df["Dia"] = df["Vencimento_dt"].dt.day
        df["Status_Clean"] = "REALIZADO"
        df["Status"] = "Lançado"
        df["Tipo_Movimento"] = "RECEITA"
        df["ParcelaId"] = df["Origem"] + "_" + df.index.astype(str)

    for k in brutos: brutos[k] = pd.concat([b for b in brutos[k] if not b.empty], ignore_index=True) if any(not b.empty for b in brutos[k]) else pd.DataFrame()
    return df, brutos

# ---------------------------------------------------------------------------
# FUNÇÃO PRINCIPAL DA API
# ---------------------------------------------------------------------------
def buscar_parcelas_f360(jwt, d_ini, d_fim, mapa_cnpj, tipo="Despesa", incluir_liquidacao=True, progresso=None, log=None):
    if not jwt:
        st.error("🚨 Ocorreu um erro crítico de Autenticação na API do F360. Verifique se o seu Token expirou.")
        st.stop()
        
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    tipos_data = ["Vencimento"] + (["Liquidação"] if incluir_liquidacao else [])
    janelas = list(_janelas(d_ini, d_fim))

    unicas, passo, total = {}, 0, len(janelas) * len(tipos_data)
    
    for td in tipos_data:
        for ini, fim in janelas:
            try:
                itens = _listar_titulos(jwt, tipo, ini, fim, td, cnpjs)
                if not itens:
                    todos = _listar_titulos(jwt, tipo, ini, fim, td, [])
                    itens = [p for p in todos if _da_rede(p, {_so_digitos(c) for c in mapa_cnpj})]
            except Exception as e:
                st.error(f"🚨 F360 API ERRO (Títulos): Falha ao buscar de {ini.strftime('%d/%m')} a {fim.strftime('%d/%m')}.\nMotivo: {e}")
                st.stop()
                
            for p in itens:
                parcela_id = p.get("ParcelaId")
                if parcela_id:
                    chave = ("id", str(parcela_id))
                else:
                    tit = p.get("DadosDoTitulo") or {}
                    empresa = _so_digitos((tit.get("Empresa") or {}).get("Inscricao"))
                    chave = ("sem_id", empresa, str(p.get("Numero") or tit.get("NumeroDoTitulo") or ""), str(p.get("Vencimento") or ""), str(p.get("ValorBruto") or ""), str(p.get("Liquidacao") or ""))
                unicas[chave] = p
            passo += 1
            if progresso: progresso(passo / total)

    df_titulos = _normaliza_titulos(list(unicas.values()), mapa_cnpj, tipo_padrao="RECEITA" if tipo == "Receita" else "DESPESA")

    if tipo == "Receita":
        df_cartoes = buscar_cartoes_f360(jwt, d_ini, d_fim, mapa_cnpj)
        partes = [d for d in (df_titulos, df_cartoes) if d is not None and not d.empty]
        return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()

    return df_titulos

# ---------------------------------------------------------------------------
# RELATÓRIO OFICIAL "FLUXO DE CAIXA.XLSX" E "CONTAS BANCÁRIAS"
# ---------------------------------------------------------------------------
def _ler_contas_do_filtro(arquivo):
    try: df = pd.read_excel(arquivo, sheet_name="Filtros", header=None, dtype=object)
    except Exception: return []
    for _, row in df.iterrows():
        vals = [str(v) for v in row.dropna()]
        if vals and "conta" in vals[0].lower() and len(vals) > 1: return [c.strip() for c in vals[1].split(",") if c.strip()]
    return []

def processar_fluxo_de_caixa_oficial(arquivo):
    df_raw = pd.read_excel(arquivo, sheet_name="Fluxo de Caixa", header=None, dtype=object)
    cab = _acha_cabecalho(df_raw, ["Data", "Saldo"])
    if cab is None: raise ValueError("Não achei o cabeçalho (Data / Saldo) na aba 'Fluxo de Caixa'.")

    colunas = [str(c).strip() for c in df_raw.iloc[cab].values]
    df = df_raw.iloc[cab + 1:].copy()
    df.columns = colunas

    saldo_inicial = 0.0
    linha_inicial = df[df.iloc[:, 0].astype(str).str.contains("Saldo Inicial", na=False)]
    if not linha_inicial.empty: saldo_inicial = _num(linha_inicial.iloc[0].get("Saldo"))

    df = df[pd.to_datetime(df.iloc[:, 0], errors="coerce").notna()].copy()
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")

    ren = {"Cartões": "Cartoes", "Boleto": "Boleto", "Orçamentos (entrada)": "Orcamento_Entrada", "Outros Recebimentos": "Outros_Recebimentos", "Total": "Total_Entradas", "Orçamentos (saída)": "Orcamento_Saida", "Outros Pagamentos": "Outros_Pagamentos", "Saldo": "Saldo"}
    cols_novas, vistos_total = [], 0
    for c in df.columns:
        c_s = str(c).strip()
        if c_s == "Total" or c_s == "Total ":
            vistos_total += 1
            cols_novas.append("Total_Entradas" if vistos_total == 1 else "Total_Saidas")
        else: cols_novas.append(ren.get(c_s, c_s))
    df.columns = cols_novas

    for c in ["Cartoes", "Boleto", "Orcamento_Entrada", "Outros_Recebimentos", "Total_Entradas", "Orcamento_Saida", "Outros_Pagamentos", "Total_Saidas", "Saldo"]:
        if c in df.columns: df[c] = df[c].apply(_num)

    df["Dia"] = df["Data"].dt.day
    df["Mes"] = df["Data"].dt.month
    df["Ano"] = df["Data"].dt.year
    return df.reset_index(drop=True), saldo_inicial, _ler_contas_do_filtro(arquivo)

def listar_contas_bancarias(jwt):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    r = requests.get(f"{BASE}/ContaBancariaPublicAPI/ListarContasBancarias", headers=headers, timeout=30)
    if r.status_code != 200: raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    corpo = r.json()
    if isinstance(corpo, dict) and corpo.get("Ok") is False: raise RuntimeError(f"F360 retornou erro: {str(corpo)[:300]}")
    return corpo.get("Result") or []

def mapear_ids_contas(jwt, nomes_conhecidos=None):
    contas = listar_contas_bancarias(jwt)
    nomes_conhecidos = nomes_conhecidos or {}
    saida = {}
    for c in contas:
        nome = str(c.get("Nome") or "").strip().upper()
        rotulo = next((v for k, v in nomes_conhecidos.items() if k.upper() in nome), str(c.get("Nome")))
        saida[c.get("Id")] = rotulo
    return saida

def processar_tabela_fluxo_dom(caminho_csv):
    import csv as _csv
    with open(caminho_csv, encoding="utf-8-sig") as f: linhas = list(_csv.reader(f, delimiter=";"))
    saldo_inicial, dias = 0.0, []

    for linha in linhas:
        linha = [c.strip() for c in linha]
        if not linha or not linha[0]: continue
        rotulo = linha[0]

        if rotulo.startswith("Saldo Inicial"):
            saldo_inicial = _num(linha[-1])
            continue
        if rotulo in ("Saldo Final",) or not re.match(r"^\d{2}/\d{2}/\d{4}$", rotulo): continue 

        vals = (linha + [""] * 10)[:10]
        d, m_, y = vals[0].split("/")
        dias.append({
            "Data": f"{y}-{m_}-{d}", "Cartoes": _num(vals[1]), "Boleto": _num(vals[2]),
            "Orcamento_Entrada": _num(vals[3]), "Outros_Recebimentos": _num(vals[4]),
            "Total_Entradas": _num(vals[5]), "Orcamento_Saida": _num(vals[6]), 
            "Outros_Pagamentos": _num(vals[7]), "Total_Saidas": _num(vals[8]), "Saldo": _num(vals[9])
        })

    df = pd.DataFrame(dias)
    if not df.empty:
        df["Data"] = pd.to_datetime(df["Data"])
        df["Dia"] = df["Data"].dt.day
        df["Mes"] = df["Data"].dt.month
        df["Ano"] = df["Data"].dt.year

    return df, saldo_inicial