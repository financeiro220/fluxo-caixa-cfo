"""
f360_api.py - Integração com a API pública do F360.

- Parcelas de títulos (despesas e receitas)      -> ParcelasDeTituloPublicAPI/ListarParcelasDeTitulos
- Parcelas de cartões (RedeCard, iFood, etc.)    -> CARTOES_ENDPOINT (confirmar no manual, seção 7)
- Leitura do export "Parcelas de Cartões" do F360 (xlsx/csv) como alternativa à API
"""
import json
import re
import unicodedata
from datetime import datetime, timedelta

import pandas as pd
import requests

BASE = "https://financas.f360.com.br"
JANELA_DIAS = 30  # margem sobre o limite de 31 dias por consulta

# Endpoint de parcelas de cartões (seção "7 - Parcelas de Cartões" do manual F360).
CARTOES_ENDPOINT = "ParcelasDeCartoesPublicAPI/ListarParcelasDeCartoes"


# ---------------------------------------------------------------------------
# Autenticação e utilitários
# ---------------------------------------------------------------------------
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


def _da_rede(p, digitos):
    insc = ((p.get("DadosDoTitulo") or {}).get("Empresa") or {}).get("Inscricao")
    return _so_digitos(insc) in digitos


def _num(v):
    """Converte 1234.5, '1.234,56' ou 'R$ 1.234,56' em float."""
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
    """Aceita '23/09/2026', '2026-09-23', '2026-09-23T10:00:00Z', Timestamp ou vazio."""
    if v is None or (not isinstance(v, str) and pd.isna(v)):
        return pd.NaT
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return pd.NaT
        if re.match(r"^\d{2}/\d{2}/\d{4}", s):
            ts = pd.to_datetime(s[:10], format="%d/%m/%Y", errors="coerce")
        else:
            ts = pd.to_datetime(s, errors="coerce")
    else:
        ts = pd.to_datetime(v, errors="coerce")
    if pd.notna(ts) and getattr(ts, "tzinfo", None) is not None:
        ts = ts.tz_localize(None)
    return ts


# ---------------------------------------------------------------------------
# Parcelas de TÍTULOS (despesas e receitas)
# ---------------------------------------------------------------------------
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


def _normaliza(parcelas, mapa_cnpj, tipo_padrao="DESPESA"):
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
                "Empresa": empresa,
                "Conta": p.get("Conta") or "",
                "Cliente / Fornecedor": fornecedor,
                "Plano de Contas": r.get("PlanoDeContas") or "Outros",
                "Valor": bruto * peso,
                "Valor_Bruto": bruto * peso,
                "Status": status,
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

    # Data de caixa: liquidação se já pago, senão vencimento.
    df["Vencimento_dt"] = df["Liquidacao_dt"].where(
        (df["Status_Clean"] == "REALIZADO") & df["Liquidacao_dt"].notna(),
        df["Vencimento_real"],
    )
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df


def _coletar_titulos(jwt, tipo, d_ini, d_fim, mapa_cnpj, incluir_liquidacao, progresso, log):
    digitos = {_so_digitos(c) for c in mapa_cnpj}
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]
    tipos_data = ["Vencimento"] + (["Liquidação"] if incluir_liquidacao else [])
    janelas = list(_janelas(d_ini, d_fim))

    unicas, passo, total = {}, 0, len(janelas) * len(tipos_data)
    for td in tipos_data:
        for ini, fim in janelas:
            rotulo = f"Títulos {tipo} / {td} {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
            try:
                itens = _listar(jwt, tipo, ini, fim, td, cnpjs)
                log.append(f"{rotulo}: {len(itens)} parcelas")
                if not itens:  # fallback: sem filtro de empresas, filtrando localmente
                    todos = _listar(jwt, tipo, ini, fim, td, [])
                    itens = [p for p in todos if _da_rede(p, digitos)]
                    log.append(f"   sem filtro de empresas: {len(todos)} parcelas, {len(itens)} das suas lojas")
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
    return list(unicas.values())


