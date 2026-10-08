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

# Tenta importar o processar CSV do navegador caso esteja usando a versão mais recente do f360_api.py
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
    .stApp {
        background: #0B0F14;
        color: #F4F7FA;
    }
    [data-testid="stHeader"] {
        background: rgba(11,15,20,0.96);
    }
    [data-testid="stSidebar"] {
        background: #151A21;
        border-right: 1px solid #252C35;
    }
    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1rem;
    }

    /* ---------- TIPOGRAFIA ---------- */
    .hero-title {
        font-size: 30px;
        line-height: 1.05;
        font-weight: 800;
        letter-spacing: -0.8px;
        margin-bottom: 2px;
        color: #F8FAFC;
    }
    .hero-subtitle {
        color: #8F9AA8;
        font-size: 14px;
        margin-bottom: 18px;
    }
    .section-title {
        font-size: 18px;
        font-weight: 750;
        color: #F4F7FA;
        margin: 4px 0 10px 0;
    }
    .muted {
        color: #8994A3;
        font-size: 12px;
    }

    /* ---------- STATUS ---------- */
    .status-pill {
        display: inline-flex;
        align-items: center;
        gap: 7px;
        padding: 7px 12px;
        border-radius: 999px;
        background: #123022;
        color: #58D68D;
        border: 1px solid #20583C;
        font-size: 12px;
        font-weight: 700;
    }
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #35D07F;
        display: inline-block;
        box-shadow: 0 0 10px rgba(53,208,127,.45);
    }

    /* ---------- CARDS ---------- */
    .kpi-card {
        background: linear-gradient(145deg, #151B23 0%, #10151C 100%);
        border: 1px solid #28313C;
        border-radius: 12px;
        padding: 15px 16px 14px 16px;
        min-height: 112px;
        box-shadow: 0 8px 24px rgba(0,0,0,.12);
    }
    .kpi-label {
        color: #8F9AA8;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: .4px;
        text-transform: uppercase;
        margin-bottom: 7px;
    }
    .kpi-value {
        color: #F8FAFC;
        font-size: 24px;
        line-height: 1.05;
        font-weight: 800;
        letter-spacing: -.5px;
    }
    .kpi-green { color: #45D483; }
    .kpi-red { color: #FF6262; }
    .kpi-yellow { color: #F4C95D; }
    .kpi-blue { color: #69B7FF; }
    .kpi-foot {
        color: #697585;
        font-size: 11px;
        margin-top: 8px;
    }

    /* ---------- EXECUTIVE PANELS ---------- */
    .panel {
        background: #11161D;
        border: 1px solid #252D37;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 14px;
    }
    .panel-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 10px;
    }
    .panel-title {
        font-size: 15px;
        font-weight: 750;
        color: #F4F7FA;
    }

    /* ---------- ALERTS ---------- */
    .alert-good {
        background: #10271D;
        border: 1px solid #24553C;
        color: #67E39A;
        border-radius: 10px;
        padding: 11px 13px;
        font-size: 13px;
        font-weight: 650;
    }
    .alert-warn {
        background: #2A2413;
        border: 1px solid #67531D;
        color: #F3D36A;
        border-radius: 10px;
        padding: 11px 13px;
        font-size: 13px;
        font-weight: 650;
    }
    .alert-danger {
        background: #2A1719;
        border: 1px solid #663034;
        color: #FF8585;
        border-radius: 10px;
        padding: 11px 13px;
        font-size: 13px;
        font-weight: 650;
    }

    /* ---------- TABLES ---------- */
    [data-testid="stDataFrame"] {
        border-radius: 10px;
        overflow: hidden;
    }

    /* ---------- BUTTONS ---------- */
    .stButton > button {
        border-radius: 8px;
        border: 1px solid #343D49;
        background: #171D25;
        color: #E9EEF3;
        font-weight: 650;
    }
    .stButton > button:hover {
        border-color: #00875A;
        color: #5CE39A;
    }

    /* ---------- DIVIDER ---------- */
    hr {
        border-color: #252D37 !important;
    }
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
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']):
        return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    if any(k in p for k in ['SÓCIO', 'SOCIO', 'LUCRO', 'DISTRIBUIÇÃO', 'DIVIDENDO', 'PRÓ-LABORE', 'PRO-LABORE']):
        return "7. DESPESAS DE SÓCIOS"
    if any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'LEITE', 'INSUMOS', 'BOBINAS', 'FRUTAS']):
        return "1. FORNECEDORES / MERCADORIAS (CMV)"
    if any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS']):
        return "2. IMPOSTOS SOBRE VENDAS"
    if any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'ENERGIA', 'ÁGUA', 'IPTU', 'LIMPEZA']):
        return "3. DESPESAS DE OCUPAÇÃO"
    if any(k in p for k in ['SALÁRIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'RESCISÃO', 'FUNCIONÁRIOS']):
        return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    if any(k in p for k in ['EMPRÉSTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFAS']):
        return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    return "5. DESPESAS OPERACIONAIS & VENDAS"

def categorizar_receita(row):
    p = str(row.get("Plano de Contas") or "").upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']):
        return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    return "0. RECEITAS DE VENDAS"

@st.cache_data(ttl=3600)
def carregar_fluxo_oficial(_arquivos):
    resultado = {}
    for arq in _arquivos:
        df_dias, saldo_ini, contas = processar_fluxo_de_caixa_oficial(arq)
        chave = contas[0] if len(contas) == 1 else "Ver Todas as Contas"
        resultado[chave] = {
            "df": df_dias,
            "saldo_inicial": saldo_ini,
            "contas": contas
        }
    return resultado

def highlight_saldo(row):
    styles = [''] * len(row)
    if row["Linha de Extrato"] == "6. 🏦 SALDO FINAL BANCÁRIO":
        for i, val in enumerate(row):
            if isinstance(val, (int, float)):
                if val < 0:
                    styles[i] = 'color: #ff6262; font-weight: bold;'
                elif val > 0:
                    styles[i] = 'color: #45d483; font-weight: bold;'
    return styles

def brl(v):
    return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def render_movement_cards(previsto, liquidado, aberto, titulo="Lançamentos", df_detalhes=None, state_key="movimentos"):
    """Cards com botões para abrir os lançamentos correspondentes."""
    c1, c2, c3 = st.columns(3)

    botoes = [
        (c1, "PREVISTO", previsto, "todos"),
        (c2, "LIQUIDADO", liquidado, "realizado"),
        (c3, "EM ABERTO", aberto, "pendente"),
    ]

    for col, rotulo, valor, filtro in botoes:
        with col:
            classe = "kpi-blue" if rotulo == "PREVISTO" else ("kpi-green" if rotulo == "LIQUIDADO" else ("kpi-green" if valor <= 0 else "kpi-yellow"))
            st.markdown(f"""
            <div class="kpi-card">
                <div class="kpi-label">{'📊' if rotulo == 'PREVISTO' else ('🟢' if rotulo == 'LIQUIDADO' else '🟡')} {titulo} · {rotulo}</div>
                <div class="kpi-value {classe}">{brl(valor)}</div>
                <div class="kpi-foot">Clique abaixo para ver os lançamentos</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"🔎 Ver lançamentos", key=f"{state_key}_{filtro}", use_container_width=True):
                st.session_state["show_kpi_data"] = {
                    "key": state_key,
                    "titulo": titulo,
                    "filtro": filtro,
                    "df": df_detalhes.copy() if df_detalhes is not None else pd.DataFrame(),
                }


def mostrar_detalhes_card():
    """Exibe a lista de lançamentos do card selecionado."""
    detalhe = st.session_state.get("show_kpi_data")
    if not detalhe:
        return

    df = detalhe.get("df", pd.DataFrame()).copy()
    filtro = detalhe.get("filtro")

    if not df.empty and filtro != "todos":
        df = df[df["Status_Clean"] == ("REALIZADO" if filtro == "realizado" else "PENDENTE")].copy()

    st.markdown("---")
    col_t, col_b = st.columns([5, 1])
    with col_t:
        st.markdown(f"### 📋 {detalhe.get('titulo', 'Lançamentos')} — {filtro.upper()}")
    with col_b:
        if st.button("✖ Fechar", key=f"fechar_{detalhe.get('key', 'movimentos')}", use_container_width=True):
            st.session_state["show_kpi_data"] = None
            st.rerun()

    if df.empty:
        st.info("Nenhum lançamento encontrado para este card no período/conta selecionados.")
        return

    colunas_preferidas = [
        "Vencimento_dt", "Empresa", "Empresa_Loja", "Categoria_CFO",
        "Status_F360", "Status_Clean", "Valor", "Numero_Titulo",
        "Fornecedor", "Cliente", "Descricao"
    ]
    cols = [c for c in colunas_preferidas if c in df.columns]
    if not cols:
        cols = list(df.columns)

    exib = df[cols].copy()
    if "Vencimento_dt" in exib.columns:
        exib["Vencimento_dt"] = pd.to_datetime(exib["Vencimento_dt"], errors="coerce").dt.strftime("%d/%m/%Y")
    if "Valor" in exib.columns:
        exib["Valor"] = pd.to_numeric(exib["Valor"], errors="coerce").fillna(0)

    st.caption(f"{len(exib):,} lançamento(s) encontrado(s) • Total: {brl(exib['Valor'].sum()) if 'Valor' in exib.columns else '—'}")
    if "Valor" in exib.columns:
        st.dataframe(exib.style.format({"Valor": "R$ {:,.2f}"}), use_container_width=True, hide_index=True)
    else:
        st.dataframe(exib, use_container_width=True, hide_index=True)

# ============================================================
# ESTADO
# ============================================================
if 'fluxo_oficial_cache' not in st.session_state:
    st.session_state.fluxo_oficial_cache = {}
if 'show_kpi_data' not in st.session_state:
    st.session_state.show_kpi_data = None

# ============================================================
# SIDEBAR
# ============================================================
with st.sidebar:
    st.markdown("## 🍦 BORELLI")
    st.caption("Controladoria · Fluxo de Caixa")
    st.divider()

    st.markdown("### ⚡ Sincronização F360")
    if "jwt" not in st.session_state:
        st.session_state.jwt = autenticar_f360(F360_TOKEN)

    periodo_api = st.date_input(
        "Período DRE (API)",
        (date(2026, 9, 1), date(2026, 10, 31)),
        format="DD/MM/YYYY"
    )

    if st.button("🚀 Sincronizar API", use_container_width=True) and len(periodo_api) == 2:
        with st.spinner("Sincronizando dados do F360..."):
            d_ini, d_fim = periodo_api[0], periodo_api[1]
            log_desp, log_rec = [], []

            df_desp = buscar_parcelas_f360(
                st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Despesa", log=log_desp
            )
            if not df_desp.empty:
                df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(categorizar_plano_contas)
            st.session_state.df_api_desp = df_desp

            df_rec = buscar_parcelas_f360(
                st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Receita", log=log_rec
            )
            if not df_rec.empty:
                df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
                df_rec["Tipo_Movimento"] = "RECEITA"
            st.session_state.df_api_rec = df_rec
            st.session_state.log_desp = log_desp
            st.session_state.log_rec = log_rec
            st.success(f"🟢 API F360 sincronizada! Despesas: {len(df_desp):,} linhas | Receitas: {len(df_rec):,} linhas")

            with st.expander("🔎 LOG / DIAGNÓSTICO DA API F360"):
                st.caption(f"Período consultado: {d_ini.strftime('%d/%m/%Y')} até {d_fim.strftime('%d/%m/%Y')}")
                st.markdown("**DESPESAS**")
                st.code("\n".join(log_desp) if log_desp else "Sem log.")
                st.markdown("**RECEITAS**")
                st.code("\n".join(log_rec) if log_rec else "Sem log.")

    st.divider()
    st.markdown("### 🏦 Dados oficiais do caixa")
    file_fluxo_oficial = st.file_uploader(
        "F360 > Fluxo de Caixa > Exportar",
        type=["xlsx"],
        accept_multiple_files=True
    )

    if HAS_DOM_PROCESSOR:
        file_tabela_csv = st.file_uploader(
            "CSV Automático (opcional)",
            type=["csv"],
            key="tabela_csv"
        )
    else:
        file_tabela_csv = None

    st.divider()
    st.caption("🔐 A fonte oficial do saldo bancário continua sendo o export do Fluxo de Caixa do F360.")

# ============================================================
# CARREGA ARQUIVOS
# ============================================================
if file_fluxo_oficial:
    st.session_state.fluxo_oficial_cache.update(
        carregar_fluxo_oficial(file_fluxo_oficial)
    )

if file_tabela_csv is not None and HAS_DOM_PROCESSOR:
    df_dom, saldo_ini_dom = processar_tabela_fluxo_dom(file_tabela_csv)
    st.session_state.fluxo_oficial_cache["CSV (via navegador)"] = {
        "df": df_dom,
        "saldo_inicial": saldo_ini_dom,
        "contas": []
    }

fluxo_oficial = st.session_state.fluxo_oficial_cache

_lista_dfs = [
    d for d in [
        st.session_state.get("df_api_desp"),
        st.session_state.get("df_api_rec")
    ]
    if d is not None and not d.empty
]
df_api = pd.concat(_lista_dfs, ignore_index=True) if _lista_dfs else pd.DataFrame()

# ============================================================
# CABEÇALHO
# ============================================================
st.markdown("""
<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px;">
    <div>
        <div class="hero-title">🍦 BORELLI</div>
        <div class="hero-subtitle">Fluxo de Caixa · Controladoria</div>
    </div>
    <div class="status-pill">
        <span class="status-dot"></span>
        F360 conectado
    </div>
</div>
""", unsafe_allow_html=True)

# ============================================================
# FILTROS
# ============================================================
f1, f2 = st.columns([2.2, 1])

with f1:
    opcoes_conta = [
        "Ver Todas as Contas",
        "17 Pantanal Itaú",
        "51 Estação Itaú",
        "61 Itaú Goiabeiras",
        "52 RT",
        "36 MJL"
    ]
    if "CSV (via navegador)" in fluxo_oficial:
        opcoes_conta.append("CSV (via navegador)")
    conta_selecionada = st.radio(
        "Conta / Loja",
        opcoes_conta,
        horizontal=True
    )

with f2:
    min_d, max_d = date(2026, 9, 1), date(2026, 10, 31)

    if not df_api.empty:
        min_d = df_api['Vencimento_dt'].min().date()
        max_d = df_api['Vencimento_dt'].max().date()

    for dados in fluxo_oficial.values():
        if not dados["df"].empty:
            min_d = min(min_d, dados["df"]["Data"].min().date())
            max_d = max(max_d, dados["df"]["Data"].max().date())

    date_range = st.date_input(
        "Período",
        value=(min_d, max_d),
        format="DD/MM/YYYY"
    )

# ============================================================
# FILTRO API
# ============================================================
df_kpi = df_api.copy()

if not df_kpi.empty:
    if conta_selecionada not in ("Ver Todas as Contas", "CSV (via navegador)"):
        df_kpi = df_kpi[df_kpi['Empresa'] == conta_selecionada]

    if isinstance(date_range, tuple) and len(date_range) == 2:
        df_kpi = df_kpi[
            (df_kpi['Vencimento_dt'].dt.date >= date_range[0]) &
            (df_kpi['Vencimento_dt'].dt.date <= date_range[1])
        ]

df_rec_kpi = (
    df_kpi[
        (df_kpi['Tipo_Movimento'] == 'RECEITA') &
        (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")
    ]
    if not df_kpi.empty else pd.DataFrame()
)

df_desp_kpi = (
    df_kpi[
        (df_kpi['Tipo_Movimento'] == 'DESPESA') &
        (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")
    ]
    if not df_kpi.empty else pd.DataFrame()
)

tot_rec_prev = df_rec_kpi['Valor'].sum() if not df_rec_kpi.empty else 0.0
tot_rec_real = (
    df_rec_kpi[df_rec_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum()
    if not df_rec_kpi.empty else 0.0
)

tot_prev = df_desp_kpi['Valor'].sum() if not df_desp_kpi.empty else 0.0
tot_real = (
    df_desp_kpi[df_desp_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum()
    if not df_desp_kpi.empty else 0.0
)
tot_pend = (
    df_desp_kpi[df_desp_kpi['Status_Clean'] == 'PENDENTE']['Valor'].sum()
    if not df_desp_kpi.empty else 0.0
)

# ============================================================
# DADOS OFICIAIS DO CAIXA PARA A VISÃO EXECUTIVA
# ============================================================
oficial = (
    fluxo_oficial.get(conta_selecionada)
    or fluxo_oficial.get("Ver Todas as Contas")
    or fluxo_oficial.get("CSV (via navegador)")
)
if not oficial and len(fluxo_oficial) == 1:
    oficial = list(fluxo_oficial.values())[0]

df_of_exec = pd.DataFrame()
saldo_inicial_exec = None
saldo_final_exec = None
entradas_oficiais = None
saidas_oficiais = None

if oficial:
    df_of_exec = oficial["df"].copy()
    saldo_inicial_exec = oficial.get("saldo_inicial")

    if isinstance(date_range, tuple) and len(date_range) == 2:
        df_of_exec = df_of_exec[
            (df_of_exec["Data"].dt.date >= date_range[0]) &
            (df_of_exec["Data"].dt.date <= date_range[1])
        ]

    if not df_of_exec.empty:
        entradas_oficiais = df_of_exec["Total_Entradas"].sum()
        saidas_oficiais = df_of_exec["Total_Saidas"].sum()
        saldo_final_exec = df_of_exec.iloc[-1]["Saldo"]

# Para a visão executiva: quando o export oficial estiver disponível,
# usa-se o caixa oficial; caso contrário, o painel continua funcionando
# com a API.
entradas_exec = entradas_oficiais if entradas_oficiais is not None else tot_rec_prev
saidas_exec = saidas_oficiais if saidas_oficiais is not None else tot_prev
resultado_exec = entradas_exec - saidas_exec

# ============================================================
# PRIMEIRA ABA — VISÃO EXECUTIVA
# ============================================================
tabs = st.tabs([
    "📊 Visão Executiva",
    "📅 Fluxo Diário",
    "📋 DRE de Caixa",
    "🏪 Comparativo Por Loja"
])

with tabs[0]:
    st.markdown(
        '<div class="section-title">Resumo financeiro do período</div>',
        unsafe_allow_html=True
    )

    c1, c2, c3, c4, c5 = st.columns(5)

    with c1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">💰 Entradas</div>
            <div class="kpi-value kpi-green">{brl(entradas_exec)}</div>
            <div class="kpi-foot">Caixa oficial quando disponível</div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">🔴 Saídas</div>
            <div class="kpi-value kpi-red">{brl(saidas_exec)}</div>
            <div class="kpi-foot">Realizadas + previstas do caixa</div>
        </div>
        """, unsafe_allow_html=True)

    resultado_class = "kpi-green" if resultado_exec >= 0 else "kpi-red"
    with c3:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">📈 Resultado do Caixa</div>
            <div class="kpi-value {resultado_class}">{brl(resultado_exec)}</div>
            <div class="kpi-foot">Entradas − saídas</div>
        </div>
        """, unsafe_allow_html=True)

    with c4:
        saldo_text = brl(saldo_final_exec) if saldo_final_exec is not None else "—"
        saldo_class = "kpi-green" if (saldo_final_exec or 0) >= 0 else "kpi-red"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">🏦 Saldo Final</div>
            <div class="kpi-value {saldo_class}">{saldo_text}</div>
            <div class="kpi-foot">Saldo do export oficial F360</div>
        </div>
        """, unsafe_allow_html=True)

    with c5:
        aberto_class = "kpi-green" if tot_pend == 0 else "kpi-yellow"
        aberto_msg = "Nenhuma despesa pendente" if tot_pend == 0 else "Despesas ainda em aberto"
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-label">⚠️ Em Aberto</div>
            <div class="kpi-value {aberto_class}">{brl(tot_pend)}</div>
            <div class="kpi-foot">{aberto_msg}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # STATUS
    if saldo_final_exec is not None and saldo_final_exec < 0:
        st.markdown(
            '<div class="alert-danger">🔴 Atenção: o saldo final do período está negativo.</div>',
            unsafe_allow_html=True
        )
    elif tot_pend > 0:
        st.markdown(
            f'<div class="alert-warn">🟡 Atenção: existem {brl(tot_pend)} em despesas pendentes na API.</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="alert-good">🟢 Caixa sem despesas pendentes identificadas na API para o período filtrado.</div>',
            unsafe_allow_html=True
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Legenda operacional
    st.markdown("""
    <div class="panel" style="padding:10px 14px;">
        <span class="muted">
            <b style="color:#69B7FF;">PREVISTO</b> = lançamentos previstos ·
            <b style="color:#45D483;">LIQUIDADO</b> = realizado ·
            <b style="color:#F4C95D;">EM ABERTO</b> = ainda pendente
        </span>
    </div>
    """, unsafe_allow_html=True)

    # GRÁFICO ENTRADAS X SAÍDAS
    g1, g2 = st.columns([1.75, 1])

    with g1:
        st.markdown("""
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">Fluxo de Caixa · Entradas × Saídas</div>
                <div class="muted">por dia</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if not df_of_exec.empty:
            chart_df = df_of_exec[["Data", "Total_Entradas", "Total_Saidas"]].copy()
            chart_df = chart_df.set_index("Data")
            chart_df.columns = ["Entradas", "Saídas"]
            st.line_chart(chart_df, height=280)
        else:
            st.info("Anexe o export 'Fluxo de Caixa.xlsx' para visualizar o fluxo diário oficial.")

    with g2:
        st.markdown("""
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">Composição das Saídas</div>
                <div class="muted">API F360</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if not df_desp_kpi.empty:
            comp = (
                df_desp_kpi.groupby("Categoria_CFO")["Valor"]
                .sum()
                .sort_values(ascending=True)
            )
            comp.index = [
                str(x).replace("1. ", "").replace("2. ", "").replace("3. ", "")
                .replace("4. ", "").replace("5. ", "").replace("6. ", "")
                .replace("7. ", "")
                for x in comp.index
            ]
            st.bar_chart(comp, height=280)
        else:
            st.info("Sincronize a API para visualizar a composição das despesas.")

    st.markdown("<br>", unsafe_allow_html=True)

    # RESULTADO POR LOJA
    st.markdown(
        '<div class="section-title">🏪 Resultado por Loja</div>',
        unsafe_allow_html=True
    )

    if not df_api.empty:
        df_loja_exec = df_api.copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_loja_exec = df_loja_exec[
                (df_loja_exec["Vencimento_dt"].dt.date >= date_range[0]) &
                (df_loja_exec["Vencimento_dt"].dt.date <= date_range[1])
            ]

        dimensao_exec = "Empresa_Loja"
        if dimensao_exec not in df_loja_exec.columns or not df_loja_exec[dimensao_exec].replace("", np.nan).notna().any():
            dimensao_exec = "Empresa"

        rec_loja = df_loja_exec[
            (df_loja_exec["Tipo_Movimento"] == "RECEITA") &
            (df_loja_exec["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")
        ].groupby(dimensao_exec)["Valor"].sum()

        desp_loja = df_loja_exec[
            (df_loja_exec["Tipo_Movimento"] == "DESPESA") &
            (df_loja_exec["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")
        ].groupby(dimensao_exec)["Valor"].sum()

        resumo_loja = pd.concat(
            [rec_loja.rename("Entradas"), desp_loja.rename("Saídas")],
            axis=1
        ).fillna(0)
        resumo_loja["Resultado"] = resumo_loja["Entradas"] - resumo_loja["Saídas"]
        resumo_loja = resumo_loja.sort_values("Resultado", ascending=False)

        st.dataframe(
            resumo_loja.style.format("R$ {:,.2f}"),
            use_container_width=True,
            hide_index=False
        )
    else:
        st.info("Sincronize a API para gerar o comparativo por loja.")

    # PROJEÇÃO SIMPLES COM BASE NO CAIXA JÁ CARREGADO
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown(
        '<div class="section-title">📅 Projeção do Caixa</div>',
        unsafe_allow_html=True
    )

    if not df_of_exec.empty:
        proj = df_of_exec[["Data", "Total_Entradas", "Total_Saidas", "Saldo"]].copy()
        proj.columns = ["Data", "Entradas", "Saídas", "Saldo"]
        proj = proj.tail(10).copy()

        st.dataframe(
            proj.style.format({
                "Entradas": "R$ {:,.2f}",
                "Saídas": "R$ {:,.2f}",
                "Saldo": "R$ {:,.2f}"
            }),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("A projeção diária utiliza os dados do export oficial do Fluxo de Caixa F360.")

# ============================================================
# SEGUNDA ABA — FLUXO DIÁRIO (ORIGINAL)
# ============================================================
with tabs[1]:
    st.subheader("Matriz Diária — Valores 100% Espelhados do F360")

    # Cards operacionais: previsto, liquidado e em aberto
    oficial = (
        fluxo_oficial.get(conta_selecionada)
        or fluxo_oficial.get("Ver Todas as Contas")
        or fluxo_oficial.get("CSV (via navegador)")
    )
    if not oficial and len(fluxo_oficial) == 1:
        oficial = list(fluxo_oficial.values())[0]

    if oficial:
        df_cards = oficial["df"].copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_cards = df_cards[
                (df_cards["Data"].dt.date >= date_range[0]) &
                (df_cards["Data"].dt.date <= date_range[1])
            ]

        # O Excel oficial traz Total_Entradas e Total_Saidas.
        # Para os cards de lançamentos, cruzamos com a API quando disponível:
        # previsto = API; liquidado = REALIZADO; aberto = PENDENTE.
        if not df_api.empty:
            # IMPORTANTE: usar exatamente o mesmo df_desp_kpi da Visão Executiva/DRE.
            # Assim o Fluxo Diário não aplica uma segunda filtragem diferente.
            desp_cards = df_desp_kpi.copy()

            prev_cards = desp_cards["Valor"].sum() if not desp_cards.empty else 0.0
            liq_cards = desp_cards.loc[desp_cards["Status_Clean"] == "REALIZADO", "Valor"].sum() if not desp_cards.empty else 0.0
            aberto_cards = desp_cards.loc[desp_cards["Status_Clean"] == "PENDENTE", "Valor"].sum() if not desp_cards.empty else 0.0

            st.markdown("#### Lançamentos do período")
            render_movement_cards(
                prev_cards, liq_cards, aberto_cards, "Despesas",
                df_detalhes=desp_cards, state_key="fluxo_despesas"
            )
            mostrar_detalhes_card()

            st.caption(
                "Previsto = todos os lançamentos de despesa; "
                "Liquidado = status REALIZADO; Em aberto = status PENDENTE."
            )
            st.markdown("<br>", unsafe_allow_html=True)
        else:
            # Fallback visual quando somente o Excel oficial estiver carregado.
            entradas = df_cards["Total_Entradas"].sum() if not df_cards.empty else 0.0
            saidas = df_cards["Total_Saidas"].sum() if not df_cards.empty else 0.0
            st.markdown("#### Movimentação oficial do caixa")
            render_movement_cards(saidas, saidas, 0.0, "Saídas")
            st.caption("Para separar previsto, liquidado e em aberto, sincronize a API F360.")
            st.markdown("<br>", unsafe_allow_html=True)
    else:
        st.info("👈 Anexe o 'Fluxo de Caixa.xlsx' para habilitar os indicadores do fluxo diário.")

    if oficial:
        df_of = oficial["df"].copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_of = df_of[
                (df_of["Data"].dt.date >= date_range[0]) &
                (df_of["Data"].dt.date <= date_range[1])
            ]

        if not df_of.empty:
            dias_of = sorted(df_of["Dia"].unique().tolist())

            linhas_of = [
                {"Linha de Extrato": "1. (+) Cartões", **dict(zip(df_of["Dia"], df_of.get("Cartoes", 0)))},
                {"Linha de Extrato": "2. (+) PIX / Boleto / Transferências", **dict(zip(df_of["Dia"], df_of.get("Boleto", 0) + df_of.get("Outros_Recebimentos", 0)))},
                {"Linha de Extrato": "3. (+) Orçamento (Entrada Prevista)", **dict(zip(df_of["Dia"], df_of.get("Orcamento_Entrada", 0)))},
                {"Linha de Extrato": "4. (=) Total de Entradas", **dict(zip(df_of["Dia"], df_of.get("Total_Entradas", 0)))},
                {"Linha de Extrato": "5. (-) Total de Saídas (Real + Orçamento)", **dict(zip(df_of["Dia"], df_of.get("Total_Saidas", 0)))},
                {"Linha de Extrato": "6. 🏦 SALDO FINAL BANCÁRIO", **dict(zip(df_of["Dia"], df_of.get("Saldo", 0)))},
            ]

            df_display = pd.DataFrame(linhas_of)[["Linha de Extrato"] + dias_of]
            st.dataframe(
                df_display.style
                .apply(highlight_saldo, axis=1)
                .format({d: "R$ {:,.2f}" for d in dias_of}),
                use_container_width=True,
                hide_index=True
            )
        else:
            st.warning("Sem dados para o período filtrado no Excel.")
    else:
        st.info("👈 Anexe o 'Fluxo de Caixa.xlsx' na barra lateral para gerar esta aba com os saldos bancários corretos.")

# ============================================================
# TERCEIRA ABA — DRE DE CAIXA (ORIGINAL)
# ============================================================
with tabs[2]:
    st.subheader("DRE de Caixa — Visão Gerencial por Plano de Contas")

    if not df_api.empty:
        # Cards da DRE: mostram claramente o volume lançado e o status.
        st.markdown("#### Lançamentos da DRE")

        rec_prev_dre = (
            df_rec_kpi["Valor"].sum()
            if not df_rec_kpi.empty else 0.0
        )
        rec_liq_dre = (
            df_rec_kpi[df_rec_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum()
            if not df_rec_kpi.empty else 0.0
        )
        rec_aberto_dre = (
            df_rec_kpi[df_rec_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum()
            if not df_rec_kpi.empty else max(rec_prev_dre - rec_liq_dre, 0)
        )

        desp_prev_dre = (
            df_desp_kpi["Valor"].sum()
            if not df_desp_kpi.empty else 0.0
        )
        desp_liq_dre = (
            df_desp_kpi[df_desp_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum()
            if not df_desp_kpi.empty else 0.0
        )
        desp_aberto_dre = (
            df_desp_kpi[df_desp_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum()
            if not df_desp_kpi.empty else max(desp_prev_dre - desp_liq_dre, 0)
        )

        render_movement_cards(
            rec_prev_dre, rec_liq_dre, rec_aberto_dre, "Receitas",
            df_detalhes=df_rec_kpi, state_key="dre_receitas"
        )
        mostrar_detalhes_card()

        st.markdown("<br>", unsafe_allow_html=True)

        render_movement_cards(
            desp_prev_dre, desp_liq_dre, desp_aberto_dre, "Despesas",
            df_detalhes=df_desp_kpi, state_key="dre_despesas"
        )
        mostrar_detalhes_card()

        st.caption(
            "Os cards usam os lançamentos da API F360 respeitando a conta/loja e o período selecionados."
        )
        st.markdown("<br>", unsafe_allow_html=True)
        dre_list = [{
            "Categoria CFO": "0. RECEITAS DE VENDAS",
            "Previsto (R$)": f"R$ {tot_rec_prev:,.2f}",
            "Realizado (R$)": f"R$ {tot_rec_real:,.2f}",
            "Variação (R$)": f"R$ {tot_rec_real - tot_rec_prev:,.2f}"
        }]

        cats = [
            "1. FORNECEDORES / MERCADORIAS (CMV)",
            "2. IMPOSTOS SOBRE VENDAS",
            "3. DESPESAS DE OCUPAÇÃO",
            "4. FOLHA DE PAGAMENTO & ENCARGOS",
            "5. DESPESAS OPERACIONAIS & VENDAS",
            "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL",
            "7. DESPESAS DE SÓCIOS"
        ]

        tot_saidas_prev = 0.0
        tot_saidas_real = 0.0

        for c in cats:
            p = (
                df_desp_kpi[df_desp_kpi["Categoria_CFO"] == c]["Valor"].sum()
                if not df_desp_kpi.empty else 0.0
            )
            r = (
                df_desp_kpi[
                    (df_desp_kpi["Categoria_CFO"] == c) &
                    (df_desp_kpi["Status_Clean"] == "REALIZADO")
                ]["Valor"].sum()
                if not df_desp_kpi.empty else 0.0
            )

            tot_saidas_prev += p
            tot_saidas_real += r

            dre_list.append({
                "Categoria CFO": f"   (-) {c}",
                "Previsto (R$)": f"R$ {p:,.2f}",
                "Realizado (R$)": f"R$ {r:,.2f}",
                "Variação (R$)": f"R$ {r - p:,.2f}"
            })

        dre_list.append({
            "Categoria CFO": "8. TOTAL SAÍDAS",
            "Previsto (R$)": f"R$ {tot_saidas_prev:,.2f}",
            "Realizado (R$)": f"R$ {tot_saidas_real:,.2f}",
            "Variação (R$)": f"R$ {tot_saidas_real - tot_saidas_prev:,.2f}"
        })

        res_prev = tot_rec_prev - tot_saidas_prev
        res_real = tot_rec_real - tot_saidas_real

        dre_list.append({
            "Categoria CFO": "(=) EBITDA",
            "Previsto (R$)": f"R$ {res_prev:,.2f}",
            "Realizado (R$)": f"R$ {res_real:,.2f}",
            "Variação (R$)": f"R$ {res_real - res_prev:,.2f}"
        })

        st.dataframe(
            pd.DataFrame(dre_list),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("Sincronize a API no menu lateral para visualizar o DRE.")

# ============================================================
# QUARTA ABA — COMPARATIVO POR LOJA (ORIGINAL)
# ============================================================
with tabs[3]:
    st.subheader("Comparativo Por Loja — Vendas e Despesas")

    if not df_api.empty:
        df_filtered_loja = df_api.copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_filtered_loja = df_filtered_loja[
                (df_filtered_loja["Vencimento_dt"].dt.date >= date_range[0]) &
                (df_filtered_loja["Vencimento_dt"].dt.date <= date_range[1])
            ]

        tem_loja = (
            "Empresa_Loja" in df_filtered_loja.columns and
            df_filtered_loja["Empresa_Loja"].replace("", np.nan).notna().any()
        )

        dimensao = "Empresa_Loja" if tem_loja else "Empresa"

        if not tem_loja:
            st.warning(
                "Sem dado de loja de origem nos lançamentos carregados. "
                "Mostrando por conta bancária de liquidação como alternativa."
            )

        df_desp_loja = df_filtered_loja[
            (df_filtered_loja["Tipo_Movimento"] == "DESPESA") &
            (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")
        ]

        df_rec_loja = df_filtered_loja[
            (df_filtered_loja["Tipo_Movimento"] == "RECEITA") &
            (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")
        ]

        if not df_desp_loja.empty:
            st.markdown("**Despesas por categoria**")
            pivot_desp = df_desp_loja.pivot_table(
                index="Categoria_CFO",
                columns=dimensao,
                values="Valor",
                aggfunc="sum",
                fill_value=0
            )
            st.dataframe(
                pivot_desp.style.format("R$ {:,.2f}"),
                use_container_width=True
            )

        if not df_rec_loja.empty:
            st.markdown("**Resumo Operacional (Receita x Despesa)**")

            resumo_rec = df_rec_loja.groupby(dimensao)["Valor"].sum().to_frame("Receita de Vendas")
            resumo_desp = (
                df_desp_loja.groupby(dimensao)["Valor"].sum().to_frame("Despesas")
                if not df_desp_loja.empty else pd.DataFrame()
            )

            resumo = resumo_rec.join(resumo_desp, how="outer").fillna(0)
            resumo["Resultado (Receita - Despesa)"] = (
                resumo["Receita de Vendas"] - resumo.get("Despesas", 0)
            )

            st.dataframe(
                resumo.style.format("R$ {:,.2f}"),
                use_container_width=True
            )

        if df_desp_loja.empty and df_rec_loja.empty:
            st.info("Nenhum lançamento com loja identificada para comparar no período selecionado.")
    else:
        st.warning("Sincronize a API para gerar o comparativo entre as lojas.")
