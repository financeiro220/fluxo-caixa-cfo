import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import os
import pickle
import base64
from datetime import datetime, date

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
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ============================================================
# FUNÇÃO PARA CARREGAR A LOGO LOCAL (COM CAMINHO ABSOLUTO)
# ============================================================
@st.cache_data
def carregar_logo():
    nomes_tentativas = ["logo_borelli.png", "logo_borelli.png.png", "logo_borelli"]
    
    pastas_para_tentar = [
        ".", 
        os.path.dirname(os.path.abspath(__file__)),
        os.getcwd(),
        r"C:\Users\USUARIO\OneDrive\Área de Trabalho\fluxo-caixa-cfo"
    ]

    for pasta in set(pastas_para_tentar):
        try:
            if os.path.exists(pasta):
                arquivos_na_pasta = os.listdir(pasta)
                for arquivo in arquivos_na_pasta:
                    if arquivo.lower().strip() in nomes_tentativas:
                        caminho_completo = os.path.join(pasta, arquivo)
                        with open(caminho_completo, "rb") as f:
                            return base64.b64encode(f.read()).decode()
        except Exception:
            continue
    return None

LOGO_BASE64 = carregar_logo()

# ============================================================
# TELA DE LOGIN E ESTADO DA SESSÃO
# ============================================================
try:
    LOGIN_USUARIO = st.secrets.get("APP_LOGIN", "financeiro")
    LOGIN_SENHA = st.secrets.get("APP_SENHA", "borelli2026")
except Exception:
    LOGIN_USUARIO, LOGIN_SENHA = "financeiro", "borelli2026"

if "autenticado" not in st.session_state:
    st.session_state.autenticado = False

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = 0

if not st.session_state.autenticado:
    st.markdown("""
    <style>
        .stApp { background: #0B0F14; }
        [data-testid="stHeader"] { background: rgba(11,15,20,0.96); }
    </style>
    """, unsafe_allow_html=True)

    col_esq, col_meio, col_dir = st.columns([1, 1.2, 1])
    with col_meio:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        
        if LOGO_BASE64:
            st.markdown(
                f"<div style='text-align:center;'><img src='data:image/png;base64,{LOGO_BASE64}' style='max-height:140px; margin-bottom:15px;'></div>"
                "<div style='text-align:center;color:#8F9AA8;margin-bottom:24px;font-size:16px;'>Fluxo de Caixa · Controladoria</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='text-align:center;font-size:32px;font-weight:800;color:#F8FAFC;'>BORELLI</div>"
                "<div style='text-align:center;color:#8F9AA8;margin-bottom:24px;'>Fluxo de Caixa · Controladoria</div>",
                unsafe_allow_html=True,
            )

        with st.form("form_login"):
            usuario = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            entrar = st.form_submit_button("Entrar", use_container_width=True)

        if entrar:
            if usuario == LOGIN_USUARIO and senha == LOGIN_SENHA:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")

    st.stop()

# ============================================================
# IDENTIDADE VISUAL E CONSTANTES
# ============================================================
CACHE_API_FILE = "dados_salvos_api.pkl"
CACHE_EXCEL_FILE = "dados_salvos_excel.pkl"

st.markdown("""
<style>
    .stApp { background: #0B0F14; color: #F4F7FA; }
    [data-testid="stHeader"] { background: rgba(11,15,20,0.96); }
    [data-testid="stSidebar"] { background: #151A21; border-right: 1px solid #252C35; }
    [data-testid="stSidebar"] > div:first-child { padding-top: 1rem; }
    .hero-title { font-size: 30px; line-height: 1.05; font-weight: 800; letter-spacing: -0.8px; margin-bottom: 2px; color: #F8FAFC; }
    .hero-subtitle { color: #8F9AA8; font-size: 14px; margin-bottom: 18px; }
    .section-title { font-size: 18px; font-weight: 750; color: #F4F7FA; margin: 4px 0 10px 0; }
    .muted { color: #8994A3; font-size: 12px; }
    .status-pill { display: inline-flex; align-items: center; gap: 7px; padding: 7px 12px; border-radius: 999px; background: #123022; color: #58D68D; border: 1px solid #20583C; font-size: 12px; font-weight: 700; }
    .status-dot { width: 8px; height: 8px; border-radius: 50%; background: #35D07F; display: inline-block; box-shadow: 0 0 10px rgba(53,208,127,.45); }
    .kpi-card { background: linear-gradient(145deg, #151B23 0%, #10151C 100%); border: 1px solid #28313C; border-radius: 12px; padding: 15px 16px 14px 16px; min-height: 112px; box-shadow: 0 8px 24px rgba(0,0,0,.12); }
    .kpi-label { color: #8F9AA8; font-size: 11px; font-weight: 700; letter-spacing: .4px; text-transform: uppercase; margin-bottom: 7px; }
    .kpi-value { color: #F8FAFC; font-size: 24px; line-height: 1.05; font-weight: 800; letter-spacing: -.5px; }
    .kpi-green { color: #45D483; }
    .kpi-red { color: #FF6262; }
    .kpi-yellow { color: #F4C95D; }
    .kpi-blue { color: #69B7FF; }
    .kpi-foot { color: #697585; font-size: 11px; margin-top: 8px; }
    .panel { background: #11161D; border: 1px solid #252D37; border-radius: 12px; padding: 16px; margin-bottom: 14px; }
    .panel-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
    .panel-title { font-size: 15px; font-weight: 750; color: #F4F7FA; }
    .alert-good { background: #10271D; border: 1px solid #24553C; color: #67E39A; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    .alert-warn { background: #2A2413; border: 1px solid #67531D; color: #F3D36A; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    .alert-danger { background: #2A1719; border: 1px solid #663034; color: #FF8585; border-radius: 10px; padding: 11px 13px; font-size: 13px; font-weight: 650; }
    [data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
    .stButton > button { border-radius: 8px; border: 1px solid #343D49; background: #171D25; color: #E9EEF3; font-weight: 650; }
    .stButton > button:hover { border-color: #00875A; color: #5CE39A; }
    hr { border-color: #252D37 !important; }
</style>
""", unsafe_allow_html=True)