# ---------------------------------------------------------------------------
# Parcelas de CARTÕES (RedeCard, iFood, Elo, Visa, Master...)
# ---------------------------------------------------------------------------
# Nomes das colunas da tela "Parcelas de Cartões" do F360, e variações prováveis da API.
# A comparação ignora acentos, pontos, espaços e maiúsculas.
_ALIAS = {
    "empresa": ["empresa", "nomeempresa", "cnpjempresa", "cnpj"],
    "adquirente": ["adquirente", "nomeadquirente"],
    "bandeira": ["bandeira"],
    "parcela": ["parcela", "numerodaparcela", "parcelamento"],
    "venda": ["dtvenda", "datavenda", "datadavenda"],
    "vencimento": ["vencim", "vencimento", "datavencimento"],
    "bruto": ["vbruto", "valorbruto"],
    "liquido": ["vliquido", "valorliquido"],
    "conta": ["conta", "contaliquidacao", "contadeliquidacao"],
    "liquidacao": ["liquid", "liquidacao", "dataliquidacao"],
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
    """Traz para o nível de cima os campos de objetos aninhados (ex.: DadosDoCartao.Adquirente)."""
    saida = {} if saida is None else saida
    for k, v in reg.items():
        saida.setdefault(k, v)
        if isinstance(v, dict):
            _achata(v, saida)
    return saida


def _verdadeiro(v):
    return str(v).strip().lower() == "true"


def _normaliza_cartoes(registros, mapa_cnpj):
    mapa = {_so_digitos(k): v for k, v in mapa_cnpj.items()}
    linhas = []
    for i, reg in enumerate(registros):
        reg = _achata(reg)
        if _verdadeiro(reg.get("Cancelada")) or _verdadeiro(reg.get("Cancelado")):
            continue

        emp_raw = str(_pega(reg, "empresa") or "").strip()
        empresa = mapa.get(_so_digitos(emp_raw)) or emp_raw or "N/D"
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
            "Empresa": empresa,
            "Conta": str(_pega(reg, "conta") or ""),
            "Cliente / Fornecedor": f"{adq} ({band})" if band and band.lower() != adq.lower() else adq,
            "Plano de Contas": f"Receita de Vendas ({adq})",
            "Valor": liquido,          # o que efetivamente cai na conta
            "Valor_Bruto": bruto,
            "Data_Venda": _data(_pega(reg, "venda")),
            "Vencimento_real": _data(_pega(reg, "vencimento")),
            "Liquidacao_dt": _data(_pega(reg, "liquidacao")),
        })

    df = pd.DataFrame(linhas)
    if df.empty:
        return df

    for c in ("Data_Venda", "Vencimento_real", "Liquidacao_dt"):
        df[c] = pd.to_datetime(df[c], errors="coerce")

    # Liquidação preenchida = já caiu na conta; senão é previsão.
    df["Status_Clean"] = df["Liquidacao_dt"].notna().map({True: "REALIZADO", False: "PENDENTE"})
    df["Status"] = df["Status_Clean"].map({"REALIZADO": "Liquidado", "PENDENTE": "A receber"})
    df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
    df = df.dropna(subset=["Vencimento_dt"]).copy()
    df["Dia"] = df["Vencimento_dt"].dt.day
    return df


def _listar_cartoes(jwt, tipo, ini, fim, tipo_datas, cnpjs, endpoint):
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    url = f"{BASE}/{endpoint.lstrip('/')}"
    pagina, total, saida = 1, 1, []
    while pagina <= total:
        params = {"pagina": pagina, "tipo": tipo, "inicio": ini.isoformat(), "fim": fim.isoformat(),
                  "tipoDatas": tipo_datas, "status": "Todos"}
        if cnpjs:
            params["empresas"] = ",".join(cnpjs)
        r = requests.get(url, headers=headers, params=params, timeout=60)
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code} em '{endpoint}': {r.text[:300]}")
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


def _chave_cartao(it):
    return str(it.get("ParcelaId") or json.dumps(it, sort_keys=True, default=str))


