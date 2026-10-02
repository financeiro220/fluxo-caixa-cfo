import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta

from f360_api import (
    autenticar_f360, 
    buscar_parcelas_f360,
    processar_fluxo_de_caixa_oficial
)

st.set_page_config(page_title="Gelateria Borelli - Fluxo de Caixa", page_icon="🟢", layout="wide")
st.markdown("""<style>.stApp { background-color: #0E1117; color: #FFFFFF; } .main-title { font-size: 28px; font-weight: bold; color: #00875A; }</style>""", unsafe_allow_html=True)

try: F360_TOKEN = st.secrets["F360_TOKEN"]
except: F360_TOKEN = "11001cbb-792d-45e5-b2f9-03ffc46fe7ed"

MAPA_CNPJ_LOJA = {"36240923000168": "4- PANTANAL", "36240923000249": "5- ESTAÇÃO", "36240923000320": "8 - GOIABEIRAS"}

def categorizar_plano_contas(plano):
    p = str(plano).upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
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

st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚡ Sincronização API (DRE)")
    if "jwt" not in st.session_state: st.session_state.jwt = autenticar_f360(F360_TOKEN)
    
    periodo_api = st.date_input("Período DRE (API)", (date(2026, 9, 1), date(2026, 9, 30)), format="DD/MM/YYYY")
    if st.button("🚀 Sincronizar API para DRE", use_container_width=True) and len(periodo_api) == 2:
        with st.spinner("Sincronizando DRE..."):
            d_ini, d_fim = periodo_api[0].replace(day=1), periodo_api[1]
            df_desp = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Despesa")
            if not df_desp.empty: df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(categorizar_plano_contas)
            st.session_state.df_api_desp = df_desp
            
            df_rec = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Receita")
            if not df_rec.empty:
                df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
                df_rec["Tipo_Movimento"] = "RECEITA"
            st.session_state.df_api_rec = df_rec
            st.success("🟢 API Sincronizada!")

    st.divider()
    st.header("🏦 Upload Matriz Diária")
    file_fluxo_oficial = st.file_uploader("F360 > Fluxo de Caixa > Exportar", type=["xlsx"], accept_multiple_files=True)

if 'filtro_kpi' not in st.session_state: st.session_state.filtro_kpi = "PENDENTE"
fluxo_oficial = carregar_fluxo_oficial(file_fluxo_oficial) if file_fluxo_oficial else {}

df_api = pd.concat([d for d in [st.session_state.get("df_api_desp"), st.session_state.get("df_api_rec")] if d is not None and not d.empty], ignore_index=True) if st.session_state.get("df_api_desp") is not None else pd.DataFrame()

col1, col2 = st.columns([2, 1])
with col1: conta_selecionada = st.radio("Conta:", ["Ver Todas as Contas", "17 Pantanal Itaú", "51 Estação Itaú", "61 Itaú Goiabeiras", "52 RT", "36 MJL"], horizontal=True)
with col2:
    min_d, max_d = date(2026, 9, 1), date(2026, 9, 30)
    if not df_api.empty: min_d, max_d = df_api['Vencimento_dt'].min().date(), df_api['Vencimento_dt'].max().date()
    date_range = st.date_input("Filtro de Tela:", value=(min_d, max_d), format="DD/MM/YYYY")

df_kpi = df_api.copy()
if not df_kpi.empty:
    if conta_selecionada != "Ver Todas as Contas": df_kpi = df_kpi[df_kpi['Empresa'] == conta_selecionada]
    if isinstance(date_range, tuple) and len(date_range) == 2: df_kpi = df_kpi[(df_kpi['Vencimento_dt'].dt.date >= date_range[0]) & (df_kpi['Vencimento_dt'].dt.date <= date_range[1])]

df_rec_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'RECEITA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()
df_desp_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'DESPESA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()

tot_rec = df_rec_kpi['Valor'].sum() if not df_rec_kpi.empty else 0.0
tot_prev, tot_real, tot_pend = 0.0, 0.0, 0.0
if not df_desp_kpi.empty:
    tot_prev = df_desp_kpi['Valor'].sum()
    tot_real = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum()
    tot_pend = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'PENDENTE']['Valor'].sum()

st.divider()
k1, k2, k3, k4 = st.columns(4)
with k1: st.button(f"📊 PREVISTAS\nR$ {tot_prev:,.2f}", use_container_width=True)
with k2: st.button(f"🟢 LIQUIDADAS\nR$ {tot_real:,.2f}", use_container_width=True)
with k3: st.button(f"🔴 EM ABERTO\nR$ {tot_pend:,.2f}", use_container_width=True)
with k4: st.metric("Receita Líquida (API)", f"R$ {tot_rec:,.2f}")

st.markdown("<br>", unsafe_allow_html=True)
tab1, tab2 = st.tabs(["📅 Fluxo Diário (Fonte Excel F360)", "📋 DRE de Caixa (Fonte API)"])

with tab1:
    st.subheader("Matriz Diária - Valores 100% Espelhados do F360")
    oficial = fluxo_oficial.get(conta_selecionada) or fluxo_oficial.get("Ver Todas as Contas")
    if not oficial and len(fluxo_oficial) == 1: oficial = list(fluxo_oficial.values())[0]

    if oficial:
        df_of = oficial["df"]
        if isinstance(date_range, tuple) and len(date_range) == 2:
            df_of = df_of[(df_of['Data'].dt.date >= date_range[0]) & (df_of['Data'].dt.date <= date_range[1])]
        
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
            st.dataframe(pd.DataFrame(linhas_of)[["Linha de Extrato"] + dias_of].style.format({d: "R$ {:,.2f}" for d in dias_of}), use_container_width=True, hide_index=True)
        else: st.warning("Sem dados para o período filtrado no Excel.")
    else:
        st.info("👈 Por favor, anexe o 'Fluxo de Caixa.xlsx' na barra lateral para gerar esta aba com os saldos bancários corretos e a visão do orçamento.")

with tab2:
    st.subheader("DRE de Caixa (Visão Gerencial por Plano de Contas)")
    if not df_api.empty:
        dre_list = [{"Categoria CFO": "0. RECEITAS DE VENDAS", "Realizado (R$)": f"R$ {tot_rec:,.2f}"}]
        cats = ["1. FORNECEDORES / MERCADORIAS (CMV)", "2. IMPOSTOS SOBRE VENDAS", "3. DESPESAS DE OCUPAÇÃO", "4. FOLHA DE PAGAMENTO & ENCARGOS", "5. DESPESAS OPERACIONAIS & VENDAS", "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"]
        for c in cats:
            r = df_desp_kpi[df_desp_kpi['Categoria_CFO'] == c]['Valor'].sum() if not df_desp_kpi.empty else 0.0
            dre_list.append({"Categoria CFO": f"   (-) {c}", "Realizado (R$)": f"R$ {r:,.2f}"})
        res_real = tot_rec - tot_real
        dre_list.append({"Categoria CFO": "(=) EBITDA", "Realizado (R$)": f"R$ {res_real:,.2f}"})
        st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
    else: st.warning("Sincronize a API no menu lateral para visualizar o DRE.")