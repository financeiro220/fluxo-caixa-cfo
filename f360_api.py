"""
f360_api.py - Integração com a API pública do F360.
Solução para vendas de Cartões/iFood de meses anteriores que liquidam no mês atual (ex: Venda em Agosto, Liquidação em Setembro).\n\nCorreção: respeita o Status da parcela para distinguir Liquidado de Agendado.
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
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return pd.NaT
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return pd.NaT
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s)
        if m:
            d, m_m, y = m.groups()
            return pd.to_datetime(f"{y}-{m_m}-{d}", errors="coerce")
        else:
            ts = pd.to_datetime(s, dayfirst=True, errors="coerce")
    else:
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
    """Identifica a conta bancária pelo texto da conta. Um título pendente
    (ainda não pago) costuma vir com Conta vazia -- antes isso caía todo
    em '17 Pantanal Itaú' por padrão, inflando essa conta e zerando as
    outras. Agora, sem conta, usa a conta padrão da EMPRESA do título."""
    c = str(conta_str or "").strip()
    c_upper = c.upper()

    if "17" in c or "PANTANAL" in c_upper:
        return "17 Pantanal Itaú"
    elif "51" in c or "ESTAÇÃO" in c_upper or "ESTACAO" in c_upper:
        return "51 Estação Itaú"
    elif "61" in c or "GOIABEIRAS" in c_upper:
        return "61 Itaú Goiabeiras"
    elif "52" in c or "RT" in c_upper:
        return "52 RT"
    elif "36" in c or "MJL" in c_upper:
        return "36 MJL"
    if c:
        return c
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
            "pagina": pagina,
            "tipo": tipo,
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

def _normaliza_titulos(parcelas, mapa_cnpj, tipo_padrao="DESPESA"):
    mapa = {_so_digitos(k): v for k, v in mapa_cnpj.items()}
    linhas = []
    for p in parcelas:
        status = str(p.get("Status", ""))
        s_low = status.lower()
        if p.get("Cancelada") or "cancelad" in s_low or "baixad" in s_low:
            continue

        tit = p.get("DadosDoTitulo") or {}
        fornecedor = (tit.get("ClienteFornecedor") or {}).get("Nome", "") or ""
        # O F360 possui status distintos para ABERTO, AGENDADO e LIQUIDADO.
        # A existência de uma data em "Liquidacao" NÃO significa, sozinha,
        # que o dinheiro já saiu do caixa: títulos agendados podem trazer uma
        # data futura nesse campo.
        #
        # Para o CFO, a regra é:
        #   - ABERTO/AGENDADO/PENDENTE -> PENDENTE
        #   - LIQUIDADO/CONCILIADO -> REALIZADO
        #   - liquidação futura -> nunca pode ser REALIZADO hoje
        #
        # A API oficial lista "Agendado" separadamente de "Liquidado".
        # IMPORTANTE: não usamos "liquidado" por substring, porque existem
        # status como "LiquidadoPendente" e "Não Liquidado". O status oficial
        # precisa ser interpretado de forma conservadora.
        status_txt = unicodedata.normalize(
            "NFKD", status.strip().lower()
        ).encode("ascii", "ignore").decode()
        status_compacto = re.sub(r"[^a-z0-9]", "", status_txt)

        # Estados que NÃO representam dinheiro efetivamente realizado.
        status_pendente = (
            status_compacto in {
                "agendado",
                "aberto",
                "abertoavencer",
                "abertovencidos",
                "aprovado",
                "pendente",
                "pendentesdeaprovacao",
                "renegociado",
                "naovinculadocomdda",
                "liquidadopendente",
                "naoliquidado",
            }
            or status_compacto.startswith("aberto")
            or status_compacto.startswith("agendado")
            or status_compacto.startswith("pendente")
            or status_compacto.startswith("liquidadopendente")
        )

        # Somente estes estados são tratados como dinheiro efetivamente
        # liquidado/conciliado. "LiquidadoPendente" fica fora.
        status_realizado = status_compacto in {
            "liquidado",
            "liquidadoall",
            "liquidadoconciliado",
            "conciliado",
        }

        liquidacao_dt_raw = _data(p.get("Liquidacao"))
        hoje = pd.Timestamp.today().normalize()

        if status_pendente:
            realizado = False
        elif status_realizado:
            # Mesmo que o F360 envie uma data futura, ela não pode ser
            # considerada caixa realizado antes do dia chegar.
            realizado = bool(
                pd.notna(liquidacao_dt_raw)
                and liquidacao_dt_raw.normalize() <= hoje
            )
        else:
            # Se o F360 não informou status, mantemos a regra conservadora:
            # só considera realizado se houver liquidação não futura.
            realizado = bool(
                not status.strip()
                and pd.notna(liquidacao_dt_raw)
                and liquidacao_dt_raw.normalize() <= hoje
            )
        bruto = float(p.get("ValorBruto") or 0)
        conta_raw = str(p.get("Conta") or "")
        cnpj = _so_digitos((tit.get("Empresa") or {}).get("Inscricao"))
        empresa_nome = mapa.get(cnpj, "")
        conta_loja = _mapear_conta_para_loja(conta_raw, empresa_nome)

        tipo_item = str(p.get("Tipo") or tit.get("Tipo") or "").lower()
        if "receita" in tipo_item or "receber" in tipo_item:
            tipo_mov = "RECEITA"
        elif "despesa" in tipo_item or "pagar" in tipo_item:
            tipo_mov = "DESPESA"
        else:
            tipo_mov = tipo_padrao

        rateio = p.get("Rateio") or [{}]
        soma = sum(abs(float(r.get("Valor") or 0)) for r in rateio)

        for r in rateio:
            peso = abs(float(r.get("Valor") or 0)) / soma if soma else 1 / len(rateio)
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
                "Valor": bruto * peso,
                "Valor_Bruto": bruto * peso,
                "Status": status,
                "Status_F360": status,
                "Status_Clean": "REALIZADO" if realizado else "PENDENTE",
                "Vencimento_real": p.get("Vencimento"),
                "Liquidacao_raw": p.get("Liquidacao"),
            })

    df = pd.DataFrame(linhas)
    if df.empty:
        return df

    df["Vencimento_real"] = df["Vencimento_real"].apply(_data)
    df["Liquidacao_dt"] = df["Liquidacao_raw"].apply(_data)
    df = df.drop(columns=["Liquidacao_raw"])
    df["Vencimento_real"] = pd.to_datetime(df["Vencimento_real"], errors="coerce")
    df["Liquidacao_dt"] = pd.to_datetime(df["Liquidacao_dt"], errors="coerce")

    # DATA USADA PELO FLUXO DE CAIXA:
    # A coluna "Liquidacao" do F360 representa a data em que o valor está
    # previsto/agenda para movimentar o caixa. Portanto, ela deve ser usada
    # para POSICIONAR o título no calendário mesmo quando o status ainda é
    # PENDENTE/AGENDADO.
    #
    # O STATUS é tratado separadamente acima e continua dizendo se o valor já
    # foi realizado ou ainda está em aberto.
    #
    # Assim:
    #   - Agendado + Liquidação 01/10 -> aparece em 01/10 como EM ABERTO
    #   - Agendado + Liquidação 09/10 -> aparece em 09/10 como EM ABERTO
    #   - Liquidado + Liquidação 09/10 -> aparece em 09/10 como LIQUIDADO
    #   - sem Liquidação -> usa o Vencimento.
    df["Vencimento_dt"] = df["Liquidacao_dt"].where(
        df["Liquidacao_dt"].notna(),
        df["Vencimento_real"]
    )
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
    "liquidacao": ["liquid", "liquidacao", "dataliquidacao"], # Adicionado 'liquid' com ponto
    "id": ["id", "parcelaid", "cartaoid"],
    "modalidade": ["modalidade"],
}

def _k(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z]", "", s.lower())

def _pega(reg, chave):
    for nome, v in reg.items():
        if _k(nome) in _ALIAS[chave]:
            if v is None or (not isinstance(v, (dict, list, str)) and pd.isna(v)) or v == "":
                continue
            if isinstance(v, dict):
                v = v.get("Inscricao") or v.get("Nome") or ""
            return v
    return None

def _achata(reg, saida=None):
    saida = {} if saida is None else saida
    for k, v in reg.items():
        saida.setdefault(k, v)
        if isinstance(v, dict):
            _achata(v, saida)
    return saida

def _normaliza_cartoes(registros, mapa_cnpj):
    mapa = {_so_digitos(k): v for k, v in mapa_cnpj.items()}
    linhas = []
    for i, reg in enumerate(registros):
        reg = _achata(reg)
        if str(reg.get("Cancelada")).lower() == "true" or str(reg.get("Cancelado")).lower() == "true":
            continue

        conta_raw = str(_pega(reg, "conta") or "")
        empresa_raw = _pega(reg, "empresa")  # a API de cartões devolve Empresa.Inscricao
        empresa_nome = mapa.get(_so_digitos(empresa_raw), "")
        conta_loja = _mapear_conta_para_loja(conta_raw, empresa_nome)
        adq = str(_pega(reg, "adquirente") or "Cartão").strip()
        band = str(_pega(reg, "bandeira") or "").strip()
        modal = str(_pega(reg, "modalidade") or "").strip()
        detalhe = adq if (not modal or modal.lower() == adq.lower()) else f"{adq} - {modal}"

        bruto = _num(_pega(reg, "bruto"))
        v_liq = _pega(reg, "liquido")
        liquido = _num(v_liq) if v_liq is not None else bruto

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
        "Status_F360": str(_pega(reg, "status") or "").strip(),
        })

    df = pd.DataFrame(linhas)
    if df.empty:
        return df

    for c in ("Data_Venda", "Vencimento_real", "Liquidacao_dt"):
        df[c] = pd.to_datetime(df[c], errors="coerce")

    df["Status_Clean"] = df["Liquidacao_dt"].notna().map({True: "REALIZADO", False: "PENDENTE"})
    df["Status"] = df["Status_Clean"].map({"REALIZADO": "Liquidado", "PENDENTE": "A receber"})
    
    # A DATA DE CAIXA PRINCIPAL PARA O EXTRATO É A LIQUIDAÇÃO
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
        if cnpjs:
            params["empresas"] = ",".join(cnpjs)
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
    """Busca cartões expandindo a busca para 30 dias antes (vendas retroativas de agosto que liquidaram em setembro)."""
    log = log if log is not None else []
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]

    # EXPANDIMOS O INÍCIO DA BUSCA DE VENDAS PARA 30 DIAS ANTES DO MÊS ATUAL
    d_ini_expandido = d_ini - timedelta(days=30)

    registros, vistos = [], set()
    for td in ("Vencimento", "Liquidação"):
        for ini, fim in _janelas(d_ini_expandido, d_fim):
            rotulo = f"Cartões / {td} {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
            try:
                itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, cnpjs)
                if not itens and cnpjs:
                    itens = _listar_cartoes_api(jwt, "Receita", ini, fim, td, [])
                log.append(f"{rotulo}: {len(itens)} parcelas de cartões encontradas")
            except Exception as e:
                log.append(f"{rotulo}: ERRO -> {e}")
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
    if nome.endswith(".csv"):
        cru = pd.read_csv(arquivo, header=None, dtype=str, sep=None, engine="python")
    else:
        cru = pd.read_excel(arquivo, header=None, dtype=object)

    cab = None
    for i, linha in cru.iterrows():
        ks = {_k(v) for v in linha.dropna()}
        if "adquirente" in ks and ({"vbruto", "valorbruto"} & ks):
            cab = i
            break
    if cab is None:
        raise ValueError("Não achei o cabeçalho (Adquirente / V. Bruto) no arquivo de cartões.")

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
        if all(tok in texto for tok in tokens):
            return idx
    return None

def _ler_aba(caminho_ou_buffer, aba, tokens_cabecalho):
    df_raw = pd.read_excel(caminho_ou_buffer, sheet_name=aba, header=None, dtype=object)
    cab = _acha_cabecalho(df_raw, tokens_cabecalho)
    if cab is None:
        return pd.DataFrame()
    df = df_raw.iloc[cab + 1:].copy()
    df.columns = [str(c).strip() for c in df_raw.iloc[cab].values]
    df = df.dropna(how="all")
    return df.reset_index(drop=True)

def processar_detalhes_fluxo_caixa(arquivos, mapa_cnpj):
    if not isinstance(arquivos, (list, tuple)):
        arquivos = [arquivos]

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
                "Origem": "Título", 
                "Detalhe": pessoa or "Não informado",
                "Empresa": conta_loja,
                "Conta": conta_raw,
                "Cliente / Fornecedor": pessoa,
                "Número": r.get("Número"),
                "Plano de Contas": r.get("Plano de Contas") or "Outros",
                "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Líquido")),
                "Vencimento_real": _data(r.get("Vencimento")),
                "Liquidacao_dt": _data(r.get("Liquidação/Agendamento")),
                "Categoria_CFO": ("7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO" if is_mutuo else "0. RECEITAS DE VENDAS"),
            })
        brutos["titulos"].append(t)

        c = _ler_aba(arq, "Parcelas de Cartões", ["Conta", "Adquirente", "Valor Bruto"])
        for _, r in c.iterrows():
            adq = str(r.get("Adquirente") or "").strip()
            band = str(r.get("Bandeira") or "").strip()
            conta_raw = str(r.get("Conta") or "").strip()
            conta_loja = _mapear_conta_para_loja(conta_raw)
            
            linhas.append({
                "Origem": "Cartão", 
                "Detalhe": f"{adq} - {band}" if band else adq,
                "Empresa": conta_loja,
                "Conta": conta_raw,
                "Cliente / Fornecedor": f"{adq} ({band})" if band else adq,
                "Número": r.get("Parcela"),
                "Plano de Contas": f"Receita de Vendas ({adq})",
                "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Líquido")),
                "Vencimento_real": _data(r.get("Vencimento")),
                "Liquidacao_dt": _data(r.get("Liquidação/Agendamento")),
                "Categoria_CFO": "0. RECEITAS DE VENDAS",
            })
        brutos["cartoes"].append(c)

        tr = _ler_aba(arq, "Transferências", ["Conta", "Valor Bruto"])
        for _, r in tr.iterrows():
            conta_raw = str(r.get("Conta") or "").strip()
            conta_loja = _mapear_conta_para_loja(conta_raw)
            linhas.append({
                "Origem": "Transferência", 
                "Detalhe": f"-> {r.get('Conta Relacionada', '')}",
                "Empresa": conta_loja, 
                "Conta": conta_raw,
                "Cliente / Fornecedor": str(r.get("Conta Relacionada") or ""),
                "Número": None,
                "Plano de Contas": "Transferências Intercompany",
                "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Bruto")),
                "Vencimento_real": _data(r.get("Emissão")),
                "Liquidacao_dt": _data(r.get("Emissão")),
                "Categoria_CFO": "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO",
            })
        brutos["transferencias"].append(tr)

    df = pd.DataFrame(linhas)
    if not df.empty:
        df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
        df = df.dropna(subset=["Vencimento_dt"]).copy()
        df["Dia"] = df["Vencimento_dt"].dt.day
        df["Status_Clean"] = "REALIZADO"
        df["Status"] = "Lançado"
        df["Tipo_Movimento"] = "RECEITA"
        df["ParcelaId"] = df["Origem"] + "_" + df.index.astype(str)

    for k in brutos:
        brutos[k] = pd.concat([b for b in brutos[k] if not b.empty], ignore_index=True) if any(not b.empty for b in brutos[k]) else pd.DataFrame()

    return df, brutos

# ---------------------------------------------------------------------------
# FUNÇÃO PRINCIPAL DA API
# ---------------------------------------------------------------------------
def buscar_parcelas_f360(jwt, d_ini, d_fim, mapa_cnpj, tipo="Despesa",
                         incluir_liquidacao=True, progresso=None, log=None):
    log = log if log is not None else []
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    tipos_data = ["Vencimento"] + (["Liquidação"] if incluir_liquidacao else [])
    janelas = list(_janelas(d_ini, d_fim))

    unicas, passo, total = {}, 0, len(janelas) * len(tipos_data)
    for td in tipos_data:
        for ini, fim in janelas:
            rotulo = f"Títulos {tipo} / {td} {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
            try:
                # Primeiro consulta com CNPJ. Depois faz também a consulta ampla
                # e une os registros das empresas desejadas. Isso evita perder
                # títulos quando o filtro "empresas" da API retorna apenas parte
                # dos registros.
                itens_filtrados = _listar_titulos(jwt, tipo, ini, fim, td, cnpjs)
                todos = _listar_titulos(jwt, tipo, ini, fim, td, [])
                digitos_alvo = {_so_digitos(c) for c in mapa_cnpj}
                itens_amplos = [p for p in todos if _da_rede(p, digitos_alvo)]

                por_id = {}
                for p in itens_filtrados + itens_amplos:
                    pid = p.get("ParcelaId")
                    if pid:
                        por_id[("id", str(pid))] = p
                    else:
                        tit = p.get("DadosDoTitulo") or {}
                        chave = (
                            "sem_id",
                            _so_digitos((tit.get("Empresa") or {}).get("Inscricao")),
                            str(p.get("Numero") or tit.get("NumeroDoTitulo") or ""),
                            str(p.get("Vencimento") or ""),
                            str(p.get("ValorBruto") or ""),
                            str(p.get("Liquidacao") or ""),
                        )
                        por_id[chave] = p

                itens = list(por_id.values())
                log.append(
                    f"{rotulo}: filtro CNPJ={len(itens_filtrados)} | "
                    f"consulta ampla={len(todos)} | após CNPJ={len(itens_amplos)} | "
                    f"união={len(itens)}"
                )
            except Exception as e:
                log.append(f"{rotulo}: ERRO -> {e}")
                itens = []
            for p in itens:
                # O ParcelaId é a chave oficial. Se vier ausente, não podemos
                # usar None como chave, pois isso faria vários títulos virarem
                # um único registro.
                parcela_id = p.get("ParcelaId")
                if parcela_id:
                    chave = ("id", str(parcela_id))
                else:
                    tit = p.get("DadosDoTitulo") or {}
                    empresa = _so_digitos((tit.get("Empresa") or {}).get("Inscricao"))
                    chave = (
                        "sem_id",
                        empresa,
                        str(p.get("Numero") or tit.get("NumeroDoTitulo") or ""),
                        str(p.get("Vencimento") or ""),
                        str(p.get("ValorBruto") or ""),
                        str(p.get("Liquidacao") or ""),
                    )
                unicas[chave] = p
            passo += 1
            if progresso:
                progresso(passo / total)

    df_titulos = _normaliza_titulos(list(unicas.values()), mapa_cnpj, tipo_padrao="RECEITA" if tipo == "Receita" else "DESPESA")

    if tipo == "Receita":
        try:
            df_cartoes = buscar_cartoes_f360(jwt, d_ini, d_fim, mapa_cnpj, log=log)
            log.append(f"Cartões API: {len(df_cartoes)} parcelas | líquido R$ {df_cartoes['Valor'].sum():,.2f}" if not df_cartoes.empty else "Cartões API: 0 parcelas")
        except Exception as e:
            log.append(f"Erro ao buscar cartões na API: {e}")
            df_cartoes = pd.DataFrame()

        partes = [d for d in (df_titulos, df_cartoes) if d is not None and not d.empty]
        return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()

    return df_titulos


# ---------------------------------------------------------------------------
# RELATÓRIO OFICIAL "FLUXO DE CAIXA.XLSX" (tela Fluxo de Caixa do F360)
# Já vem com saldo inicial, saldo final por dia e a coluna "Orçamentos
# (entrada)" -- a previsão de receita do plano orçamentário para dias que
# ainda não têm lançamento real. É a fonte mais confiável: usar os números
# dela direto garante bater 100% com a tela do F360, sem heurística.
# ---------------------------------------------------------------------------
def _ler_contas_do_filtro(arquivo):
    """Lê a aba 'Filtros' para saber quais contas esse export cobre."""
    try:
        df = pd.read_excel(arquivo, sheet_name="Filtros", header=None, dtype=object)
    except Exception:
        return []
    for _, row in df.iterrows():
        vals = [str(v) for v in row.dropna()]
        if vals and "conta" in vals[0].lower() and len(vals) > 1:
            return [c.strip() for c in vals[1].split(",") if c.strip()]
    return []


def processar_fluxo_de_caixa_oficial(arquivo):
    """
    Lê o export 'Fluxo de Caixa.xlsx' (F360 > Fluxo de Caixa > Exportar).
    Devolve (df_dias, saldo_inicial, contas):
      df_dias: uma linha por dia com Dia, Mes, Ano, Cartoes, Boleto,
               Orcamento_Entrada, Outros_Recebimentos, Total_Entradas,
               Orcamento_Saida, Outros_Pagamentos, Total_Saidas, Saldo.
      saldo_inicial: valor da linha 'Saldo Inicial' do relatório.
      contas: lista de contas bancárias que esse export cobre (da aba Filtros).
    """
    df_raw = pd.read_excel(arquivo, sheet_name="Fluxo de Caixa", header=None, dtype=object)
    cab = _acha_cabecalho(df_raw, ["Data", "Saldo"])
    if cab is None:
        raise ValueError("Não achei o cabeçalho (Data / Saldo) na aba 'Fluxo de Caixa'.")

    colunas = [str(c).strip() for c in df_raw.iloc[cab].values]
    df = df_raw.iloc[cab + 1:].copy()
    df.columns = colunas

    saldo_inicial = 0.0
    linha_inicial = df[df.iloc[:, 0].astype(str).str.contains("Saldo Inicial", na=False)]
    if not linha_inicial.empty:
        saldo_inicial = _num(linha_inicial.iloc[0].get("Saldo"))

    df = df[pd.to_datetime(df.iloc[:, 0], errors="coerce").notna()].copy()
    df["Data"] = pd.to_datetime(df["Data"], errors="coerce")

    ren = {
        "Cartões": "Cartoes", "Boleto": "Boleto",
        "Orçamentos (entrada)": "Orcamento_Entrada",
        "Outros Recebimentos": "Outros_Recebimentos",
        "Total": "Total_Entradas",  # 1ª ocorrência; a 2ª é tratada abaixo
        "Orçamentos (saída)": "Orcamento_Saida",
        "Outros Pagamentos": "Outros_Pagamentos",
        "Saldo": "Saldo",
    }
    # há duas colunas "Total" (entradas e saídas); renomeia pela posição
    cols_novas, vistos_total = [], 0
    for c in df.columns:
        c_s = str(c).strip()
        if c_s == "Total" or c_s == "Total ":
            vistos_total += 1
            cols_novas.append("Total_Entradas" if vistos_total == 1 else "Total_Saidas")
        else:
            cols_novas.append(ren.get(c_s, c_s))
    df.columns = cols_novas

    for c in ["Cartoes", "Boleto", "Orcamento_Entrada", "Outros_Recebimentos", "Total_Entradas",
             "Orcamento_Saida", "Outros_Pagamentos", "Total_Saidas", "Saldo"]:
        if c in df.columns:
            df[c] = df[c].apply(_num)

    df["Dia"] = df["Data"].dt.day
    df["Mes"] = df["Data"].dt.month
    df["Ano"] = df["Data"].dt.year

    contas = _ler_contas_do_filtro(arquivo)
    return df.reset_index(drop=True), saldo_inicial, contas


# ---------------------------------------------------------------------------
# CONTAS BANCÁRIAS (API) -- não traz saldo, só cadastro (Id, Nome, Agência...).
# Serve para pegar o Id real de cada conta, usado no filtro do Extrato
# Bancário (seção 9 do manual), em vez de casar texto por heurística.
# ---------------------------------------------------------------------------
def listar_contas_bancarias(jwt):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    r = requests.get(f"{BASE}/ContaBancariaPublicAPI/ListarContasBancarias", headers=headers, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    corpo = r.json()
    if isinstance(corpo, dict) and corpo.get("Ok") is False:
        raise RuntimeError(f"F360 retornou erro: {str(corpo)[:300]}")
    return corpo.get("Result") or []


def mapear_ids_contas(jwt, nomes_conhecidos=None):
    """Monta {Id: Nome da conta} a partir do cadastro real, em vez de
    hardcode. nomes_conhecidos (opcional) é um dict {pedaço do nome: nome
    padronizado que o app usa}, tipo {'PANTANAL': '17 Pantanal Itaú'}, só
    para exibir com o mesmo rótulo que o resto do app já usa."""
    contas = listar_contas_bancarias(jwt)
    nomes_conhecidos = nomes_conhecidos or {}
    saida = {}
    for c in contas:
        nome = str(c.get("Nome") or "").strip()
        nome_up = nome.upper()
        rotulo = next((v for k, v in nomes_conhecidos.items() if k.upper() in nome_up), nome)
        saida[c.get("Id")] = rotulo
    return saida


# ---------------------------------------------------------------------------
# TABELA DO FLUXO DE CAIXA LIDA DIRETO DA TELA (ler_tabela_fluxo.py)
# Formato: 2 linhas de cabeçalho, 1 linha "Saldo Inicial (dd/mm/aaaa)",
# N linhas de dia (10 células: Data, Cartões, Boleto, Orçamento entrada,
# Outros Recebimentos, Total entrada, Orçamento saída, Outros Pagamentos,
# Total saída, Saldo) e 1 linha final "Saldo Final".
# ---------------------------------------------------------------------------
def processar_tabela_fluxo_dom(caminho_csv):
    import csv as _csv
    with open(caminho_csv, encoding="utf-8-sig") as f:
        linhas = list(_csv.reader(f, delimiter=";"))

    saldo_inicial, data_inicial = 0.0, None
    dias = []

    for linha in linhas:
        linha = [c.strip() for c in linha]
        if not linha or not linha[0]:
            continue
        rotulo = linha[0]

        if rotulo.startswith("Saldo Inicial"):
            m = re.search(r"\((\d{2})/(\d{2})/(\d{4})\)", rotulo)
            if m:
                data_inicial = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
            saldo_inicial = _num(linha[-1])
            continue

        if rotulo in ("Saldo Final",) or not re.match(r"^\d{2}/\d{2}/\d{4}$", rotulo):
            continue  # pula cabeçalhos e a linha de total

        # linha de dia: Data, Cartões, Boleto, OrcE, OutrosE, TotalE, OrcS, OutrosS, TotalS, Saldo
        vals = (linha + [""] * 10)[:10]
        d, m_, y = vals[0].split("/")
        dias.append({
            "Data": f"{y}-{m_}-{d}",
            "Cartoes": _num(vals[1]), "Boleto": _num(vals[2]),
            "Orcamento_Entrada": _num(vals[3]), "Outros_Recebimentos": _num(vals[4]),
            "Total_Entradas": _num(vals[5]),
            "Orcamento_Saida": _num(vals[6]), "Outros_Pagamentos": _num(vals[7]),
            "Total_Saidas": _num(vals[8]),
            "Saldo": _num(vals[9]),
        })

    df = pd.DataFrame(dias)
    if not df.empty:
        df["Data"] = pd.to_datetime(df["Data"])
        df["Dia"] = df["Data"].dt.day
        df["Mes"] = df["Data"].dt.month
        df["Ano"] = df["Data"].dt.year

    return df, saldo_inicial