def buscar_cartoes_f360(jwt, d_ini, d_fim, mapa_cnpj, endpoint=None, log=None, tipo="Receita"):
    """Parcelas de cartões/PIX por Vencimento e por Liquidação (sem duplicar entre as duas)."""
    log = log if log is not None else []
    endpoint = endpoint or CARTOES_ENDPOINT
    cnpjs = [_fmt_cnpj(c) for c in mapa_cnpj]

    registros, vistos = [], set()
    for td in ("Vencimento", "Liquidação"):
        for ini, fim in _janelas(d_ini, d_fim):
            rotulo = f"Cartões {tipo} / {td} {ini:%d/%m/%Y} a {fim:%d/%m/%Y}"
            try:
                itens = _listar_cartoes(jwt, tipo, ini, fim, td, cnpjs, endpoint)
                if not itens and cnpjs:  # fallback sem filtro de empresas
                    itens = _listar_cartoes(jwt, tipo, ini, fim, td, [], endpoint)
                log.append(f"{rotulo}: {len(itens)} parcelas")
            except Exception as e:
                log.append(f"{rotulo}: ERRO -> {e}")
                if td == "Vencimento":
                    raise
                itens = []
            for it in itens:
                chave = _chave_cartao(it)
                if td == "Vencimento":
                    registros.append(it)
                    vistos.add(chave)
                elif chave not in vistos:
                    registros.append(it)

    df_c = _normaliza_cartoes(registros, mapa_cnpj)
    if not df_c.empty:
        resumo = (df_c.groupby("Detalhe")
                  .agg(Qtd=("Valor", "size"), Liquido=("Valor", "sum"))
                  .sort_values("Liquido", ascending=False))
        log.append("Composição dos cartões (Detalhe | Qtd | Líquido):")
        for det, row in resumo.iterrows():
            log.append(f"   {det}: {int(row['Qtd'])} | R$ {row['Liquido']:,.2f}")
        tem_ifood = any("ifood" in str(d).lower() for d in resumo.index)
        log.append(f"iFood encontrado: {'SIM' if tem_ifood else 'NÃO — confira tipoDatas/filtro'}")
    return df_c


def processar_parcelas_cartoes_arquivo(arquivo, mapa_cnpj):
    """Lê o export da tela 'Parcelas de Cartões' do F360 (.xlsx, .xls ou .csv)."""
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
    df = df[df.apply(lambda r: _pega(r.to_dict(), "adquirente") is not None, axis=1)]  # tira linhas de total
    return _normaliza_cartoes(df.to_dict("records"), mapa_cnpj)


# ---------------------------------------------------------------------------
# Relatório nativo "Detalhes Fluxo de Caixa" (xlsx, 5 abas) exportado do F360.
# É a fonte da verdade: já separa Títulos, Cartões, Transferências e Ajustes,
# sem depender de heurística por palavra-chave.
# ---------------------------------------------------------------------------
def _nomes_lojas_chave(mapa_cnpj):
    """Extrai palavras-chave dos nomes das lojas para detectar intercompany
    pelo campo Pessoa (ex.: '4- PANTANAL' -> 'PANTANAL')."""
    chaves = set()
    for nome in mapa_cnpj.values():
        s = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode()
        for palavra in re.split(r"[^A-Za-z]+", s.upper()):
            if len(palavra) >= 4:  # ignora números de loja e conectores curtos
                chaves.add(palavra)
    return chaves


