import streamlit as st
import pandas as pd
import numpy as np
import json
import re
from datetime import datetime, date, timedelta

# IMPORTAÇÃO DO MÓDULO F360
from f360_api import autenticar_f360, buscar_parcelas_f360

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
    .welcome-card {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-left: 6px solid #00875A;
        border-radius: 8px;
        padding: 25px;
        margin-top: 20px;
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

def categorizar_plano_contas(plano):
    if pd.isna(plano):
        return "5. DESPESAS OPERACIONAIS & VENDAS"
    
    p = str(plano).upper().strip()
    
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'TRANSFERÊNCIA', 'TRANSFERENCIA', 'MUMTUO']):
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
    else:
        return "5. DESPESAS OPERACIONAIS & VENDAS"

def carregar_api_f360(jwt_token, d_ini, d_fim, log=None):
    df_tudo = buscar_parcelas_f360(jwt_token, d_ini, d_fim, MAPA_CNPJ_LOJA, tipo="Ambos", log=log)
    if not df_tudo.empty:
        df_tudo["Categoria_CFO"] = df_tudo["Plano de Contas"].apply(categorizar_plano_contas)
    return df_tudo

# ---------------------------------------------------------
# INTERFACE SIDEBAR
# ---------------------------------------------------------
st.markdown("<div class='main-title'>🍦 Gelateria Borelli - Gestão de Fluxo de Caixa</div>", unsafe_allow_html=True)
st.markdown("<div class='main-subtitle'>Acompanhamento de liquidez, governança e extrato acumulado diário em tempo real (F360)</div>", unsafe_allow_html=True)

with st.sidebar:
    st.header("⚡ Integração F360 API")
    usar_api = st.toggle("Usar API F360 (Tempo Real)", value=True)
    
    if usar_api:
        if "jwt" not in st.session_state or st.session_state.jwt is None:
            st.session_state.jwt = autenticar_f360(F360_TOKEN)
            
        if st.session_state.jwt:
            st.success("🟢 Sessão JWT válida")
            hoje = date(2026, 9, 1) # Período base
            periodo_api = st.date_input(
                "Período do Fluxo de Caixa", 
                (hoje.replace(day=1), hoje + timedelta(days=30)), 
                format="DD/MM/YYYY"
            )
            
            btn_buscar = st.button("🚀 Consultar Fluxo de Caixa F360", use_container_width=True)
            
            if btn_buscar and len(periodo_api) == 2:
                log = []
                try:
                    with st.spinner("Consultando Fluxo de Caixa F360 (Contas 17, 51, 61 + Orçamento 2026)..."):
                        df_res = carregar_api_f360(st.session_state.jwt, periodo_api[0], periodo_api[1], log)
                        st.session_state.df_api = df_res
                        st.success("🟢 Fluxo de caixa carregado com sucesso!")
                except Exception as e:
                    st.error(f"Erro na API F360: {e}")
                    if "401" in str(e):
                        st.session_state.jwt = None
                
                with st.expander("🔍 Diagnóstico da API"):
                    st.code("\n".join(log) or "sem chamadas")
        else:
            st.error("🔴 Falha na autenticação F360")

if 'filtro_kpi' not in st.session_state:
    st.session_state.filtro_kpi = "PENDENTE"

# FONTE DE DADOS PRINCIPAL
df_tudo = st.session_state.get("df_api")

