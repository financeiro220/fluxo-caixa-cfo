import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta

# IMPORTAÇÃO DO MÓDULO F360
from f360_api import (
    autenticar_f360, 
    buscar_parcelas_f360,
    processar_fluxo_de_caixa_oficial
)

try:
    from f360_api import processar_tabela_fluxo_dom
    HAS_DOM_PROCESSOR = True
except ImportError:
    HAS_DOM_PROCESSOR = False

st.set_page_config(
    page_title="Borelli | Fluxo de Caixa",
    page_icon="🍦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# IDENTIDADE VISUAL — DASHBOARD EXECUTIVO
# ============================================================
st.markdown("""
<style>
    /* ---------- BASE ---------- */
    .stApp { background: #0B0F14; color: #F4F7FA; }
    [data-testid="stHeader"] { background: rgba(11,15,20,0.96); }
    [data-testid="stSidebar"] { background: #151A21; border-right: 1px solid #252C35; }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }

    /* ---------- TIPOGRAFIA ---------- */
    .hero-title { font-size: 30px; line-height: 1.05; font-weight: 800; letter-spacing: -0.8px; margin-bottom: 2px; color: #F8FAFC; }
    .hero-subtitle { color: #8F9AA8; font-size: 14px; margin-bottom: 18px; }
    .section-title { font-size: 18px; font-weight: 750; color: #F4F7FA; margin: 4px 0 10px 0; }
    .muted { color: #8994A3; font-size: 12px; }

    /* ---------- STATUS ---------- */
    .status-pill { display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px; border-radius: 999px; background: #123022; color: #58D68D; border: 1px solid #20583C; font-size: 12px; font-weight: 700; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #35D07F; display: inline-block; box-shadow: 0 0 10px rgba(53,208,127,.45); }

    /* ---------- CARDS ---------- */
    .kpi-card { background: linear-gradient(145deg, #151B23 0%, #10151C 100%); border: 1px solid #28313C; border-radius: 12px; padding: 15px 16px 14px 16px; min-height: 112px; box-shadow: 0 8px 24px rgba(0,0,0,.12); }
    .kpi-label { color: #8F9AA8; font-size: 11px; font-weight: 700; letter-spacing: .4px; text-transform: uppercase; margin-bottom: 7px; }
    .kpi-value { color: #F8FAFC; font-size: 24px; line-height: 1.05; font-weight: 800; letter-spacing: -.5px; }
    .kpi-green { color: #45D483; }
    .kpi-red { color: #FF6262; }
    .kpi-yellow { color: #F4C95D; }
    .kpi-blue { color: #69B7FF; }
    .kpi-foot { color: #697585; font-size: 11px; margin-top: 8px; }

    /* ---------- EXECUTIVE PANELS ---------- */
    .panel { background: #11161D; border: 1px solid #252D37; border-radius: 12px; padding: 16px; margin-bottom: 14px; }
    .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .panel-title { font-size: 15px; font-weight: 750; color: #F4F7FA; }

    /* ---------- ALERTS ---------- */
    .alert-good { background: #10271D; border: 1px solid #24553C; color: #67E39A; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    .alert-warn { background: #2A2413; border: 1px solid #67531D; color: #F3D36A; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    .alert-danger { background: #2A1719; border: 1px solid #663034; color: #FF8585; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }

    /* ---------- TABLES ---------- */
    [data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }

    /* ---------- BUTTONS ---------- */
    .stButton > button { border-radius: 8px; border: 1px solid #343D49; background: #171D25; color: #E9EEF3; font-weight: 650; }
    .stButton > button:hover { border-color: #00875A; color: #5CE39A; }

    /* ---------- DIVIDER ---------- */
    hr { border-color: #252D37 !important; }
</style>
""", unsafe_allow_html=True)

try:
    F360_TOKEN = st.secrets["F360_TOKEN"]
except:
    F360_TOKEN = "11001cbb-792d-45e5-b2f9-03ffc46fe7ed"

MAPA_CNPJ_LOJA = {
    "36240923000168": "4- PANTANAL",
    "36240923000249": "5- ESTAÇÃO",
    "36240923000320": "8 - GOIABEIRAS"
}

def categorizar_plano_contas(plano):
    p = str(plano).upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    if any(k in p for k in ['SÓCIO', 'SOCIO', 'LUCRO', 'DISTRIBUIÇÃO', 'DIVIDENDO', 'PRÓ-LABORE', 'PRO-LABORE']): return "7. DESPESAS DE SÓCIOS"
    if any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'LEITE', 'INSUMOS', 'BOBINAS', 'FRUTAS']): return "1. FORNECEDORES / MERCADORIAS (CMV)"
    if any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS']): return "2. IMPOSTOS SOBRE VENDAS"
    if any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'ENERGIA', 'ÁGUA', 'IPTU', 'LIMPEZA']): return "3. DESPESAS DE OCUPAÇÃO"
    if any(k in p for k in ['SALÁRIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'RESCISÃO', 'FUNCIONÁRIOS']): return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    if any(k in p for k in ['EMPRÉSTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFAS']): return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    return "5. DESPESAS OPERACIONAIS & VENDAS"

def categorizar_receita(row):
    p = str(row.get("Plano de Contas") or "").upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    return "0. RECEITAS DE VENDAS"

@st.cache_data(ttl=3600)
def carregar_fluxo_oficial(_arquivos):
    resultado = {}
    for arq in _arquivos:
        df_dias, saldo_ini, contas = processar_fluxo_de_caixa_oficial(arq)
        chave = contas[0] if len(contas) == 1 else "Ver Todas as Contas"
        resultado[chave] = {"df": df_dias, "saldo_inicial": saldo_ini, "contas": contas}
    return resultado

def highlight_saldo(row):
    styles = [''] * len(row)
    if row["Linha de Extrato"] == "6. 🏦 SALDO FINAL BANCÁRIO":
        for i, val in enumerate(row):
            if isinstance(val, (int, float)):
                if val < 0: styles[i] = 'color: #ff6262; font-weight: bold;'
                elif val > 0: styles[i] = 'color: #45d483; font-weight: bold;'
    return styles

def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def _preparar_titulos_detalhe(df, status=None):
    if df is None or df.empty: return pd.DataFrame()
    d = df.copy()
    if status == "REALIZADO": d = d[d["Status_Clean"].astype(str).str.upper() == "REALIZADO"]
    elif status == "PENDENTE": d = d[d["Status_Clean"].astype(str).str.upper() == "PENDENTE"]

    colunas_preferidas = ["Vencimento_dt", "Empresa", "Empresa_Loja", "Cliente/Fornecedor", "Cliente", "Fornecedor", "Plano de Contas", "Categoria_CFO", "Valor", "Status_Clean", "Status", "Data_Liquidacao"]
    colunas = [c for c in colunas_preferidas if c in d.columns]
    for c in d.columns:
        if c not in colunas and any(k in str(c).lower() for k in ["titulo", "documento", "parcela", "id", "descrição", "descricao"]):
            colunas.append(c)

    if not colunas: return d
    d = d[colunas].copy()
    d = d.loc[:, ~d.columns.duplicated(keep="first")].copy()

    if "Vencimento_dt" in d.columns:
        d["Vencimento"] = pd.to_datetime(d["Vencimento_dt"], errors="coerce").dt.strftime("%d/%m/%Y")
        d = d.drop(columns=["Vencimento_dt"])

    if "Data_Liquidacao" in d.columns:
        d["Liquidação"] = pd.to_datetime(d["Data_Liquidacao"], errors="coerce").dt.strftime("%d/%m/%Y")

    if "Valor" in d.columns: d["Valor"] = pd.to_numeric(d["Valor"], errors="coerce").fillna(0)

    rename = {"Empresa_Loja": "Loja", "Cliente/Fornecedor": "Cliente / Fornecedor", "Plano de Contas": "Plano de Contas", "Status_Clean": "Status"}
    d = d.rename(columns=rename)
    d = d.loc[:, ~d.columns.duplicated(keep="first")].copy()
    
    nomes, contagem = [], {}
    for nome in d.columns:
        nome = str(nome)
        if nome not in contagem:
            contagem[nome] = 0
            nomes.append(nome)
        else:
            contagem[nome] += 1
            nomes.append(f"{nome}_{contagem[nome]}")
    d.columns = nomes
    return d

def render_movement_cards(previsto, liquidado, aberto, titulo="Lançamentos", df_detail=None, state_prefix="mov"):
    c1, c2, c3 = st.columns(3)
    cards = [
        (c1, "PREVISTO", previsto, "kpi-blue", "Todos os títulos do período", "ALL"),
        (c2, "LIQUIDADO", liquidado, "kpi-green", "Valores já realizados", "REALIZADO"),
        (c3, "EM ABERTO", aberto, "kpi-yellow" if aberto > 0 else "kpi-green", "Previsto ainda não liquidado", "PENDENTE")
    ]

    for col, label, value, color_class, foot, status in cards:
        with col:
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">{"📊" if status == "ALL" else "🟢" if status == "REALIZADO" else "🟡"} {titulo} · {label}</div>
                <div class="kpi-value {color_class}">{brl(value)}</div>
                <div class="kpi-foot">{foot}</div>
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"Ver títulos · {label}", key=f"btn_{state_prefix}_{status}", use_container_width=True):
                st.session_state.show_kpi_data = f"{state_prefix}:{status}"

    current = st.session_state.get("show_kpi_data")
    if isinstance(current, str) and current.startswith(f"{state_prefix}:"):
        status = current.split(":", 1)[1]
        df_show = _preparar_titulos_detalhe(df_detail, None if status == "ALL" else status)

        st.markdown("""<div style="background:#11161D; border:1px solid #303A46; border-radius:12px; padding:16px; margin:14px 0 18px 0;">""", unsafe_allow_html=True)
        h1, h2 = st.columns([5, 1])
        with h1:
            nomes = {"ALL": "Todos os títulos", "REALIZADO": "Títulos liquidados", "PENDENTE": "Títulos em aberto"}
            st.markdown(f"### 📋 {titulo} · {nomes.get(status, status)}")
        with h2:
            if st.button("✕ Fechar", key=f"fechar_box_{state_prefix}_{status}", use_container_width=True):
                st.session_state.show_kpi_data = None
                st.rerun()

        if df_show.empty:
            st.info("Nenhum título encontrado para este status no período/loja selecionados.")
        else:
            if "Valor" in df_show.columns:
                total = df_show["Valor"].sum()
                st.caption(f"{len(df_show):,} título(s) · Total: {brl(total)}".replace(",", "."))
                st.dataframe(df_show.style.format({"Valor": "R$ {:,.2f}"}), use_container_width=True, hide_index=True)
            else:
                st.dataframe(df_show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# ESTADO E SIDEBAR
# ============================================================
if 'fluxo_oficial_cache' not in st.session_state: st.session_state.fluxo_oficial_cache = {}
if 'show_kpi_data' not in st.session_state: st.session_state.show_kpi_data = None

with st.sidebar:
    st.markdown("## 🍦 BORELLI")
    st.caption("Controladoria · Fluxo de Caixa")
    st.divider()

    st.markdown("### ⚡ Sincronização F360")
    periodo_api = st.date_input("Período DRE (API)", (date(2026, 10, 1), date(2026, 10, 31)), format="DD/MM/YYYY")

    if st.button("🚀 Sincronizar API", use_container_width=True) and len(periodo_api) == 2:
        with st.spinner("Sincronizando dados do F360..."):
            st.session_state.jwt = autenticar_f360(F360_TOKEN)
            d_ini, d_fim = periodo_api[0], periodo_api[1]

            log_desp, log_rec = [], []
            df_desp = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Despesa", log=log_desp)
            if not df_desp.empty: df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(categorizar_plano_contas)
            st.session_state.df_api_desp, st.session_state.log_api_desp = df_desp, log_desp

            df_rec = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Receita", log=log_rec)
            if not df_rec.empty:
                df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
                df_rec["Tipo_Movimento"] = "RECEITA"
            st.session_state.df_api_rec, st.session_state.log_api_rec = df_rec, log_rec
            st.session_state.log_api_periodo = (d_ini, d_fim)
            st.success(f"🟢 API sincronizada! Despesas: {len(df_desp):,} | Receitas: {len(df_rec):,}")

    with st.expander("🔎 LOG / DIAGNÓSTICO DA API F360", expanded=False):
        logs_d = st.session_state.get("log_api_desp", [])
        logs_r = st.session_state.get("log_api_rec", [])
        periodo_log = st.session_state.get("log_api_periodo")
        if periodo_log: st.caption(f"Período consultado: {periodo_log[0]:%d/%m/%Y} até {periodo_log[1]:%d/%m/%Y}")
        if logs_d: st.markdown("**DESPESAS**"); st.code("\n".join(logs_d), language="text")
        if logs_r: st.markdown("**RECEITAS**"); st.code("\n".join(logs_r), language="text")
        if not logs_d and not logs_r: st.info("Clique em '🚀 Sincronizar API' para gerar o log.")

    st.divider()
    st.markdown("### 🏦 Dados oficiais do caixa")
    file_fluxo_oficial = st.file_uploader("F360 > Fluxo de Caixa > Exportar", type=["xlsx"], accept_multiple_files=True)
    file_tabela_csv = st.file_uploader("CSV Automático (opcional)", type=["csv"], key="tabela_csv") if HAS_DOM_PROCESSOR else None
    st.divider()
    st.caption("🔐 A fonte oficial do saldo bancário continua sendo o export do Fluxo de Caixa do F360.")

# ============================================================
# CARREGA ARQUIVOS
# ============================================================
if file_fluxo_oficial: st.session_state.fluxo_oficial_cache.update(carregar_fluxo_oficial(file_fluxo_oficial))
if file_tabela_csv is not None and HAS_DOM_PROCESSOR:
    df_dom, saldo_ini_dom = processar_tabela_fluxo_dom(file_tabela_csv)
    st.session_state.fluxo_oficial_cache["CSV (via navegador)"] = {"df": df_dom, "saldo_inicial": saldo_ini_dom, "contas": []}

fluxo_oficial = st.session_state.fluxo_oficial_cache
_lista_dfs = [d for d in [st.session_state.get("df_api_desp"), st.session_state.get("df_api_rec")] if d is not None and not d.empty]
df_api = pd.concat(_lista_dfs, ignore_index=True) if _lista_dfs else pd.DataFrame()

# ============================================================
# CABEÇALHO E FILTROS
# ============================================================
st.markdown("""
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px;">
    <div><div class="hero-title">🍦 BORELLI</div><div class="hero-subtitle">Fluxo de Caixa · Controladoria</div></div>
    <div class="status-pill"><span class="status-dot"></span>F360 conectado</div>
</div>
""", unsafe_allow_html=True)

f1, f2 = st.columns([2.2, 1])
with f1:
    opcoes_conta = ["Ver Todas as Contas", "17 Pantanal Itaú", "51 Estação Itaú", "61 Itaú Goiabeiras", "52 RT", "36 MJL"]
    if "CSV (via navegador)" in fluxo_oficial: opcoes_conta.append("CSV (via navegador)")
    conta_selecionada = st.radio("Conta / Loja", opcoes_conta, horizontal=True)

with f2:
    min_d, max_d = date(2026, 10, 1), date(2026, 10, 31)
    if not df_api.empty: min_d, max_d = df_api['Vencimento_dt'].min().date(), df_api['Vencimento_dt'].max().date()
    for dados in fluxo_oficial.values():
        if not dados["df"].empty:
            min_d = min(min_d, dados["df"]["Data"].min().date())
            max_d = max(max_d, dados["df"]["Data"].max().date())
    date_range = st.date_input("Período", value=(min_d, max_d), format="DD/MM/YYYY")

# ============================================================
# FILTRO API E VARIÁVEIS GLOBAIS
# ============================================================
df_kpi = df_api.copy()
if not df_kpi.empty:
    if conta_selecionada not in ("Ver Todas as Contas", "CSV (via navegador)"): df_kpi = df_kpi[df_kpi['Empresa'] == conta_selecionada]
    if isinstance(date_range, tuple) and len(date_range) == 2: df_kpi = df_kpi[(df_kpi['Vencimento_dt'].dt.date >= date_range[0]) & (df_kpi['Vencimento_dt'].dt.date <= date_range[1])]

df_rec_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'RECEITA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()
df_desp_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'DESPESA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()

tot_rec_prev = df_rec_kpi['Valor'].sum() if not df_rec_kpi.empty else 0.0
tot_rec_real = df_rec_kpi[df_rec_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_rec_kpi.empty else 0.0
tot_prev = df_desp_kpi['Valor'].sum() if not df_desp_kpi.empty else 0.0
tot_real = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_desp_kpi.empty else 0.0
tot_pend = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'PENDENTE']['Valor'].sum() if not df_desp_kpi.empty else 0.0

oficial = fluxo_oficial.get(conta_selecionada) or fluxo_oficial.get("Ver Todas as Contas") or fluxo_oficial.get("CSV (via navegador)")
if not oficial and len(fluxo_oficial) == 1: oficial = list(fluxo_oficial.values())[0]

df_of_exec, saldo_final_exec, entradas_oficiais, saidas_oficiais = pd.DataFrame(), None, None, None
if oficial:
    df_of_exec = oficial["df"].copy()
    if isinstance(date_range, tuple) and len(date_range) == 2: df_of_exec = df_of_exec[(df_of_exec["Data"].dt.date >= date_range[0]) & (df_of_exec["Data"].dt.date <= date_range[1])]
    if not df_of_exec.empty:
        entradas_oficiais = df_of_exec["Total_Entradas"].sum()
        saidas_oficiais = df_of_exec["Total_Saidas"].sum()
        saldo_final_exec = df_of_exec.iloc[-1]["Saldo"]

entradas_exec = entradas_oficiais if entradas_oficiais is not None else tot_rec_prev
saidas_exec = saidas_oficiais if saidas_oficiais is not None else tot_prev
resultado_exec = entradas_exec - saidas_exec

# ============================================================
# ABAS DO DASHBOARD
# ============================================================
tabs = st.tabs(["📊 Visão Executiva", "📅 Fluxo Diário", "📋 DRE de Caixa", "🏪 Comparativo Por Loja"])

with tabs[0]:
    st.markdown('<div class="section-title">Resumo financeiro do período</div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.markdown(f'<div class="kpi-card"><div class="kpi-label">💰 Entradas</div><div class="kpi-value kpi-green">{brl(entradas_exec)}</div><div class="kpi-foot">Caixa oficial quando disponível</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="kpi-card"><div class="kpi-label">🔴 Saídas</div><div class="kpi-value kpi-red">{brl(saidas_exec)}</div><div class="kpi-foot">Realizadas + previstas do caixa</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="kpi-card"><div class="kpi-label">📈 Resultado do Caixa</div><div class="kpi-value {"kpi-green" if resultado_exec >= 0 else "kpi-red"}">{brl(resultado_exec)}</div><div class="kpi-foot">Entradas − saídas</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="kpi-card"><div class="kpi-label">🏦 Saldo Final</div><div class="kpi-value {"kpi-green" if (saldo_final_exec or 0) >= 0 else "kpi-red"}">{brl(saldo_final_exec) if saldo_final_exec is not None else "—"}</div><div class="kpi-foot">Saldo do export oficial F360</div></div>', unsafe_allow_html=True)
    with c5: st.markdown(f'<div class="kpi-card"><div class="kpi-label">⚠️ Em Aberto</div><div class="kpi-value {"kpi-green" if tot_pend == 0 else "kpi-yellow"}">{brl(tot_pend)}</div><div class="kpi-foot">{"Nenhuma despesa pendente" if tot_pend == 0 else "Despesas ainda em aberto"}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if saldo_final_exec is not None and saldo_final_exec < 0: st.markdown('<div class="alert-danger">🔴 Atenção: o saldo final do período está negativo.</div>', unsafe_allow_html=True)
    elif tot_pend > 0: st.markdown(f'<div class="alert-warn">🟡 Atenção: existem {brl(tot_pend)} em despesas pendentes na API.</div>', unsafe_allow_html=True)
    else: st.markdown('<div class="alert-good">🟢 Caixa sem despesas pendentes identificadas na API para o período filtrado.</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    g1, g2 = st.columns([1.75, 1])
    with g1:
        st.markdown('<div class="panel"><div class="panel-header"><div class="panel-title">Fluxo de Caixa · Entradas × Saídas</div><div class="muted">por dia</div></div></div>', unsafe_allow_html=True)
        if not df_of_exec.empty:
            chart_df = df_of_exec[["Data", "Total_Entradas", "Total_Saidas"]].set_index("Data")
            chart_df.columns = ["Entradas", "Saídas"]
            st.line_chart(chart_df, height=280)
        else: st.info("Anexe o export 'Fluxo de Caixa.xlsx' para visualizar o fluxo diário oficial.")

    with g2:
        st.markdown('<div class="panel"><div class="panel-header"><div class="panel-title">Composição das Saídas</div><div class="muted">API F360</div></div></div>', unsafe_allow_html=True)
        if not df_desp_kpi.empty:
            comp = df_desp_kpi.groupby("Categoria_CFO")["Valor"].sum().sort_values(ascending=True)
            comp.index = [str(x).replace("1. ", "").replace("2. ", "").replace("3. ", "").replace("4. ", "").replace("5. ", "").replace("6. ", "").replace("7. ", "") for x in comp.index]
            st.bar_chart(comp, height=280)
        else: st.info("Sincronize a API para visualizar a composição das despesas.")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">🏪 Resultado por Loja</div>', unsafe_allow_html=True)
    if not df_api.empty:
        df_loja_exec = df_kpi.copy()
        dimensao_exec = "Empresa_Loja" if ("Empresa_Loja" in df_loja_exec.columns and df_loja_exec["Empresa_Loja"].replace("", np.nan).notna().any()) else "Empresa"
        rec_loja = df_loja_exec[(df_loja_exec["Tipo_Movimento"] == "RECEITA") & (df_loja_exec["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")].groupby(dimensao_exec)["Valor"].sum()
        desp_loja = df_loja_exec[(df_loja_exec["Tipo_Movimento"] == "DESPESA") & (df_loja_exec["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")].groupby(dimensao_exec)["Valor"].sum()
        resumo_loja = pd.concat([rec_loja.rename("Entradas"), desp_loja.rename("Saídas")], axis=1).fillna(0)
        resumo_loja["Resultado"] = resumo_loja["Entradas"] - resumo_loja["Saídas"]
        resumo_loja = resumo_loja.sort_values("Resultado", ascending=False)
        try:
            st.dataframe(resumo_loja.style.format("R$ {:,.2f}"), use_container_width=True)
        except Exception:
            st.dataframe(resumo_loja, use_container_width=True)
    else: st.info("Sincronize a API para gerar o comparativo por loja.")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">📅 Projeção do Caixa</div>', unsafe_allow_html=True)
    if not df_of_exec.empty:
        proj = df_of_exec[["Data", "Total_Entradas", "Total_Saidas", "Saldo"]].copy()
        proj.columns = ["Data", "Entradas", "Saídas", "Saldo"]
        try:
            st.dataframe(proj.tail(10).style.format({"Entradas": "R$ {:,.2f}", "Saídas": "R$ {:,.2f}", "Saldo": "R$ {:,.2f}"}), use_container_width=True, hide_index=True)
        except Exception:
            st.dataframe(proj.tail(10), use_container_width=True, hide_index=True)
    else: st.info("A projeção diária utiliza os dados do export oficial do Fluxo de Caixa F360.")

with tabs[1]:
    st.subheader("Matriz Diária — Valores 100% Espelhados do F360")
    if oficial:
        df_cards = oficial["df"].copy()
        if isinstance(date_range, tuple) and len(date_range) == 2: df_cards = df_cards[(df_cards["Data"].dt.date >= date_range[0]) & (df_cards["Data"].dt.date <= date_range[1])]

        if not df_api.empty:
            df_cards_api = df_kpi.copy()
            desp_cards = df_cards_api[(df_cards_api["Tipo_Movimento"] == "DESPESA") & (df_cards_api["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
            prev_cards = desp_cards["Valor"].sum() if not desp_cards.empty else 0.0
            liq_cards = desp_cards[desp_cards["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not desp_cards.empty else 0.0
            aberto_cards = desp_cards[desp_cards["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not desp_cards.empty else max(prev_cards - liq_cards, 0)
            st.markdown("#### Lançamentos do período")
            render_movement_cards(prev_cards, liq_cards, aberto_cards, "Despesas", df_detail=desp_cards, state_prefix="fluxo_despesas")
        else:
            saidas = df_cards["Total_Saidas"].sum() if not df_cards.empty else 0.0
            st.markdown("#### Movimentação oficial do caixa")
            render_movement_cards(saidas, saidas, 0.0, "Saídas", df_detail=None, state_prefix="fluxo_oficial")
            st.caption("Para separar previsto, liquidado e em aberto, sincronize a API F360.")
    else: st.info("👈 Anexe o 'Fluxo de Caixa.xlsx' para habilitar os indicadores do fluxo diário.")

    if oficial and not df_cards.empty:
        dias_of = sorted(df_cards["Dia"].unique().tolist())
        linhas_of = [
            {"Linha de Extrato": "1. (+) Cartões", **dict(zip(df_cards["Dia"], df_cards.get("Cartoes", 0)))},
            {"Linha de Extrato": "2. (+) PIX / Boleto / Transferências", **dict(zip(df_cards["Dia"], df_cards.get("Boleto", 0) + df_cards.get("Outros_Recebimentos", 0)))},
            {"Linha de Extrato": "3. (+) Orçamento (Entrada Prevista)", **dict(zip(df_cards["Dia"], df_cards.get("Orcamento_Entrada", 0)))},
            {"Linha de Extrato": "4. (=) Total de Entradas", **dict(zip(df_cards["Dia"], df_cards.get("Total_Entradas", 0)))},
            {"Linha de Extrato": "5. (-) Total de Saídas (Real + Orçamento)", **dict(zip(df_cards["Dia"], df_cards.get("Total_Saidas", 0)))},
            {"Linha de Extrato": "6. 🏦 SALDO FINAL BANCÁRIO", **dict(zip(df_cards["Dia"], df_cards.get("Saldo", 0)))},
        ]
        df_display = pd.DataFrame(linhas_of)[["Linha de Extrato"] + dias_of]
        try:
            st.dataframe(df_display.style.apply(highlight_saldo, axis=1).format({d: "R$ {:,.2f}" for d in dias_of}), use_container_width=True, hide_index=True)
        except Exception:
            st.dataframe(df_display, use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("DRE de Caixa — Visão Gerencial por Plano de Contas")
    if not df_api.empty:
        st.markdown("#### Lançamentos da DRE")
        rec_prev_dre = df_rec_kpi["Valor"].sum() if not df_rec_kpi.empty else 0.0
        rec_liq_dre = df_rec_kpi[df_rec_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not df_rec_kpi.empty else 0.0
        rec_aberto_dre = df_rec_kpi[df_rec_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not df_rec_kpi.empty else max(rec_prev_dre - rec_liq_dre, 0)
        desp_prev_dre = df_desp_kpi["Valor"].sum() if not df_desp_kpi.empty else 0.0
        desp_liq_dre = df_desp_kpi[df_desp_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not df_desp_kpi.empty else 0.0
        desp_aberto_dre = df_desp_kpi[df_desp_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not df_desp_kpi.empty else max(desp_prev_dre - desp_liq_dre, 0)

        render_movement_cards(rec_prev_dre, rec_liq_dre, rec_aberto_dre, "Receitas", df_detail=df_rec_kpi, state_prefix="dre_receitas")
        st.markdown("<br>", unsafe_allow_html=True)
        render_movement_cards(desp_prev_dre, desp_liq_dre, desp_aberto_dre, "Despesas", df_detail=df_desp_kpi, state_prefix="dre_despesas")
        st.caption("Os cards usam os lançamentos da API F360 respeitando a conta/loja e o período selecionados.")
        st.markdown("<br>", unsafe_allow_html=True)

        dre_list = [{"Categoria CFO": "0. RECEITAS DE VENDAS", "Previsto (R$)": f"R$ {tot_rec_prev:,.2f}", "Realizado (R$)": f"R$ {tot_rec_real:,.2f}", "Variação (R$)": f"R$ {tot_rec_real - tot_rec_prev:,.2f}"}]
        cats = ["1. FORNECEDORES / MERCADORIAS (CMV)", "2. IMPOSTOS SOBRE VENDAS", "3. DESPESAS DE OCUPAÇÃO", "4. FOLHA DE PAGAMENTO & ENCARGOS", "5. DESPESAS OPERACIONAIS & VENDAS", "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL", "7. DESPESAS DE SÓCIOS"]
        tot_saidas_prev, tot_saidas_real = 0.0, 0.0

        for c in cats:
            p = df_desp_kpi[df_desp_kpi["Categoria_CFO"] == c]["Valor"].sum() if not df_desp_kpi.empty else 0.0
            r = df_desp_kpi[(df_desp_kpi["Categoria_CFO"] == c) & (df_desp_kpi["Status_Clean"] == "REALIZADO")]["Valor"].sum() if not df_desp_kpi.empty else 0.0
            tot_saidas_prev += p
            tot_saidas_real += r
            dre_list.append({"Categoria CFO": f"   (-) {c}", "Previsto (R$)": f"R$ {p:,.2f}", "Realizado (R$)": f"R$ {r:,.2f}", "Variação (R$)": f"R$ {r - p:,.2f}"})

        dre_list.append({"Categoria CFO": "8. TOTAL SAÍDAS", "Previsto (R$)": f"R$ {tot_saidas_prev:,.2f}", "Realizado (R$)": f"R$ {tot_saidas_real:,.2f}", "Variação (R$)": f"R$ {tot_saidas_real - tot_saidas_prev:,.2f}"})
        res_prev, res_real = tot_rec_prev - tot_saidas_prev, tot_rec_real - tot_saidas_real
        dre_list.append({"Categoria CFO": "(=) EBITDA", "Previsto (R$)": f"R$ {res_prev:,.2f}", "Realizado (R$)": f"R$ {res_real:,.2f}", "Variação (R$)": f"R$ {res_real - res_prev:,.2f}"})
        try:
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
        except Exception:
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True)
    else: st.warning("Sincronize a API no menu lateral para visualizar o DRE.")

with tabs[3]:
    st.subheader("Comparativo Por Loja — Vendas e Despesas")
    if not df_api.empty:
        df_filtered_loja = df_kpi.copy()
        tem_loja = "Empresa_Loja" in df_filtered_loja.columns and df_filtered_loja["Empresa_Loja"].replace("", np.nan).notna().any()
        dimensao = "Empresa_Loja" if tem_loja else "Empresa"
        if not tem_loja: st.warning("Sem dado de loja de origem nos lançamentos carregados. Mostrando por conta bancária de liquidação.")

        df_desp_loja = df_filtered_loja[(df_filtered_loja["Tipo_Movimento"] == "DESPESA") & (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
        df_rec_loja = df_filtered_loja[(df_filtered_loja["Tipo_Movimento"] == "RECEITA") & (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]

        if not df_desp_loja.empty:
            st.markdown("**Despesas por categoria**")
            pivot_desp = df_desp_loja.pivot_table(index="Categoria_CFO", columns=dimensao, values="Valor", aggfunc="sum", fill_value=0)
            try:
                st.dataframe(pivot_desp.style.format("R$ {:,.2f}"), use_container_width=True)
            except Exception:
                st.dataframe(pivot_desp, use_container_width=True)

        if not df_rec_loja.empty:
            st.markdown("**Resumo Operacional (Receita x Despesa)**")
            resumo_rec = df_rec_loja.groupby(dimensao)["Valor"].sum().to_frame("Receita de Vendas")
            resumo_desp = df_desp_loja.groupby(dimensao)["Valor"].sum().to_frame("Despesas") if not df_desp_loja.empty else pd.DataFrame()
            resumo = resumo_rec.join(resumo_desp, how="outer").fillna(0)
            resumo["Resultado (Receita - Despesa)"] = resumo["Receita de Vendas"] - resumo.get("Despesas", 0)
            try:
                st.dataframe(resumo.style.format("R$ {:,.2f}"), use_container_width=True)
            except Exception:
                st.dataframe(resumo, use_container_width=True)

        if df_desp_loja.empty and df_rec_loja.empty: st.info("Nenhum lançamento com loja identificada para comparar no período selecionado.")
    else: st.warning("Sincronize a API para gerar o comparativo entre as lojas.")