def _acha_cabecalho(df_raw, tokens):
    """Procura a linha de cabeçalho que contenha todos os tokens informados."""
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
    """
    Lê um ou mais arquivos 'Detalhes Fluxo de Caixa.xlsx' exportados do F360
    (o F360 pode dividir a exportação em vários arquivos) e devolve:
      - df_entradas: título+cartão+transferência+ajuste normalizados, uma linha
        por lançamento, prontos para exibir ou comparar com a API.
      - brutos: dict com os DataFrames originais de cada aba (para conferência).
    """
    if not isinstance(arquivos, (list, tuple)):
        arquivos = [arquivos]

    chaves_lojas = _nomes_lojas_chave(mapa_cnpj)
    linhas, brutos = [], {"titulos": [], "cartoes": [], "transferencias": [], "ajustes": []}

    for arq in arquivos:
        t = _ler_aba(arq, "Parcelas de Títulos", ["Empresa", "Pessoa", "Valor Bruto"])
        for _, r in t.iterrows():
            pessoa = str(r.get("Pessoa") or "").strip()
            pessoa_norm = unicodedata.normalize("NFKD", pessoa).encode("ascii", "ignore").decode().upper()
            intercompany = any(k in pessoa_norm for k in chaves_lojas)
            linhas.append({
                "Origem": "Título", "Detalhe": pessoa or "Não informado",
                "Empresa": str(r.get("Empresa") or "").strip(),
                "Conta": str(r.get("Conta") or "").strip(),
                "Cliente / Fornecedor": pessoa,
                "Número": r.get("Número"),
                "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Líquido")),
                "Vencimento_real": _data(r.get("Vencimento")),
                "Liquidacao_dt": _data(r.get("Liquidação/Agendamento")),
                "Categoria_CFO": ("7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO" if intercompany
                                 else "0. RECEITAS DE VENDAS"),
            })
        brutos["titulos"].append(t)

        c = _ler_aba(arq, "Parcelas de Cartões", ["Empresa", "Adquirente", "Valor Bruto"])
        for _, r in c.iterrows():
            adq = str(r.get("Adquirente") or "").strip()
            band = str(r.get("Bandeira") or "").strip()
            linhas.append({
                "Origem": "Cartão", "Detalhe": f"{adq} - {band}" if band else adq,
                "Empresa": str(r.get("Empresa") or "").strip(),
                "Conta": str(r.get("Conta") or "").strip(),
                "Cliente / Fornecedor": f"{adq} ({band})" if band else adq,
                "Número": r.get("Parcela"),
                "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Líquido")),
                "Vencimento_real": _data(r.get("Vencimento")),
                "Liquidacao_dt": _data(r.get("Liquidação/Agendamento")),
                "Categoria_CFO": "0. RECEITAS DE VENDAS",
            })
        brutos["cartoes"].append(c)

        tr = _ler_aba(arq, "Transferências", ["Conta", "Valor Bruto"])
        for _, r in tr.iterrows():
            linhas.append({
                "Origem": "Transferência", "Detalhe": f"-> {r.get('Conta Relacionada', '')}",
                "Empresa": "", "Conta": str(r.get("Conta") or "").strip(),
                "Cliente / Fornecedor": str(r.get("Conta Relacionada") or ""),
                "Número": None,
                "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Bruto")),
                "Vencimento_real": _data(r.get("Emissão")),
                "Liquidacao_dt": _data(r.get("Emissão")),
                "Categoria_CFO": "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO",
            })
        brutos["transferencias"].append(tr)

        aj = _ler_aba(arq, "Ajustes", ["Conta", "Valor Bruto"])
        for _, r in aj.iterrows():
            linhas.append({
                "Origem": "Ajuste", "Detalhe": "Ajuste manual",
                "Empresa": "", "Conta": str(r.get("Conta") or "").strip(),
                "Cliente / Fornecedor": "Ajuste", "Número": None,
                "Valor_Bruto": _num(r.get("Valor Bruto")),
                "Valor": _num(r.get("Valor Bruto")),
                "Vencimento_real": _data(r.get("Emissão")),
                "Liquidacao_dt": _data(r.get("Emissão")),
                "Categoria_CFO": "8. AJUSTES DE CAIXA",
            })
        brutos["ajustes"].append(aj)

    df = pd.DataFrame(linhas)
    if not df.empty:
        df["Vencimento_dt"] = df["Liquidacao_dt"].where(df["Liquidacao_dt"].notna(), df["Vencimento_real"])
        df = df.dropna(subset=["Vencimento_dt"]).copy()
        df["Dia"] = df["Vencimento_dt"].dt.day
        df["Status_Clean"] = "REALIZADO"  # este relatório só traz o que já está lançado/agendado
        df["Status"] = "Lançado"
        df["Tipo_Movimento"] = "RECEITA"
        df["ParcelaId"] = df["Origem"] + "_" + df.index.astype(str)

    for k in brutos:
        brutos[k] = pd.concat([b for b in brutos[k] if not b.empty], ignore_index=True) if any(not b.empty for b in brutos[k]) else pd.DataFrame()

    return df, brutos


# ---------------------------------------------------------------------------
# Função principal
# ---------------------------------------------------------------------------
def buscar_parcelas_f360(jwt, d_ini, d_fim, mapa_cnpj, tipo="Despesa",
                         incluir_liquidacao=True, progresso=None, log=None,
                         endpoint_cartoes=None):
    """
    tipo="Despesa": parcelas de títulos a pagar.
    tipo="Receita": parcelas de títulos a receber + parcelas de cartões (valor LÍQUIDO).
    """
    log = log if log is not None else []
    parcelas = _coletar_titulos(jwt, tipo, d_ini, d_fim, mapa_cnpj,
                                incluir_liquidacao, progresso, log)
    df = _normaliza(parcelas, mapa_cnpj, tipo_padrao="RECEITA" if tipo == "Receita" else "DESPESA")

    if tipo == "Receita":
        try:
            df_c = buscar_cartoes_f360(jwt, d_ini, d_fim, mapa_cnpj, endpoint_cartoes, log)
            log.append(f"Cartões: {len(df_c)} parcelas | bruto R$ {df_c['Valor_Bruto'].sum():,.2f} "
                       f"| líquido R$ {df_c['Valor'].sum():,.2f}" if not df_c.empty else "Cartões: 0 parcelas")
        except Exception as e:
            log.append(f"Cartões: ERRO -> {e}")
            df_c = pd.DataFrame()
        partes = [d for d in (df, df_c) if d is not None and not d.empty]
        return pd.concat(partes, ignore_index=True) if partes else pd.DataFrame()

    return df