if df_tudo is not None and not df_tudo.empty:
    try:
        col_filtro1, col_filtro2 = st.columns([2, 1])
        
        min_date = df_tudo['Vencimento_dt'].min().date()
        max_date = df_tudo['Vencimento_dt'].max().date()
        
        with col_filtro1:
            st.caption("🏢 **Unidade / Loja:**")
            lojas_disponiveis = list(df_tudo['Empresa'].dropna().unique())
            lojas_opcoes = ["Ver Todas as Lojas"] + lojas_disponiveis
            loja_selecionada = st.radio("", lojas_opcoes, horizontal=True)

        with col_filtro2:
            st.caption("📅 **Período do Filtro:**")
            date_range = st.date_input(
                "",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
                format="DD/MM/YYYY"
            )

        df_filtered = df_tudo.copy()
        
        if loja_selecionada != "Ver Todas as Lojas":
            df_filtered = df_filtered[df_filtered['Empresa'] == loja_selecionada].copy()

        if isinstance(date_range, tuple) and len(date_range) == 2:
            start_date, end_date = date_range
            df_filtered = df_filtered[
                (df_filtered['Vencimento_dt'].dt.date >= start_date) & 
                (df_filtered['Vencimento_dt'].dt.date <= end_date)
            ]

        st.divider()

        # SEPARAÇÃO DE RECEITAS E DESPESAS
        df_receitas = df_filtered[df_filtered['Tipo_Movimento'] == 'RECEITA'].copy()
        df_despesas = df_filtered[df_filtered['Tipo_Movimento'] == 'DESPESA'].copy()

        df_desp_operacional = df_despesas[df_despesas['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy()
        df_desp_mutuo = df_despesas[df_despesas['Categoria_CFO'] == "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"].copy()

        # TOTALIZADORES
        tot_receita_prevista = df_receitas['Valor'].sum()
        tot_receita_realizada = df_receitas[df_receitas['Status_Clean'] == 'REALIZADO']['Valor'].sum()
        
        tot_previsto = df_desp_operacional['Valor'].sum()
        tot_realizado = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'REALIZADO']['Valor'].sum()
        tot_pendente = df_desp_operacional[df_desp_operacional['Status_Clean'] == 'PENDENTE']['Valor'].sum()
        tot_mutuo_realizado = df_desp_mutuo[df_desp_mutuo['Status_Clean'] == 'REALIZADO']['Valor'].sum()

        st.caption("👇 **Clique nos botões para filtrar as despesas na tabela inferior:**")

        k1, k2, k3, k4 = st.columns(4)

        with k1:
            if st.button(f"📊 DESPESAS PREVISTAS\nR$ {tot_previsto:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "TODOS"

        with k2:
            if st.button(f"🟢 DESPESAS LIQUIDADAS\nR$ {tot_realizado:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "REALIZADO"

        with k3:
            if st.button(f"🔴 DESPESAS EM ABERTO\nR$ {tot_pendente:,.2f}", use_container_width=True):
                st.session_state.filtro_kpi = "PENDENTE"

        with k4:
            st.metric("Total de Receitas Orçadas / Realizadas", f"R$ {tot_receita_prevista:,.2f}", delta=f"Realizado: R$ {tot_receita_realizada:,.2f}")

        st.markdown("<br>", unsafe_allow_html=True)

        tab1, tab2, tab3 = st.tabs(["📋 DRE de Caixa", "📅 Fluxo Diário (Extrato Banco)", "🏪 Comparativo Por Loja"])
        
        with tab1:
            st.subheader("Demonstrativo do Fluxo de Caixa (Previsto vs. Realizado)")
            
            dre_list = []
            dre_list.append({
                "Categoria CFO": "0. RECEITAS DE VENDAS / ENTRADAS (ORÇAMENTO 2026)",
                "Previsto (R$)": f"R$ {tot_receita_prevista:,.2f}",
                "Realizado (R$)": f"R$ {tot_receita_realizada:,.2f}",
                "Variação (R$)": f"R$ {tot_receita_realizada - tot_receita_prevista:,.2f}",
                "% do Total": "100.0%"
            })
                
            cats = [
                "1. FORNECEDORES / MERCADORIAS (CMV)",
                "2. IMPOSTOS SOBRE VENDAS",
                "3. DESPESAS DE OCUPAÇÃO",
                "4. FOLHA DE PAGAMENTO & ENCARGOS",
                "5. DESPESAS OPERACIONAIS & VENDAS",
                "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
            ]
            
            for c in cats:
                p = df_desp_operacional[df_desp_operacional['Categoria_CFO'] == c]['Valor'].sum()
                r = df_desp_operacional[(df_desp_operacional['Categoria_CFO'] == c) & (df_desp_operacional['Status_Clean'] == 'REALIZADO')]['Valor'].sum()
                v = r - p
                pct = (p / tot_receita_prevista * 100) if tot_receita_prevista > 0 else 0.0
                dre_list.append({
                    "Categoria CFO": f"   (-) {c}",
                    "Previsto (R$)": f"R$ {p:,.2f}",
                    "Realizado (R$)": f"R$ {r:,.2f}",
                    "Variação (R$)": f"R$ {v:,.2f}",
                    "% do Total": f"{pct:.1f}%"
                })
                
            res_operacional_prev = tot_receita_prevista - tot_previsto
            res_operacional_real = tot_receita_realizada - tot_realizado
            
            dre_list.append({
                "Categoria CFO": "(=) RESULTADO LÍQUIDO OPERACIONAL (EBITDA DA LOJA)",
                "Previsto (R$)": f"R$ {res_operacional_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_operacional_real:,.2f}",
                "Variação (R$)": f"R$ {res_operacional_real - res_operacional_prev:,.2f}",
                "% do Total": f"{(res_operacional_real / tot_receita_realizada * 100) if tot_receita_realizada > 0 else 0:.1f}%"
            })
            
            p_mutuo = df_desp_mutuo['Valor'].sum()
            r_mutuo = tot_mutuo_realizado
            dre_list.append({
                "Categoria CFO": "   (-) 7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO ENTRE LOJAS",
                "Previsto (R$)": f"R$ {p_mutuo:,.2f}",
                "Realizado (R$)": f"R$ {r_mutuo:,.2f}",
                "Variação (R$)": f"R$ {r_mutuo - p_mutuo:,.2f}",
                "% do Total": f"{(p_mutuo / tot_receita_prevista * 100) if tot_receita_prevista > 0 else 0:.1f}%"
            })
            
            res_final_prev = res_operacional_prev - p_mutuo
            res_final_real = res_operacional_real - r_mutuo
            dre_list.append({
                "Categoria CFO": "(=) GERAÇÃO LÍQUIDA FINAL DE CAIXA DA CONTA",
                "Previsto (R$)": f"R$ {res_final_prev:,.2f}",
                "Realizado (R$)": f"R$ {res_final_real:,.2f}",
                "Variação (R$)": f"R$ {res_final_real - res_final_prev:,.2f}",
                "% do Total": f"{(res_final_real / tot_receita_realizada * 100) if tot_receita_realizada > 0 else 0:.1f}%"
            })
            
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True, hide_index=True)
            
        with tab2:
            st.subheader("Matriz Diária com Saldo de Encerramento (Fluxo de Caixa F360)")
            
            df_filtered['Dia'] = pd.to_datetime(df_filtered['Vencimento_dt']).dt.day
            dias_mes = sorted([int(d) for d in df_filtered['Dia'].dropna().unique() if d > 0])
            
            piv_ent = df_receitas.groupby('Dia')['Valor'].sum()
            piv_sai = df_despesas[df_despesas['Status_Clean'] == 'REALIZADO'].groupby('Dia')['Valor'].sum()
            
            row_e, row_s, row_liq = {}, {}, {}
            
            for d in dias_mes:
                e = piv_ent.get(d, 0.0)
                s = piv_sai.get(d, 0.0)
                l = e - s
                
                row_e[d] = e
                row_s[d] = s
                row_liq[d] = l
                
            df_extrato_diario = pd.DataFrame([
                {"Linha de Extrato": "1. (+) Total Receitas (Vendas Orçadas / Realizadas)", **row_e},
                {"Linha de Extrato": "2. (-) Total Saídas Liquidadas", **row_s},
                {"Linha de Extrato": "3. (=) Resultado Líquido do Dia", **row_liq}
            ])
            
            cols_order = ["Linha de Extrato"] + dias_mes
            st.dataframe(
                df_extrato_diario[cols_order].style.format({d: "R$ {:,.2f}" for d in dias_mes}),
                use_container_width=True,
                hide_index=True
            )
            
        with tab3:
            st.subheader("Matriz Comparativa entre Lojas")
            pivot_store = df_despesas.pivot_table(index='Categoria_CFO', columns='Empresa', values='Valor', aggfunc='sum', fill_value=0)
            st.dataframe(pivot_store.style.format("R$ {:,.2f}"), use_container_width=True)

        st.divider()

        # TABELA INFERIOR DE DESPESAS
        if st.session_state.filtro_kpi == "REALIZADO":
            df_titulos = df_despesas[df_despesas['Status_Clean'] == 'REALIZADO'].copy()
        elif st.session_state.filtro_kpi == "PENDENTE":
            df_titulos = df_despesas[df_despesas['Status_Clean'] == 'PENDENTE'].copy()
        else:
            df_titulos = df_despesas.copy()

        df_display = df_titulos.copy()
        df_display['Data de Caixa'] = df_display['Vencimento_dt'].dt.strftime('%d/%m/%Y')
        
        st.subheader(f"📊 Exibindo Títulos de Despesas ({len(df_display)} registros)")
        st.dataframe(
            df_display[['Número', 'Empresa', 'Cliente / Fornecedor', 'Data de Caixa', 'Valor', 'Plano de Contas', 'Categoria_CFO', 'Status_Clean']],
            use_container_width=True,
            hide_index=True
        )

    except Exception as e:
        st.error(f"Erro ao processar os dados: {e}")
else:
    st.markdown("""
    <div class='welcome-card'>
        <h3>🍦 Painel de Fluxo de Caixa Executivo - Gelateria Borelli</h3>
        <p>Aguardando carga dos relatórios no menu lateral para inicializar o processamento.</p>
        <ol>
            <li>Ative a opção <b>Usar API F360 (Tempo Real)</b> no menu lateral e clique em <b>🚀 Consultar Fluxo de Caixa F360</b>.</li>
        </ol>
    </div>
    """, unsafe_allow_html=True)