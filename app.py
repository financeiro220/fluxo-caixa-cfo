import streamlit as st
import pandas as pd
import numpy as np
import json
import re
import unicodedata
from datetime import datetime, date, timedelta

# IMPORTAÇÃO DO MÓDULO F360
from f360_api import (
    autenticar_f360, 
    buscar_parcelas_f360, 
    buscar_saldos_bancarios_f360,
    IDS_CONTAS_BORELLI
)

# ---------------------------------------------------------
# CONFIGURAÇÃO DA PÁGINA E TEMA BORELLI
# ---------------------------------------------------------
st.set_page_config(
    page_title="Gelateria Borelli - Gestão de Fluxo de Caixa",
    page_icon="🟢",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp {
        background-color: #0E1117;
        color: #FFFFFF;
    }
    .main-title {
        font-size: 28px;
        font-weight: bold;
        color: #00875A;
        margin-bottom: 5px;
    }
    .main-subtitle {
        font-size: 14px;
        color: #A0AAB0;
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

try:
    F360_TOKEN = st.secrets["F360_TOKEN"]
except Exception:
    F360_TOKEN = "11001cbb-792d-45e5-b2f9-03ffc46fe7ed"

MAPA_CNPJ_LOJA = {
    "36240923000168": "4- PANTANAL",
    "36240923000249": "5- ESTAÇÃO",
    "36240923000320": "8 - GOIABEIRAS"
}

# FERIADOS NACIONAIS / REGIONAIS CONHECIDOS
FERIADOS = ['2026-09-07']

def categorizar_plano_contas(plano):
    if pd.isna(plano): return "5. DESPESAS OPERACIONAIS & VENDAS"
    p = str(plano).upper().strip()
    if any(k in p for k in ['EMPRÉSTIMO MÚTUO', 'EMPRESTIMO MUTUO', 'MÚTUO', 'MUTUO', 'TRANSFERÊNCIA INTERCOMPANY']):
        return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    elif any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'DESCARTAVEIS', 'PRODUTO PARA REVENDA', 'LEITE', 'INSUMOS', 'MEC3', 'BOBINAS', 'FRUTAS', 'RIBERFOODS']):
        return "1. FORNECEDORES / MERCADORIAS (CMV)"
    elif any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS']):
        return "2. IMPOSTOS SOBRE VENDAS"
    elif any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'CONDOMINIO', 'ENERGIA', 'ÁGUA', 'AGUA', 'IPTU', 'SEGURO PREDIAL', 'FUNDO DE PROMOÇÃO', 'LIMPEZA', 'FACHADA']):
        return "3. DESPESAS DE OCUPAÇÃO"
    elif any(k in p for k in ['SALÁRIO', 'SALARIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'FERIAS', 'DÉCIMO', 'DECIMO', 'AUXÍLIO', 'AUXILIO', 'PREMIAÇÕES', 'PREMIACOES', 'RESCISÃO', 'RESCISAO', 'DSR', 'ADICIONAL', 'PROVENTOS', 'FUNCIONÁRIOS', 'FUNCIONARIOS', 'UNIFORMES']):
        return "4. FOLHA DE PAGAMENTO & ENCARGOS"
    elif any(k in p for k in ['EMPRÉSTIMO', 'EMPRESTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFAS', 'RENEGOCIAÇÃO', 'RENEGOCIACAO', 'INVESTIMENTOS']):
        return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
    else: return "5. DESPESAS OPERACIONAIS & VENDAS"

def categorizar_receita(row):
    plano = str(row.get("Plano de Contas") or "").upper().strip()
    if any(k in plano for k in ['EMPRÉSTIMO MÚTUO', 'EMPRESTIMO MUTUO', 'MÚTUO', 'MUTUO', 'TRANSFERÊNCIA INTERCOMPANY']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    return "0. RECEITAS DE VENDAS"

def carregar_despesas_api_f360(jwt_token, d_ini, d_fim, log=None):
    df_desp = buscar_parcelas_f360(jwt_token, d_ini, d_fim, MAPA_CNPJ_LOJA, tipo="Despesa", log=log)
    if df_desp is not None and not df_desp.empty: df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(categorizar_plano_contas)
    return df_desp

def carregar_receitas_api_f360(jwt_token, d_ini, d_fim, log=None):
    df_rec = buscar_parcelas_f360(jwt_token, d_ini, d_fim, MAPA_CNPJ_LOJA, tipo="Receita", log=log)
    if df_rec is not None and not df_rec.empty:
        df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
        df_rec["Tipo_Movimento"] = "RECEITA"
    return df_rec

# ---------------------------------------------------------
# INTERFACE SIDEBAR (SALDOS INICIAIS DINÂMICOS)
# ---------------------------------------------------------
with st.sidebar:
    st.header("⚡ Sincronização API F360")
    
    if "jwt" not in st.session_state or st.session_state.jwt is None:
        st.session_state.jwt = autenticar_f360(F360_TOKEN)
        
    if st.session_state.jwt:
        hoje = date(2026, 9, 1)
        periodo_api = st.date_input("Período de Busca", (hoje.replace(day=1), hoje.replace(day=1) + timedelta(days=29)), format="DD/MM/YYYY")
        
        st.divider()
        st.subheader("🏦 Saldos Iniciais do Mês (D-1)")
        st.caption("Altere os saldos de abertura oficiais do banco aqui:")
        saldo_17 = st.number_input("17 Pantanal Itaú", value=24053.13, step=100.0)
        saldo_36 = st.number_input("36 MJL", value=500.00, step=100.0)
        saldo_51 = st.number_input("51 Estação Itaú", value=333.38, step=100.0)
        saldo_52 = st.number_input("52 RT", value=3434.92, step=100.0)
        saldo_61 = st.number_input("61 Itaú Goiabeiras", value=300.77, step=100.0)
        
        SALDOS_INICIAIS = {
            "17 Pantanal Itaú": saldo_17,
            "36 MJL": saldo_36,
            "51 Estação Itaú": saldo_51,
            "52 RT": saldo_52,
            "61 Itaú Goiabeiras": saldo_61
        }
        
        st.markdown("---")
        btn_sincronizar = st.button("🚀 Sincronizar Tudo via API", use_container_width=True)
        
        log = []
        if btn_sincronizar and len(periodo_api) == 2:
            try:
                # FORÇA BUSCA DESDE O DIA 1 DO MÊS PARA GARANTIR CÁLCULOS
                d_ini_api = periodo_api[0].replace(day=1)
                d_fim_api = periodo_api[1]

                with st.spinner("Sincronizando extratos com a F360..."):
                    st.session_state.df_api_desp = carregar_despesas_api_f360(st.session_state.jwt, d_ini_api, d_fim_api, log)
                    st.session_state.df_api_rec = carregar_receitas_api_f360(st.session_state.jwt, d_ini_api, d_fim_api, log)
                    st.success("🟢 Dados sincronizados com sucesso!")
            except Exception as e:
                st.error(f"Erro na Sincronização: {e}")

if 'filtro_kpi' not in st.session_state: st.session_state.filtro_kpi = "PENDENTE"

# ---------------------------------------------------------
# PROCESSAMENTO DE DADOS E CORREÇÃO BANCÁRIA
# ---------------------------------------------------------
df_tudo_list = []
if st.session_state.get("df_api_desp") is not None and not st.session_state["df_api_desp"].empty: df_tudo_list.append(st.session_state["df_api_desp"])
if st.session_state.get("df_api_rec") is not None and not st.session_state["df_api_rec"].empty: df_tudo_list.append(st.session_state["df_api_rec"])
df_tudo = pd.concat(df_tudo_list, ignore_index=True) if df_tudo_list else None

def proximo_dia_util(d):
    """
    Empurra as datas de Finais de Semana e Feriados para Segunda-feira.
    Contas bancárias nunca movimentam em feriados, igual no F360.
    """
    if pd.isna(d): return d
    d_ts = pd.to_datetime(d)
    while d_ts.weekday() >= 5 or d_ts.strftime('%Y-%m-%d') in FERIADOS: 
        d_ts += timedelta(days=1)
    return d_ts

if df_tudo is not None and not df_tudo.empty:
    df_tudo['Vencimento_dt'] = df_tudo['Vencimento_dt'].apply(proximo_dia_util)

# ---------------------------------------------------------
# RENDERIZAÇÃO DO DASHBOARD
# ---------------------------------------------------------
if df_tudo is not None and not df_tudo.empty:
    if 'Tipo_Movimento' not in df_tudo.columns: df_tudo['Tipo_Movimento'] = 'DESPESA'

    col_filtro1, col_filtro2 = st.columns([2, 1])
    min_date, max_date = df_tudo['Vencimento_dt'].min().date(), df_tudo['Vencimento_dt'].max().date()
    
    with col_filtro1:
        conta_selecionada = st.radio("", ["Ver Todas as Contas", "17 Pantanal Itaú", "51 Estação Itaú", "61 Itaú Goiabeiras", "52 RT", "36 MJL"], horizontal=True)
    with col_filtro2:
        date_range = st.date_input("Período de Exibição no Caixa", value=(min_date, max_date), min_value=min_date, max_value=max_date, format="DD/MM/YYYY")

    df_filtered = df_tudo.copy()
    if conta_selecionada != "Ver Todas as Contas": df_filtered = df_filtered[df_filtered['Empresa'] == conta_selecionada]

    df_kpi = df_filtered.copy()
    if isinstance(date_range, tuple) and len(date_range) == 2:
        df_kpi = df_kpi[(df_kpi['Vencimento_dt'].dt.date >= date_range[0]) & (df_kpi['Vencimento_dt'].dt.date <= date_range[1])]

    df_receitas, df_despesas = df_kpi[df_kpi['Tipo_Movimento'] == 'RECEITA'], df_kpi[df_kpi['Tipo_Movimento'] == 'DESPESA']
    df_rec_vendas = df_receitas[df_receitas['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"]
    df_desp_operacional = df_despesas[df_despesas['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"]

    tot_receita_prevista = df_rec_vendas['Valor'].sum() if not df_rec_vendas.empty else 0.0
    tot_receita_realizada = df_rec_vendas[df_rec_vendas['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_rec_vendas.empty else tot_receita_prevista
    tot_previsto = df_desp_operacional['Valor'].sum() if not df_desp_operacional.empty else 0.0
    tot_realizado = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_desp_operacional.empty else 0.0
    tot_pendente = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'PENDENTE']['Valor'].sum() if not df_desp_operacional.empty else 0.0

    st.divider()
    k1, k2, k3, k4 = st.columns(4)
    with k1:
        if st.button(f"📊 DESPESAS PREVISTAS\nR$ {tot_previsto:,.2f}", use_container_width=True): st.session_state.filtro_kpi = "TODOS"
    with k2:
        if st.button(f"🟢 DESPESAS LIQUIDADAS\nR$ {tot_realizado:,.2f}", use_container_width=True): st.session_state.filtro_kpi = "REALIZADO"
    with k3:
        if st.button(f"🔴 DESPESAS EM ABERTO\nR$ {tot_pendente:,.2f}", use_container_width=True): st.session_state.filtro_kpi = "PENDENTE"
    with k4:
        st.metric("Total Receita Líquida (Vendas)", f"R$ {tot_receita_prevista:,.2f}", delta=f"Realizado: R$ {tot_receita_realizada:,.2f}")

    st.markdown("<br>", unsafe_allow_html=True)

    tab1, tab2, tab3 = st.tabs(["📅 Fluxo Diário (Extrato Banco)", "📋 DRE de Caixa", "🏪 Comparativo Por Conta"])
    
    with tab1:
        st.subheader("Matriz Diária com Saldo de Encerramento (Visão Extrato Bancário F360)")
        
        dias_visiveis = []
        if isinstance(date_range, tuple) and len(date_range) == 2:
            d_temp = date_range[0]
            while d_temp <= date_range[1]:
                if d_temp.day not in dias_visiveis:
                    dias_visiveis.append(d_temp.day)
                d_temp += timedelta(days=1)
        else:
            dias_visiveis = list(range(min_date.day, max_date.day + 1))

        dias_mes_calc = list(range(1, 32))
        
        df_rec_total = df_filtered[df_filtered['Tipo_Movimento'] == 'RECEITA']
        df_desp_total = df_filtered[df_filtered['Tipo_Movimento'] == 'DESPESA']
        
        p_vendas = df_rec_total[(df_rec_total['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO") & (df_rec_total['Status_Clean'] == 'REALIZADO')].groupby(df_rec_total['Vencimento_dt'].dt.day)['Valor'].sum()
        p_tin = df_rec_total[(df_rec_total['Categoria_CFO'] == "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO") & (df_rec_total['Status_Clean'] == 'REALIZADO')].groupby(df_rec_total['Vencimento_dt'].dt.day)['Valor'].sum()
        p_sai = df_desp_total[(df_desp_total['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO") & (df_desp_total['Status_Clean'] == 'REALIZADO')].groupby(df_desp_total['Vencimento_dt'].dt.day)['Valor'].sum()
        p_tout = df_desp_total[(df_desp_total['Categoria_CFO'] == "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO") & (df_desp_total['Status_Clean'] == 'REALIZADO')].groupby(df_desp_total['Vencimento_dt'].dt.day)['Valor'].sum()

        row_s_ini, row_vendas, row_tin, row_tot_ent, row_saidas, row_tout, row_tot_sai, row_liq_op, row_saldo_final = {}, {}, {}, {}, {}, {}, {}, {}, {}

        if conta_selecionada in SALDOS_INICIAIS:
            saldo_acumulado = SALDOS_INICIAIS[conta_selecionada]
        else:
            saldo_acumulado = sum(SALDOS_INICIAIS.values())

        for d in dias_mes_calc:
            s_inicial = saldo_acumulado
            v = p_vendas.get(d, 0.0)
            tin = p_tin.get(d, 0.0)
            tot_e = v + tin
            s = p_sai.get(d, 0.0)
            tout = p_tout.get(d, 0.0)
            tot_s = s + tout
            liq_op = v - s
            s_final = s_inicial + tot_e - tot_s
            saldo_acumulado = s_final 
            
            if d in dias_visiveis:
                row_s_ini[d] = s_inicial
                row_vendas[d] = v
                row_tin[d] = tin
                row_tot_ent[d] = tot_e
                row_saidas[d] = s
                row_tout[d] = tout
                row_tot_sai[d] = tot_s
                row_liq_op[d] = liq_op
                row_saldo_final[d] = s_final

        if dias_visiveis:
            df_extrato_diario = pd.DataFrame([
                {"Linha de Extrato": "0. 🏦 SALDO INICIAL DO DIA", **row_s_ini},
                {"Linha de Extrato": "1. (+) Total Vendas Liquidadas", **row_vendas},
                {"Linha de Extrato": "2. (+) Transferências Recebidas", **row_tin},
                {"Linha de Extrato": "3. (=) TOTAL DE ENTRADAS", **row_tot_ent},
                {"Linha de Extrato": "4. (-) Total Saídas Liquidadas", **row_saidas},
                {"Linha de Extrato": "5. (-) Transferências Concedidas", **row_tout},
                {"Linha de Extrato": "6. (=) TOTAL DE SAÍDAS", **row_tot_sai},
                {"Linha de Extrato": "7. (=) Resultado Líquido", **row_liq_op},
                {"Linha de Extrato": "8. 🏦 SALDO FINAL EM CONTA BANCÁRIA", **row_saldo_final}
            ])
            cols_order = ["Linha de Extrato"] + dias_visiveis
            st.dataframe(df_extrato_diario[cols_order].style.format({d: "R$ {:,.2f}" for d in dias_visiveis}), use_container_width=True, hide_index=True)
        else:
            st.warning("Nenhum dia selecionado no filtro.")
            
    with tab2:
        st.subheader("Demonstrativo do Fluxo de Caixa (Previsto vs. Realizado)")
        dre_list = [{"Categoria CFO": "0. RECEITAS DE VENDAS / ENTRADAS (LÍQUIDO)", "Previsto (R$)": f"R$ {tot_receita_prevista:,.2f}", "Realizado (R$)": f"R$ {tot_receita_realizada:,.2f}", "Variação (R$)": f"R$ {tot_receita_realizada - tot_receita_prevista:,.2f}", "% do Total": "100.0%"}]
        cats = ["1. FORNECEDORES / MERCADORIAS (CMV)", "2. IMPOSTOS SOBRE VENDAS", "3. DESPESAS DE OCUPAÇÃO", "4. FOLHA DE PAGAMENTO & ENCARGOS", "5. DESPESAS OPERACIONAIS & VENDAS", "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"]
        for c in cats:
            p = df_desp_operacional[df_desp_operacional['Categoria_CFO'] == c]['Valor'].sum() if not df_desp_operacional.empty else 0.0
            r = df_desp_operacional[(df_desp_operacional['Categoria_CFO'] == c) & (df_desp_operacional['Status_Clean'] == 'REALIZADO')]['Valor'].sum() if not df_desp_operacional.empty else 0.0
            v = r - p
            pct = (p / tot_receita_prevista * 100) if tot_receita_prevista > 0 else 0.0
            dre_list.append({"Categoria CFO": f"   (-) {c}", "Previsto (R$)": f"R$ {p:,.2f}", "Realizado (R$)": f"R$ {r:,.2f}", "Variação (R$)": f"R$ {v:,.2f}", "% do Total": f"{pct:.1f}%"})
        res_operacional_prev = tot_receita_prevista - tot_previsto
        res_operacional_real = tot_receita_realizada - tot_realizado
        dre_list.append({"Categoria CFO": "(=) RESULTADO LÍQUIDO OPERACIONAL (EBITDA)", "Previsto (R$)": f"R$ {res_operacional_prev:,.2f}", "Realizado (R$)": f"R$ {res_operacional_real:,.2f}", "Variação (R$)": f"R$ {res_operacional_real - res_operacional_prev:,.2f}", "% do Total": f"{(res_operacional_real / tot_receita_realizada * 100) if tot_receita_realizada > 0 else 0:.1f}%"})
        st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
            
    with tab3:
        st.subheader("Matriz Comparativa por Conta Bancária")
        if not df_despesas.empty:
            pivot_store = df_despesas.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)

else:
    st.markdown("""
    <div class='welcome-card'>
        <h3>🍦 Painel de Fluxo de Caixa Executivo - Gelateria Borelli</h3>
        <p>Aguardando sincronização automática no menu lateral.</p>
    </div>
    """, unsafe_allow_html=True)