# ============================================================
# FUNÇÕES DE LÓGICA
# ============================================================
if 'fluxo_oficial_cache' not in st.session_state:
    st.session_state.fluxo_oficial_cache = {}
    if os.path.exists(CACHE_EXCEL_FILE):
        try:
            with open(CACHE_EXCEL_FILE, 'rb') as f:
                st.session_state.fluxo_oficial_cache = pickle.load(f)
        except Exception:
            pass

if 'api_loaded' not in st.session_state:
    st.session_state.api_loaded = True
    if os.path.exists(CACHE_API_FILE):
        try:
            with open(CACHE_API_FILE, 'rb') as f:
                api_data = pickle.load(f)
            st.session_state.df_api_desp = api_data.get('desp', pd.DataFrame())
            st.session_state.df_api_rec = api_data.get('rec', pd.DataFrame())
        except Exception:
            pass

if 'show_kpi_data' not in st.session_state: st.session_state.show_kpi_data = None

def categorizar_receita(row):
    p = str(row.get("Plano de Contas") or "").upper().strip()
    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
    return "0. RECEITAS DE VENDAS"

@st.cache_data(ttl=3600)
def carregar_fluxo_oficial(_arquivos):
    resultado = {}
    for arq in _arquivos:
        df_dias, saldo_ini, contas = processar_fluxo_de_caixa_oficial(arq)
        nome = getattr(arq, "name", "Arquivo")
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

def formatar_dataframe_brl(df):
    if df is None or df.empty: return df
    df_show = df.copy()
    for col in df_show.columns:
        if pd.api.types.is_numeric_dtype(df_show[col]):
            df_show[col] = df_show[col].apply(lambda x: f"R$ {x:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
    return df_show

def _preparar_titulos_detalhe(df, status=None):
    if df is None or df.empty: return pd.DataFrame()
    d = df.copy()
    if status == "REALIZADO": d = d[d["Status_Clean"].astype(str).str.upper() == "REALIZADO"]
    elif status == "PENDENTE": d = d[d["Status_Clean"].astype(str).str.upper() == "PENDENTE"]

    colunas_preferidas = ["Vencimento_dt", "Empresa", "Empresa_Loja", "Cliente / Fornecedor", "Plano de Contas", "Categoria_CFO", "Valor", "Status_Clean", "Status", "Data_Liquidacao"]
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

    rename = {"Empresa_Loja": "Loja", "Status_Clean": "Status"}
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
    
    cols = d.columns.tolist()
    if "Vencimento" in cols: cols.insert(0, cols.pop(cols.index("Vencimento")))
    if "Empresa" in cols: cols.insert(1, cols.pop(cols.index("Empresa")))
    if "Loja" in cols: cols.insert(2, cols.pop(cols.index("Loja")))
    if "Cliente / Fornecedor" in cols: cols.insert(3, cols.pop(cols.index("Cliente / Fornecedor")))
    
    return d[cols]

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
                st.caption(f"{len(df_show):,} título(s) · Total: {brl(total)}")
                st.dataframe(formatar_dataframe_brl(df_show), use_container_width=True, hide_index=True)
            else:
                st.dataframe(df_show, use_container_width=True, hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

# ============================================================
# SIDEBAR E PROCESSAMENTO
# ============================================================
with st.sidebar:
    if LOGO_BASE64:
        st.markdown(f"<div style='text-align:center;'><img src='data:image/png;base64,{LOGO_BASE64}' style='max-width:160px; margin-bottom:10px;'></div>", unsafe_allow_html=True)
    else:
        st.markdown("## BORELLI")
    
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
            
            if not df_desp.empty: 
                df_desp['Valor'] = pd.to_numeric(df_desp['Valor'], errors='coerce').fillna(0)
                
                def corrigir_descontos(row):
                    val = row['Valor']
                    plano = str(row.get('Plano de Contas', '')).upper()
                    if "DESCONTO" in plano and val > 0: return -val
                    return val
                df_desp['Valor'] = df_desp.apply(corrigir_descontos, axis=1)
                
                def cat_desp(p):
                    p = str(p).upper().strip()
                    if any(k in p for k in ['MÚTUO', 'MUTUO', 'INTERCOMPANY', 'APLICAÇÃO']): return "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO"
                    if any(k in p for k in ['SÓCIO', 'SOCIO', 'LUCRO', 'DISTRIBUIÇÃO', 'DIVIDENDO', 'PRÓ-LABORE']): return "7. DESPESAS DE SÓCIOS"
                    if any(k in p for k in ['SALÁRIO', 'VALE', 'FOLHA', 'FGTS', 'FÉRIAS', 'RESCISÃO', 'FUNCIONÁRIOS', 'FREELANCE', 'DIARISTA', 'MÉDICO', 'INSS', 'SINDICATO', 'VT', 'VR']): return "4. FOLHA DE PAGAMENTO & ENCARGOS"
                    if any(k in p for k in ['CMV', 'DESCARTÁVEIS', 'LEITE', 'INSUMO', 'BOBINA', 'FRUTA', 'COMPRAS', 'MERCADORIA']): return "1. FORNECEDORES / MERCADORIAS (CMV)"
                    if any(k in p for k in ['ICMS', 'IMPOSTO', 'FISCAL', 'DAS', 'TAXAS MUNICIPAIS', 'PIS', 'COFINS', 'ISS', 'SIMPLES']): return "2. IMPOSTOS SOBRE VENDAS"
                    if any(k in p for k in ['ALUGUEL', 'CONDOMÍNIO', 'ENERGIA', 'ÁGUA', 'IPTU', 'LUZ', 'INTERNET', 'SEGURO PREDIAL', 'TELEFONE']): return "3. DESPESAS DE OCUPAÇÃO"
                    if any(k in p for k in ['EMPRÉSTIMO', 'CAPITAL DE GIRO', 'JUROS', 'MULTA', 'TARIFA', 'TAXA', 'MAQUININHA', 'BANCÁRIA']): return "6. AMORTIZAÇÃO DE DÍVIDAS & CAPITAL"
                    if any(k in p for k in ['LIMPEZA', 'MANUTENÇÃO', 'CONTABILIDADE', 'MARKETING', 'IFOOD', 'SISTEMA', 'HONORÁRIO', 'MATERIAL']): return "5. DESPESAS OPERACIONAIS & VENDAS"
                    return "5. DESPESAS OPERACIONAIS & VENDAS"
                    
                df_desp["Categoria_CFO"] = df_desp["Plano de Contas"].apply(cat_desp)
            st.session_state.df_api_desp = df_desp

            df_rec = buscar_parcelas_f360(st.session_state.jwt, d_ini, d_fim, MAPA_CNPJ_LOJA, "Receita", log=log_rec)
            if not df_rec.empty:
                df_rec["Categoria_CFO"] = df_rec.apply(categorizar_receita, axis=1)
                df_rec["Tipo_Movimento"] = "RECEITA"
            st.session_state.df_api_rec = df_rec
            
            with open(CACHE_API_FILE, 'wb') as f:
                pickle.dump({'desp': df_desp, 'rec': df_rec}, f)
                
            st.success(f"🟢 API sincronizada! Despesas: {len(df_desp):,} | Receitas: {len(df_rec):,}")

    st.divider()
    st.markdown("### 🏦 Dados oficiais do caixa")
    file_fluxo_oficial = st.file_uploader("F360 > Fluxo de Caixa > Exportar", type=["xlsx"], accept_multiple_files=True, key=f"fluxo_uploader_{st.session_state.uploader_key}")
    file_tabela_csv = st.file_uploader("CSV Automático (opcional)", type=["csv"], key=f"csv_uploader_{st.session_state.uploader_key}") if HAS_DOM_PROCESSOR else None
    
    st.divider()
    if st.button("🧹 Limpar Memória", use_container_width=True):
        if os.path.exists(CACHE_API_FILE): os.remove(CACHE_API_FILE)
        if os.path.exists(CACHE_EXCEL_FILE): os.remove(CACHE_EXCEL_FILE)
        
        chaves_para_manter = ["autenticado", "uploader_key"]
        for chave in list(st.session_state.keys()):
            if chave not in chaves_para_manter:
                del st.session_state[chave]
                
        st.session_state.uploader_key += 1
        st.rerun()

    st.caption("🔐 A fonte oficial do saldo bancário é o export do Fluxo de Caixa. Limpe a memória sempre que subir arquivos novos.")
    st.divider()
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

# CARREGAMENTO DE ARQUIVOS
if file_fluxo_oficial: 
    st.session_state.fluxo_oficial_cache.update(carregar_fluxo_oficial(file_fluxo_oficial))
    with open(CACHE_EXCEL_FILE, 'wb') as f: pickle.dump(st.session_state.fluxo_oficial_cache, f)

if file_tabela_csv is not None and HAS_DOM_PROCESSOR:
    df_dom, saldo_ini_dom = processar_tabela_fluxo_dom(file_tabela_csv)
    st.session_state.fluxo_oficial_cache["CSV (via navegador)"] = {"df": df_dom, "saldo_inicial": saldo_ini_dom, "contas": []}
    with open(CACHE_EXCEL_FILE, 'wb') as f: pickle.dump(st.session_state.fluxo_oficial_cache, f)

fluxo_oficial = st.session_state.fluxo_oficial_cache
_lista_dfs = [d for d in [st.session_state.get("df_api_desp"), st.session_state.get("df_api_rec")] if d is not None and not d.empty]
df_api = pd.concat(_lista_dfs, ignore_index=True) if _lista_dfs else pd.DataFrame()

# ============================================================
# CABEÇALHO E FILTROS
# ============================================================
if LOGO_BASE64:
    header_html = f"""
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px; margin-bottom: 20px;">
        <div><img src="data:image/png;base64,{LOGO_BASE64}" style="max-height:60px; margin-bottom:5px;"><div class="hero-subtitle">Fluxo de Caixa · Controladoria</div></div>
        <div class="status-pill"><span class="status-dot"></span>F360 conectado</div>
    </div>"""
else:
    header_html = """
    <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px; margin-bottom: 20px;">
        <div><div class="hero-title">BORELLI</div><div class="hero-subtitle">Fluxo de Caixa · Controladoria</div></div>
        <div class="status-pill"><span class="status-dot"></span>F360 conectado</div>
    </div>"""
st.markdown(header_html, unsafe_allow_html=True)

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
# CÁLCULOS E SEPARAÇÃO: CAIXA (EXCEL) VS DRE (API)
# ============================================================
df_kpi = df_api.copy()
if not df_kpi.empty:
    if conta_selecionada not in ("Ver Todas as Contas", "CSV (via navegador)"): df_kpi = df_kpi[df_kpi['Empresa'] == conta_selecionada]
    if isinstance(date_range, tuple) and len(date_range) == 2: df_kpi = df_kpi[(df_kpi['Vencimento_dt'].dt.date >= date_range[0]) & (df_kpi['Vencimento_dt'].dt.date <= date_range[1])]

oficial = fluxo_oficial.get(conta_selecionada) or fluxo_oficial.get("Ver Todas as Contas") or fluxo_oficial.get("CSV (via navegador)")
if not oficial and len(fluxo_oficial) == 1: oficial = list(fluxo_oficial.values())[0]

# --- REGRA DE OURO DA CONTROLADORIA: O DATAFRAME DO EXCEL É INTOCÁVEL ---
df_of_exec = pd.DataFrame()
entradas_oficiais = 0.0
saidas_oficiais = 0.0
saldo_final_exec = None
saldo_atual_hoje = None # NOVO SALDO FIXO DO DIA

if oficial:
    df_of_exec = oficial["df"].copy()
    
    # 1. Pega o Saldo Real de Hoje ANTES de filtrar o calendário
    hoje = date.today()
    if not df_of_exec.empty:
        df_ate_hoje = df_of_exec[df_of_exec["Data"].dt.date <= hoje]
        saldo_atual_hoje = df_ate_hoje.iloc[-1]["Saldo"] if not df_ate_hoje.empty else df_of_exec.iloc[-1]["Saldo"]

    # 2. Aplica o filtro do calendário do utilizador
    if isinstance(date_range, tuple) and len(date_range) == 2: 
        df_of_exec = df_of_exec[(df_of_exec["Data"].dt.date >= date_range[0]) & (df_of_exec["Data"].dt.date <= date_range[1])]
    
    # 3. Calcula as métricas do período selecionado
    if not df_of_exec.empty:
        entradas_oficiais = df_of_exec["Total_Entradas"].sum()
        saidas_oficiais = df_of_exec["Total_Saidas"].sum()
        saldo_final_exec = df_of_exec.iloc[-1]["Saldo"]

# Variáveis da API (Bruto / Competência / Títulos)
df_rec_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'RECEITA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()
df_desp_kpi = df_kpi[(df_kpi['Tipo_Movimento'] == 'DESPESA') & (df_kpi['Categoria_CFO'] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")] if not df_kpi.empty else pd.DataFrame()

tot_rec_prev = df_rec_kpi['Valor'].sum() if not df_rec_kpi.empty else 0.0
tot_rec_real = df_rec_kpi[df_rec_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_rec_kpi.empty else 0.0
tot_prev = df_desp_kpi['Valor'].sum() if not df_desp_kpi.empty else 0.0
tot_real = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'REALIZADO']['Valor'].sum() if not df_desp_kpi.empty else 0.0
tot_pend = df_desp_kpi[df_desp_kpi['Status_Clean'] == 'PENDENTE']['Valor'].sum() if not df_desp_kpi.empty else 0.0

# Valores Consolidados Visão Executiva (Caixa Real do Banco + Pendências da API)
entradas_exec = entradas_oficiais
saidas_exec = saidas_oficiais + tot_pend
resultado_exec = entradas_exec - saidas_exec

# ============================================================
# ABAS DO DASHBOARD
# ============================================================
tabs = st.tabs(["📊 Visão Executiva", "📅 Fluxo Diário", "📋 DRE de Caixa", "🏪 Comparativo Por Loja"])

with tabs[0]:
    st.markdown('<div class="section-title">Resumo financeiro do período</div>', unsafe_allow_html=True)
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: st.markdown(f'<div class="kpi-card"><div class="kpi-label">💰 Entradas Reais</div><div class="kpi-value kpi-green">{brl(entradas_exec)}</div><div class="kpi-foot">Dinheiro liquidado no banco</div></div>', unsafe_allow_html=True)
    with c2: st.markdown(f'<div class="kpi-card"><div class="kpi-label">🔴 Saídas</div><div class="kpi-value kpi-red">{brl(saidas_exec)}</div><div class="kpi-foot">Caixa Pago + Pendente da API</div></div>', unsafe_allow_html=True)
    with c3: st.markdown(f'<div class="kpi-card"><div class="kpi-label">📈 Resultado</div><div class="kpi-value {"kpi-green" if resultado_exec >= 0 else "kpi-red"}">{brl(resultado_exec)}</div><div class="kpi-foot">Entradas − saídas do período</div></div>', unsafe_allow_html=True)
    with c4: st.markdown(f'<div class="kpi-card"><div class="kpi-label">🏦 Saldo Atual (Hoje)</div><div class="kpi-value {"kpi-green" if (saldo_atual_hoje or 0) >= 0 else "kpi-red"}">{brl(saldo_atual_hoje) if saldo_atual_hoje is not None else "—"}</div><div class="kpi-foot">{"Projeção do filtro: " + brl(saldo_final_exec) if saldo_final_exec is not None else "Extrato exato da conta"}</div></div>', unsafe_allow_html=True)
    with c5: st.markdown(f'<div class="kpi-card"><div class="kpi-label">⚠️ Em Aberto</div><div class="kpi-value {"kpi-green" if tot_pend == 0 else "kpi-yellow"}">{brl(tot_pend)}</div><div class="kpi-foot">{"Nenhuma pendência" if tot_pend == 0 else "Despesas pendentes na API"}</div></div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    if saldo_atual_hoje is not None and saldo_atual_hoje < 0:
        st.markdown('<div class="alert-danger">🔴 URGENTE: O saldo da sua conta bancária hoje está NEGATIVO.</div>', unsafe_allow_html=True)
    elif saldo_final_exec is not None and saldo_final_exec < 0: 
        st.markdown('<div class="alert-warn">🟡 Atenção: A projeção para o final do período selecionado ficará negativa.</div>', unsafe_allow_html=True)
    elif tot_pend > 0: 
        st.markdown(f'<div class="alert-warn">🟡 Atenção: existem {brl(tot_pend)} em despesas pendentes para o período.</div>', unsafe_allow_html=True)
    else: 
        st.markdown('<div class="alert-good">🟢 Conta Positiva e sem despesas pendentes identificadas.</div>', unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)

    g1, g2 = st.columns([1.75, 1])
    with g1:
        st.markdown('<div class="panel"><div class="panel-header"><div class="panel-title">Evolução do Caixa Bancário Diário</div><div class="muted">Excel</div></div></div>', unsafe_allow_html=True)
        if not df_of_exec.empty:
            chart_df = df_of_exec[["Data", "Total_Entradas", "Total_Saidas"]].copy()
            chart_df.columns = ["Data", "Entradas", "Saídas"]
            chart_df['Data_str'] = chart_df['Data'].dt.strftime('%d/%m')
            
            df_melt = chart_df.melt(id_vars=['Data_str'], value_vars=['Entradas', 'Saídas'], var_name='Tipo', value_name='Valor')
            
            def formata_k(val):
                if val < 100: return ""
                if val >= 1000: return f"{val/1000:.1f}K".replace(".0K", "K")
                return f"{val:.0f}"
                
            df_melt['Rotulo'] = df_melt['Valor'].apply(formata_k)
            max_y = df_melt['Valor'].max()
            max_y = max_y * 1.15 if pd.notna(max_y) and max_y > 0 else 100
            
            base = alt.Chart(df_melt).encode(
                x=alt.X("Data_str:O", title="", axis=alt.Axis(labelAngle=0)),
                xOffset="Tipo:N",
                y=alt.Y("Valor:Q", title="", scale=alt.Scale(domain=[0, max_y]), axis=alt.Axis(format="s", grid=True))
            )
            
            barras = base.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
                color=alt.Color("Tipo:N", scale=alt.Scale(domain=["Entradas", "Saídas"], range=["#45D483", "#FF6262"]), legend=alt.Legend(title="", orient="bottom")),
                tooltip=[alt.Tooltip("Data_str:O", title="Data"), alt.Tooltip("Tipo:N", title="Tipo"), alt.Tooltip("Valor:Q", title="R$", format=",.2f")]
            )
            textos = base.mark_text(align='center', baseline='bottom', dy=-8, fontSize=13, fontWeight="bold", color="#F8FAFC").encode(text=alt.Text('Rotulo:N'))
            
            st.altair_chart((barras + textos).properties(height=280), use_container_width=True)
        else: st.info("Anexe o export 'Fluxo de Caixa.xlsx' para visualizar o fluxo diário oficial.")

    with g2:
        st.markdown('<div class="panel"><div class="panel-header"><div class="panel-title">Composição das Despesas Brutas</div><div class="muted">API</div></div></div>', unsafe_allow_html=True)
        if not df_desp_kpi.empty:
            comp = df_desp_kpi.groupby("Categoria_CFO")["Valor"].sum().sort_values(ascending=True)
            comp.index = [str(x).replace("1. ", "").replace("2. ", "").replace("3. ", "").replace("4. ", "").replace("5. ", "").replace("6. ", "").replace("7. ", "") for x in comp.index]
            comp_df = comp.reset_index()
            comp_df.columns = ["Categoria", "Valor"]
            
            def formata_k_comp(val):
                if val < 10: return ""
                if val >= 1000: return f"{val/1000:.1f}K".replace(".0K", "K")
                return f"{val:.0f}"
                
            comp_df['Rotulo'] = comp_df['Valor'].apply(formata_k_comp)
            max_x = comp_df['Valor'].max()
            max_x = max_x * 1.2 if pd.notna(max_x) and max_x > 0 else 100
            
            base_comp = alt.Chart(comp_df).encode(
                x=alt.X("Valor:Q", title="", scale=alt.Scale(domain=[0, max_x]), axis=alt.Axis(format="s", grid=False)),
                y=alt.Y("Categoria:N", sort="-x", title="", axis=alt.Axis(labelAngle=0, labelLimit=300))
            )
            
            barras_comp = base_comp.mark_bar(color="#69B7FF", cornerRadiusEnd=3).encode(tooltip=[alt.Tooltip("Categoria:N", title="Categoria"), alt.Tooltip("Valor:Q", title="R$", format=",.2f")])
            textos_comp = base_comp.mark_text(align='left', baseline='middle', dx=5, fontSize=13, fontWeight="bold", color="#F8FAFC").encode(text=alt.Text('Rotulo:N'))
            
            st.altair_chart((barras_comp + textos_comp).properties(height=280), use_container_width=True)
        else: st.info("Sincronize a API para visualizar a composição das despesas.")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-title">📅 Projeção Intocável do Saldo Bancário</div>', unsafe_allow_html=True)
    if not df_of_exec.empty:
        proj = df_of_exec[["Data", "Total_Entradas", "Total_Saidas", "Saldo"]].copy()
        proj.columns = ["Data", "Entradas", "Saídas", "Saldo"]
        proj['Data'] = pd.to_datetime(proj['Data']).dt.strftime('%d/%m/%Y')
        def colorir_saldo(val):
            if isinstance(val, (int, float)):
                if val < 0: return 'color: #FF6262; font-weight: bold;'
                elif val > 0: return 'color: #45D483; font-weight: bold;'
            return ''
        try:
            st.dataframe(proj.tail(10).style.format({"Entradas": "R$ {:,.2f}", "Saídas": "R$ {:,.2f}", "Saldo": "R$ {:,.2f}"}).map(colorir_saldo, subset=['Saldo']), use_container_width=True, hide_index=True)
        except:
            st.dataframe(proj.tail(10), use_container_width=True, hide_index=True)

with tabs[1]:
    if oficial:
        df_cards = df_of_exec.copy()

        if not df_api.empty:
            df_cards_api = df_kpi.copy()
            rec_cards = df_cards_api[(df_cards_api["Tipo_Movimento"] == "RECEITA") & (df_cards_api["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
            prev_rec = rec_cards["Valor"].sum() if not rec_cards.empty else 0.0
            liq_rec = rec_cards[rec_cards["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not rec_cards.empty else 0.0
            aberto_rec = rec_cards[rec_cards["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not rec_cards.empty else max(prev_rec - liq_rec, 0)
            
            st.markdown("#### Lançamentos do período (Venda Bruta vs Líquido Bancário)")
            st.caption("A API reflete o momento da venda. O extrato reflete o dinheiro líquido creditado no banco no dia.")
            render_movement_cards(prev_rec, liq_rec, aberto_rec, "Receitas API", df_detail=rec_cards, state_prefix="fluxo_receitas")
            st.markdown("<br>", unsafe_allow_html=True)
            
            desp_cards = df_cards_api[(df_cards_api["Tipo_Movimento"] == "DESPESA") & (df_cards_api["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
            prev_cards = desp_cards["Valor"].sum() if not desp_cards.empty else 0.0
            liq_cards = desp_cards[desp_cards["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not desp_cards.empty else 0.0
            aberto_cards = desp_cards[desp_cards["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not desp_cards.empty else max(prev_cards - liq_cards, 0)
            render_movement_cards(prev_cards, liq_cards, aberto_cards, "Despesas API", df_detail=desp_cards, state_prefix="fluxo_despesas")
        else:
            entradas = df_cards["Total_Entradas"].sum() if not df_cards.empty else 0.0
            saidas = df_cards["Total_Saidas"].sum() if not df_cards.empty else 0.0
            st.markdown("#### Movimentação oficial do caixa")
            render_movement_cards(entradas, entradas, 0.0, "Entradas Banco", df_detail=None, state_prefix="fluxo_oficial_ent")
            st.markdown("<br>", unsafe_allow_html=True)
            render_movement_cards(saidas, saidas, 0.0, "Saídas Banco", df_detail=None, state_prefix="fluxo_oficial_sai")

    if oficial and not df_cards.empty:
        st.markdown("<hr>", unsafe_allow_html=True)
        st.markdown("#### Extrato Bancário Exato (F360)")
        dias_of = sorted(df_cards["Dia"].unique().tolist())
        linhas_of = [
            {"Linha de Extrato": "1. (+) Cartões", **dict(zip(df_cards["Dia"], df_cards.get("Cartoes", 0)))},
            {"Linha de Extrato": "2. (+) PIX / Boleto / Transferências", **dict(zip(df_cards["Dia"], df_cards.get("Boleto", 0) + df_cards.get("Outros_Recebimentos", 0)))},
            {"Linha de Extrato": "3. (+) Orçamento (Entrada Prevista)", **dict(zip(df_cards["Dia"], df_cards.get("Orcamento_Entrada", 0)))},
            {"Linha de Extrato": "4. (=) Total de Entradas (Líquido)", **dict(zip(df_cards["Dia"], df_cards.get("Total_Entradas", 0)))},
            {"Linha de Extrato": "5. (-) Total de Saídas (Real + Orç)", **dict(zip(df_cards["Dia"], df_cards.get("Total_Saidas", 0)))},
            {"Linha de Extrato": "6. 🏦 SALDO FINAL BANCÁRIO", **dict(zip(df_cards["Dia"], df_cards.get("Saldo", 0)))},
        ]
        df_display = pd.DataFrame(linhas_of)[["Linha de Extrato"] + dias_of]
        
        def format_currency(val):
            if isinstance(val, (int, float)): return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return val
            
        try:
            st.dataframe(df_display.style.apply(highlight_saldo, axis=1).format({d: format_currency for d in dias_of}), use_container_width=True, hide_index=True)
        except:
            st.dataframe(df_display, use_container_width=True, hide_index=True)

with tabs[2]:
    st.subheader("DRE de Caixa — Visão Gerencial por Competência")
    if not df_api.empty:
        st.markdown("#### Lançamentos Brutos da DRE (API)")
        rec_prev_dre = df_rec_kpi["Valor"].sum() if not df_rec_kpi.empty else 0.0
        rec_liq_dre = df_rec_kpi[df_rec_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not df_rec_kpi.empty else 0.0
        rec_aberto_dre = df_rec_kpi[df_rec_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not df_rec_kpi.empty else max(rec_prev_dre - rec_liq_dre, 0)
        desp_prev_dre = df_desp_kpi["Valor"].sum() if not df_desp_kpi.empty else 0.0
        desp_liq_dre = df_desp_kpi[df_desp_kpi["Status_Clean"] == "REALIZADO"]["Valor"].sum() if not df_desp_kpi.empty else 0.0
        desp_aberto_dre = df_desp_kpi[df_desp_kpi["Status_Clean"] == "PENDENTE"]["Valor"].sum() if not df_desp_kpi.empty else max(desp_prev_dre - desp_liq_dre, 0)

        render_movement_cards(rec_prev_dre, rec_liq_dre, rec_aberto_dre, "Receitas Brutas", df_detail=df_rec_kpi, state_prefix="dre_receitas")
        st.markdown("<br>", unsafe_allow_html=True)
        render_movement_cards(desp_prev_dre, desp_liq_dre, desp_aberto_dre, "Despesas Brutas", df_detail=df_desp_kpi, state_prefix="dre_despesas")
        st.caption("A DRE é baseada em competência. Taxas de maquininha estão nas saídas operacionais.")
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
        
        def colorir_linha_dre(row):
            styles = [''] * len(row)
            cat = str(row.iloc[0])
            if "(=) EBITDA" in cat:
                for i, val in enumerate(row):
                    if i > 0 and isinstance(val, str):
                        try:
                            v = float(val.replace('R$ ', '').replace('.', '').replace(',', '.'))
                            if v < 0: styles[i] = 'color: #FF6262; font-weight: bold;'
                            elif v > 0: styles[i] = 'color: #45D483; font-weight: bold;'
                        except: pass
            elif "8. TOTAL SAÍDAS" in cat:
                styles = ['font-weight: bold; border-top: 1px solid #303A46;'] * len(row)
            return styles

        try:
            st.dataframe(pd.DataFrame(dre_list).style.apply(colorir_linha_dre, axis=1), use_container_width=True, hide_index=True)
        except:
            st.dataframe(pd.DataFrame(dre_list), use_container_width=True)
    else: st.warning("Sincronize a API no menu lateral para visualizar o DRE.")

with tabs[3]:
    st.subheader("Comparativo Por Loja — Vendas e Despesas (API)")
    if not df_api.empty:
        df_filtered_loja = df_kpi.copy()
        tem_loja = "Empresa_Loja" in df_filtered_loja.columns and df_filtered_loja["Empresa_Loja"].replace("", np.nan).notna().any()
        dimensao = "Empresa_Loja" if tem_loja else "Empresa"

        df_desp_loja = df_filtered_loja[(df_filtered_loja["Tipo_Movimento"] == "DESPESA") & (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]
        df_rec_loja = df_filtered_loja[(df_filtered_loja["Tipo_Movimento"] == "RECEITA") & (df_filtered_loja["Categoria_CFO"] != "7. TRANSFERÊNCIAS INTERCOMPANY / MÚTUO")]

        def formatar_tabela_loja_sem_zero(val):
            if isinstance(val, (int, float)):
                if val == 0: return "—"
                return f"R$ {val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
            return val

        if not df_desp_loja.empty:
            st.markdown("**Despesas por categoria**")
            pivot_desp = df_desp_loja.pivot_table(index="Categoria_CFO", columns=dimensao, values="Valor", aggfunc="sum", fill_value=0)
            try:
                st.dataframe(pivot_desp.style.format(formatar_tabela_loja_sem_zero), use_container_width=True)
            except:
                st.dataframe(pivot_desp, use_container_width=True)

        if not df_rec_loja.empty:
            st.markdown("**Resumo Operacional (Receita x Despesa)**")
            resumo_rec = df_rec_loja.groupby(dimensao)["Valor"].sum().to_frame("Receita de Vendas Bruta")
            resumo_desp = df_desp_loja.groupby(dimensao)["Valor"].sum().to_frame("Despesas Brutas") if not df_desp_loja.empty else pd.DataFrame()
            resumo = resumo_rec.join(resumo_desp, how="outer").fillna(0)
            resumo["Resultado"] = resumo["Receita de Vendas Bruta"] - resumo.get("Despesas Brutas", 0)
            
            def style_loja_resultado(val):
                if isinstance(val, (int, float)):
                    if val < 0: return 'color: #FF6262; font-weight: bold;'
                    elif val > 0: return 'color: #45D483; font-weight: bold;'
                return ''
                
            try:
                st.dataframe(resumo.style.format(formatar_tabela_loja_sem_zero).map(style_loja_resultado, subset=["Resultado"]), use_container_width=True)
            except:
                st.dataframe(resumo, use_container_width=True)

    else: st.warning("Sincronize a API para gerar o comparativo entre as lojas.")