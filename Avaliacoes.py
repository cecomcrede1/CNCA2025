# --------------------------------------------------------------------------
# PAINEL DE RESULTADOS CECOM CREDE 01 2025 - VERSÃO MELHORADA
# --------------------------------------------------------------------------

import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go
import indicadores
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import logging
from pathlib import Path

# --------------------------------------------------------------------------
# 1. CONFIGURAÇÕES E CONSTANTES
# --------------------------------------------------------------------------

@dataclass
class ConfigApp:
    """Classe para centralizar configurações da aplicação"""
    PAGE_TITLE: str = "CECOM/CREDE 01 - Painel de Resultados"
    PAGE_ICON: str = "painel_cecom.png"
    LAYOUT: str = "wide"
    
    # URLs e endpoints
    API_URL: str = "https://criancaalfabetizada.caeddigital.net/portal/functions/getDadosResultado"
    
    # Timeout para requisições
    REQUEST_TIMEOUT: int = 30
    
    # Etapas disponíveis
    ETAPAS: set = frozenset({1, 2, 3, 4, 5})
    
    # Ciclos de avaliação
    CICLOS: Dict[str, str] = frozenset({
        "1": "1º Ciclo",
        "2": "2º Ciclo",
    }.items())
    
    # Componentes curriculares
    COMPONENTES: Dict[str, str] = frozenset({
        "Língua Portuguesa": "LÍNGUA PORTUGUESA",
        "Matemática": "MATEMÁTICA"
    }.items())
    
    # Escolas indígenas (códigos conhecidos)
    ESCOLAS_INDIGENAS: set = frozenset({
        "23000291", "23244755", "23239174", "23564067", "23283610", 
        "23215674", "23263423", "23061642", "23462353", "23062770",
        "23241462", "23235411", "23241454", "23215682", "23263555"
    })

# Instância global da configuração
config = ConfigApp()

# --------------------------------------------------------------------------
# 2. CONFIGURAÇÃO INICIAL E LOGGING
# --------------------------------------------------------------------------

def configurar_pagina():
    """Configura a página do Streamlit"""
    st.set_page_config(
        page_title=config.PAGE_TITLE,
        page_icon=config.PAGE_ICON,
        layout=config.LAYOUT,
        initial_sidebar_state="expanded"
    )

def inicializar_sessao():
    """Inicializa variáveis de sessão"""
    session_defaults = {
        'authenticated': False,
        'codigo': None,
        'dados_cache': {}
    }
    
    for key, value in session_defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def exibir_logos():
    """Exibe os logos institucionais"""
    logos = [
        ("BrasilMEC.png", 250),
        ("logo_governo_preto_SEDUC.png", 250),
        ("crede.png", 200)
    ]
    
    cols = st.columns([0.3, 0.3, 0.3])
    
    for i, (logo, width) in enumerate(logos):
        with cols[i]:
            if Path(logo).exists():
                st.image(logo, width=width)
            else:
                st.warning(f"Logo {logo} não encontrado")
    
    # Logo adicional na última coluna
    with cols[2]:
        if Path("cecom.png").exists():
            st.image("cecom.png", width=100)

def carregar_credenciais() -> Tuple[Dict, Dict, str, str]:
    """Carrega credenciais de forma segura"""
    try:
        usuarios = st.secrets["users"]
        escolas = st.secrets["schools"]
        installation_id = st.secrets["api"]["installation_id"]
        session_token = st.secrets["api"]["session_token"]
        
        return usuarios, escolas, installation_id, session_token
        
    except KeyError as e:
        st.error(f" Erro na configuração: {e}. Verifique o arquivo secrets.toml")
        st.stop()

# --------------------------------------------------------------------------
# 3. CLASSES DE DADOS
# --------------------------------------------------------------------------

@dataclass
class PayloadBase:
    """Classe base para payloads da API"""
    entidade: str
    componente: str
    etapa: int
    ciclo: str
    installation_id: str
    session_token: str
    
    def _criar_filtros_base(self) -> List[Dict]:
        """Cria filtros básicos comuns"""
        return [
            {"operation": "equalTo", "field": "DADOS.VL_FILTRO_DISCIPLINA", "value": dict(config.COMPONENTES)[self.componente]},
            {"operation": "equalTo", "field": "DADOS.VL_FILTRO_ETAPA", "value": f"ENSINO FUNDAMENTAL DE 9 ANOS - {self.etapa}º ANO"},
            {"operation": "equalTo", "field": "DADOS.VL_FILTRO_AVALIACAO", "value": f"AV{self.ciclo}2025"},
        ]
    
    def _criar_payload_base(self, indicadores_list: List, filtros_extras: List = None) -> Dict:
        """Cria estrutura base do payload"""
        filtros_extras = filtros_extras or []
        
        # Determinar dependência com base no código da entidade
        dependencia = "MUNICIPAL" if self.entidade in st.secrets["users"] or (self.entidade not in st.secrets["users"] and self.entidade not in config.ESCOLAS_INDIGENAS) else "ESTADUAL"
        print(dependencia)
        return {
            "CD_INDICADOR": indicadores_list,
            "agregado": self.entidade,
            "filtros": self._criar_filtros_base() + filtros_extras,
            "filtrosAdicionais": [{"field": "DADOS.VL_FILTRO_REDE", "value": dependencia, "operation": "equalTo"}],
            "ordenacao": [["NM_ENTIDADE", "ASC"]], 
            "nivelAbaixo": "0", 
            "collectionResultado": None, 
            "CD_INDICADOR_LABEL": [], 
            "TP_ENTIDADE_LABEL": "01",
            "_ApplicationId": "portal", 
            "_ClientVersion": "js2.19.0", 
            "_InstallationId": self.installation_id,
            "_SessionToken": self.session_token
        }

class PayloadGeral(PayloadBase):
    """Payload para dados gerais"""
    
    def criar_payload(self) -> Dict:
        return self._criar_payload_base(list(indicadores.INDIC_GERAL))

class PayloadHabilidades(PayloadBase):
    """Payload para dados de habilidades"""
    
    def criar_payload(self) -> Dict:
        filtros_extras = [
            {"operation": "containedIn", "field": "DADOS.DC_FAIXA_PERCENTUAL_HABILIDADE", 
             "value": ["Alto", "Médio Baixo", "Médio Alto", "Baixo"]}
        ]
        
        payload = self._criar_payload_base(list(indicadores.INDIC_HABILIDADES), filtros_extras)
        payload["ordenacao"] = [["DADOS.CD_HABILIDADE", "ASC"]]
        
        return payload

# --------------------------------------------------------------------------
# 4. CLASSE PARA API
# --------------------------------------------------------------------------

class APIClient:
    """Cliente para comunicação com a API"""
    
    def __init__(self, base_url: str = config.API_URL, timeout: int = config.REQUEST_TIMEOUT):
        self.base_url = base_url
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
    
    @st.cache_data(ttl=300)  # Cache por 5 minutos
    def requisitar_dados(_self, payload: Dict) -> Optional[Dict]:
        """
        Faz requisição para a API com cache e tratamento de erros robusto
        
        Args:
            payload: Dados da requisição
            
        Returns:
            Resposta da API ou None em caso de erro
        """
        try:
            with st.spinner("Carregando dados..."):
                response = requests.post(
                    _self.base_url, 
                    json=payload, 
                    headers=_self.headers, 
                    timeout=_self.timeout
                )
                response.raise_for_status()
                return response.json()
                
        except requests.exceptions.Timeout:
            st.error("⏱Tempo limite esgotado. Tente novamente.")
        except requests.exceptions.ConnectionError:
            st.error("Erro de conexão. Verifique sua internet.")
        except requests.exceptions.HTTPError as e:
            st.error(f"Erro HTTP {response.status_code}: {e}")
        except requests.exceptions.RequestException as e:
            st.error(f"Erro na requisição: {e}")
        except Exception as e:
            st.error(f"Erro inesperado: {e}")
            
        return None

# --------------------------------------------------------------------------
# 5. PROCESSAMENTO DE DADOS
# --------------------------------------------------------------------------

class ProcessadorDados:
    """Classe para processar dados da API"""
    
    @staticmethod
    def processar_dados_gerais(resposta: Dict, ciclo_label: str) -> Optional[pd.DataFrame]:
        """Processa dados gerais da API"""
        if not resposta or "result" not in resposta or not resposta["result"]:
            return None
            
        df = pd.DataFrame(resposta["result"])
        if df.empty:
            return None
            
        # Adicionar ciclo e converter colunas numéricas
        df["Ciclo"] = ciclo_label
        colunas_numericas = ['TX_ACERTOS', 'TX_PARTICIPACAO', 'QT_PREVISTO', 'QT_EFETIVO', 'NU_N01', 'NU_N02', 'NU_N03']
        
        for col in colunas_numericas:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
        
        # Limpar nome da etapa
        if 'VL_FILTRO_ETAPA' in df.columns:
            df['VL_FILTRO_ETAPA'] = df['VL_FILTRO_ETAPA'].str.replace('ENSINO FUNDAMENTAL DE 9 ANOS - ', '')
        
        return df
    
    @staticmethod
    def processar_dados_habilidades(resposta: Dict, ciclo_label: str) -> Optional[pd.DataFrame]:
        """Processa dados de habilidades da API"""
        if not resposta or "result" not in resposta or not resposta["result"]:
            return None
            
        df = pd.DataFrame(resposta["result"])
        if df.empty:
            return None
            
        # Adicionar ciclo e converter colunas numéricas
        df["Ciclo"] = ciclo_label
        df['TX_ACERTO'] = pd.to_numeric(df['TX_ACERTO'], errors='coerce')
        
        # Limpar nome da etapa
        if 'VL_FILTRO_ETAPA' in df.columns:
            df['VL_FILTRO_ETAPA'] = df['VL_FILTRO_ETAPA'].str.replace('ENSINO FUNDAMENTAL DE 9 ANOS - ', '')
        
        return df

# --------------------------------------------------------------------------
# 6. AUTENTICAÇÃO
# --------------------------------------------------------------------------

class GerenciadorAuth:
    """Gerenciador de autenticação"""
    
    def __init__(self, usuarios: Dict, escolas: Dict):
        self.usuarios = usuarios
        self.escolas = escolas
        self.todos_usuarios = {**usuarios, **escolas}
    
    def renderizar_login(self):
        """Renderiza interface de login"""
        st.sidebar.image("painel_cecom.png")
        st.sidebar.title("🔐 Autenticação")
        
        with st.sidebar.form("login_form"):
            codigo_input = st.text_input("Código do Município ou Escola", placeholder="Digite seu código")
            senha_input = st.text_input("Senha", type="password", placeholder="Digite sua senha")
            submitted = st.form_submit_button("🚪 Entrar", use_container_width=True)
            
            if submitted:
                if self._validar_credenciais(codigo_input, senha_input):
                    st.session_state.authenticated = True
                    st.session_state.codigo = codigo_input
                    st.sidebar.success("Login realizado com sucesso!")
                    st.rerun()
                else:
                    st.sidebar.error("Código ou senha inválidos.")
    
    def _validar_credenciais(self, codigo: str, senha: str) -> bool:
        """Valida credenciais do usuário"""
        return codigo in self.todos_usuarios and self.todos_usuarios[codigo] == senha
    
    def renderizar_sidebar_logado(self):
        """Renderiza sidebar para usuário autenticado"""
        st.sidebar.image("painel_cecom.png")
        with st.sidebar.expander("Usuário Logado", expanded=True):
            codigo = st.session_state.codigo
            tipo_usuario = self._determinar_tipo_usuario(codigo)
            
            st.success(f"**Código:** {codigo}")
            st.info(f"**Tipo:** {tipo_usuario}")
            
            if st.button("Sair", use_container_width=True):
                self._fazer_logout()
    
    def _determinar_tipo_usuario(self, codigo: str) -> dict:
        """Determina o tipo de usuário baseado no código"""

        if codigo in self.usuarios:
            return "Municipal"
        elif codigo in config.ESCOLAS_INDIGENAS:
            return "Escola Indígena"

    
    def _fazer_logout(self):
        """Realiza logout do usuário"""
        st.session_state.authenticated = False
        st.session_state.codigo = None
        st.session_state.dados_cache = {}
        st.rerun()

# --------------------------------------------------------------------------
# 7. VISUALIZAÇÕES
# --------------------------------------------------------------------------

class GeradorGraficos:
    """Classe para gerar gráficos e visualizações"""
    
    @staticmethod
    def criar_grafico_habilidades(df_habilidades: pd.DataFrame) -> go.Figure:
        """Cria gráfico de barras para habilidades"""
        if df_habilidades.empty:
            return None
            
        fig = px.bar(
            df_habilidades,
            x='DC_HABILIDADE',
            y='TX_ACERTO',
            title='Taxa de Acertos por Habilidades por Ciclo',
            text=df_habilidades['TX_ACERTO'].round(1),
            color='Ciclo',
            color_discrete_map={"1º Ciclo": "#98FB98", "2º Ciclo": "#228B22"},
            labels={
                'TX_ACERTO': 'Taxa de Acertos (%)', 
                'Ciclo': 'Ciclo de Avaliação',
                'DC_HABILIDADE': 'Habilidade'
            },
            hover_data=['CD_HABILIDADE'],
            range_y=[0, 109]
        )
        
        # Personalizações
        fig.update_traces(
            textfont=dict(size=18),
            textposition='outside',
            hovertemplate="<b>Habilidade:</b> %{customdata[0]}<br>" +
                         "<b>Taxa de Acerto:</b> %{y:.1f}%<br>" +
                         "<b>Descrição:</b> %{x}<br>" +
                         "<extra></extra>",
            hoverlabel=dict(font_size=14)
        )
        
        fig.update_layout(
            showlegend=True,
            barmode='group',
            yaxis=dict(dtick=10, title_font=dict(size=14), tickfont=dict(size=12)),
            xaxis=dict(showticklabels=False, title_font=dict(size=14)),
            height=400
        )
        
        return fig
    
    @staticmethod
    def criar_gauge_participacao(valor: float, cor: str) -> go.Figure:
        """Cria gráfico gauge para participação"""
        fig = go.Figure(go.Indicator(
            mode="gauge+number",
            value=valor,
            number={'suffix': '%'},
            gauge={
                'axis': {'range': [0, 100]},
                'bar': {'color': cor},
                'steps': [
                    {'range': [0, 80], 'color': "##c1e8cb"},
                    {'range': [80, 90], 'color': "#ffc400"},
                    {'range': [90, 100], 'color': "#ff0022"}
                ],
                'threshold': {
                    'line': {'color': "red", 'width': 4},
                    'thickness': 0.85,
                    'value': 100
                }
            }
        ))
        
        fig.update_layout(height=200, margin=dict(l=10, r=10, t=30, b=10))
        return fig
    
    @staticmethod
    def criar_grafico_evolucao_niveis(df_geral: pd.DataFrame) -> go.Figure:
        """Cria gráfico de evolução dos níveis em barras horizontais"""
        if df_geral.empty:
            return None
        
        # Garantir que as colunas sejam numéricas
        colunas_niveis = ['NU_N01', 'NU_N02', 'NU_N03']
        for col in colunas_niveis:
            if col in df_geral.columns:
                df_geral[col] = pd.to_numeric(df_geral[col], errors='coerce')
        
        # Agrupar por ciclo e calcular médias para evitar duplicatas
        df_agrupado = df_geral.groupby('Ciclo').agg({
            'NU_N01': 'mean',
            'NU_N02': 'mean', 
            'NU_N03': 'mean'
        }).reset_index()
        
        # Ordenar pelos ciclos
        ordem_ciclos = ["2º Ciclo", "1º Ciclo"]
        df_agrupado['Ciclo'] = pd.Categorical(df_agrupado['Ciclo'], categories=ordem_ciclos, ordered=True)
        df_agrupado = df_agrupado.sort_values('Ciclo')
        
        fig = go.Figure()
        
        # Configurações das barras
        barras_config = [
            ('NU_N01', 'Defasagem', '#FF4444'),
            ('NU_N02', 'Aprendizado Intermediário', '#FFA500'),
            ('NU_N03', 'Aprendizado Adequado', '#32CD32')
        ]
        
        for coluna, nome, cor in barras_config:
            if coluna in df_agrupado.columns:
                valores = df_agrupado[coluna].fillna(0)
                
                fig.add_trace(go.Bar(
                    y=df_agrupado['Ciclo'].astype(str),  # eixo Y (categorias)
                    x=valores,                           # valores no eixo X
                    name=nome,
                    orientation='h',                     # barras horizontais
                    marker=dict(color=cor),
                    text=[f"{v:.0f}" for v in valores], # labels com %
                    textposition='inside',
                    hovertemplate=f"<b>{nome}</b><br>" +
                                "Ciclo: %{y}<br>" +
                                "Quantidade de Estudantes: %{x:.1f}<br>" +
                                "<extra></extra>"
                ))
                
                fig.update_layout(
                    barmode='stack',  # barras lado a lado
                    title=dict(
                        text='Evolução dos Níveis de Aprendizagem',
                        font=dict(size=18),
                        x=0.5
                    ),
                    xaxis=dict(
                        title='Quantidade de Estudantes',
                        tickfont=dict(size=16)
                    ),
                    yaxis=dict(
                        title='Ciclo',
                        tickfont=dict(size=16)
                    ),
                    legend=dict(font=dict(size=18)),
                    bargap=0.3
                )
                # aumentar tamanho dos rótulos
                fig.update_traces(
                    textfont=dict(size=20),
                    textposition='inside'
                )
        
        return fig

# --------------------------------------------------------------------------
# 8. INTERFACE PRINCIPAL
# --------------------------------------------------------------------------

class PainelResultados:
    """Classe principal do painel"""
    
    def __init__(self):
        self.usuarios, self.escolas, self.installation_id, self.session_token = carregar_credenciais()
        self.auth_manager = GerenciadorAuth(self.usuarios, self.escolas)
        self.api_client = APIClient()
        self.processador = ProcessadorDados()
        self.gerador_graficos = GeradorGraficos()
    
    def executar(self):
        """Executa a aplicação principal"""
        configurar_pagina()
        inicializar_sessao()
        exibir_logos()
        
        if not st.session_state.authenticated:
            self._renderizar_tela_login()
        else:
            self._renderizar_painel_principal()
    
    def _renderizar_tela_login(self):
        """Renderiza tela de login"""
        self.auth_manager.renderizar_login()
        "---"
        st.sidebar.info("Faça login para acessar o painel de resultados.")
        st.header("Painel de Resultados – CECOM/CREDE 01")
        "---"
        st.markdown("""
                    Bem-vindo ao Painel de Resultados da CREDE 01.
Este espaço foi desenvolvido pelo Cecom/CREDE 01 com o objetivo de disponibilizar, de forma clara e acessível, os principais dados das avaliações externas realizadas em nossa regional.

Nosso propósito é oferecer aos municípios e escolas um compilado de informações que facilite a análise dos resultados e apoie a tomada de decisões pedagógicas no chão da escola.

Aqui você encontrará:

- Indicadores consolidados por município e escola;

- Resultados por etapa, turma e componente curricular;

- Evolução das aprendizagens e níveis de proficiência;

- Ferramentas de visualização interativa para apoiar o acompanhamento e o planejamento.

O painel foi pensado para aproximar os dados da prática pedagógica, fortalecendo o trabalho coletivo de gestores, professores e equipes escolares, em prol da melhoria da aprendizagem de nossos estudantes.""")
        
    
    def _renderizar_painel_principal(self):
        """Renderiza painel principal"""
        self.auth_manager.renderizar_sidebar_logado()
        
        st.title("Painel de Resultados das Avaliações - CECOM/CREDE 01")
        st.sidebar.header("🔧 Filtros")
        
        # Seletores
        entidade_input = st.session_state.codigo
        selecao_etapa = st.sidebar.selectbox(
            "Selecione a etapa",
            options=sorted(list(config.ETAPAS)),
            format_func=lambda ano: f"{ano}º Ano"
        )
        selecao_componente = st.sidebar.selectbox(
            "Selecione o componente",
            options=list(dict(config.COMPONENTES).keys())
        )
        
        # Buscar e processar dados
        dados_gerais, dados_habilidades = self._buscar_dados(
            entidade_input, selecao_componente, selecao_etapa
        )
        
        if dados_gerais or dados_habilidades:
            self._exibir_resultados(dados_gerais, dados_habilidades)
        else:
            st.error("Nenhum dado encontrado para os filtros selecionados.")
    
    def _buscar_dados(self, entidade: str, componente: str, etapa: int) -> Tuple[List[pd.DataFrame], List[pd.DataFrame]]:
        """Busca dados da API para todos os ciclos"""
        dados_gerais_coletados = []
        dados_habilidades_coletados = []
        
        for ciclo_key, ciclo_label in dict(config.CICLOS).items():
            # Dados gerais
            payload_geral = PayloadGeral(
                entidade, componente, etapa, ciclo_key, 
                self.installation_id, self.session_token
            ).criar_payload()
            
            resposta_geral = self.api_client.requisitar_dados(payload_geral)
            df_geral = self.processador.processar_dados_gerais(resposta_geral, ciclo_label)
            
            if df_geral is not None:
                dados_gerais_coletados.append(df_geral)
            
            # Dados de habilidades
            payload_habilidades = PayloadHabilidades(
                entidade, componente, etapa, ciclo_key,
                self.installation_id, self.session_token
            ).criar_payload()
            
            resposta_habilidades = self.api_client.requisitar_dados(payload_habilidades)
            df_habilidades = self.processador.processar_dados_habilidades(resposta_habilidades, ciclo_label)
            
            if df_habilidades is not None:
                dados_habilidades_coletados.append(df_habilidades)
        
        return dados_gerais_coletados, dados_habilidades_coletados
    
    def _exibir_resultados(self, dados_gerais: List[pd.DataFrame], dados_habilidades: List[pd.DataFrame]):
        """Exibe resultados consolidados"""
        st.subheader("Visão Consolidada dos Ciclos 1 e 2")
        
        # Consolidar dados
        df_geral_consolidado = pd.concat(dados_gerais, ignore_index=True) if dados_gerais else pd.DataFrame()
        df_habilidades_consolidado = pd.concat(dados_habilidades, ignore_index=True) if dados_habilidades else pd.DataFrame()
        
        # Exibir métricas básicas
        if not df_geral_consolidado.empty:
            self._exibir_metricas_basicas(df_geral_consolidado)
            st.divider()
        
        # Exibir tabelas
        # self._exibir_tabelas_dados(df_geral_consolidado, df_habilidades_consolidado)
        
        # Exibir gráficos
        self._exibir_graficos(df_geral_consolidado, df_habilidades_consolidado)
        
        # Análise top 5
        if not df_habilidades_consolidado.empty:
            self._exibir_analise_top5(df_habilidades_consolidado)
    
    def _exibir_metricas_basicas(self, df: pd.DataFrame):
        """Exibe métricas básicas do município/escola"""
        info = df.iloc[0]
        
        st.metric("Entidade", info['NM_ENTIDADE'])
        
        col1, col2 = st.columns([0.3, 0.7])
        with col1:
            st.metric("Etapa", info['VL_FILTRO_ETAPA'])
        with col2:
            st.metric("Componente", info['VL_FILTRO_DISCIPLINA'])
    
    def _exibir_tabelas_dados(self, df_geral: pd.DataFrame, df_habilidades: pd.DataFrame):
        """Exibe tabelas de dados"""
        col1, col2 = st.columns(2)
        
        with col1:
            if not df_geral.empty:
                st.expander("🔍 Mostrar dados gerais", expanded=False)
                st.write("**Dados Gerais Consolidados**")
                st.dataframe(df_geral, use_container_width=True, hide_index=True)
        
        with col2:
            if not df_habilidades.empty:
                st.expander("🔍 Mostrar dados de habilidades", expanded=False)
                st.write("**Dados de Habilidades Consolidados**")
                st.dataframe(df_habilidades, use_container_width=True, hide_index=True)
    
    def _exibir_graficos(self, df_geral: pd.DataFrame, df_habilidades: pd.DataFrame):
        """Exibe gráficos principais"""
        st.subheader("Resultados")
        st.divider()
        
        col1, col2 = st.columns([0.3, 0.7])
        
        with col1:
            if not df_geral.empty:
                # Calcular médias por ciclo
                medias = df_geral.groupby('Ciclo')['TX_ACERTOS'].mean()
                
                st.markdown("##### Proficiência Média")
                for ciclo in ["1º Ciclo", "2º Ciclo"]:
                    if ciclo in medias.index:
                        delta = medias[ciclo] - medias.get("1º Ciclo", 0) if ciclo == "2º Ciclo" else None
                        st.metric(
                            ciclo, 
                            f"{medias[ciclo]:.1f}%", 
                            delta=f"{delta:.1f}%" if delta is not None else None,
                        )
        
        with col2:
            if not df_habilidades.empty:
                st.markdown("##### Taxa de Acertos por Habilidades")
                fig_habilidades = self.gerador_graficos.criar_grafico_habilidades(df_habilidades)
                if fig_habilidades:
                    st.plotly_chart(fig_habilidades, use_container_width=True)
        
        # Gráficos de participação
        if not df_geral.empty:
            self._exibir_participacao(df_geral)
        
        # Gráfico de evolução
        if not df_geral.empty:
            st.divider()
            st.markdown("##### Distribuição dos Estudantes por Nível de Aprendizagem")
            
            # Debug: mostrar dados disponíveis
            if st.checkbox("🔍 Mostrar dados dos níveis (debug)", key="debug_niveis"):
                st.write("**Dados disponíveis:**")
                colunas_debug = ['Ciclo', 'NU_N01', 'NU_N02', 'NU_N03']
                colunas_existentes = [col for col in colunas_debug if col in df_geral.columns]
                st.dataframe(df_geral[colunas_existentes])
            
            fig_evolucao = self.gerador_graficos.criar_grafico_evolucao_niveis(df_geral)
            if fig_evolucao:
                st.plotly_chart(fig_evolucao, use_container_width=True)
                
                # Adicionar explicação dos níveis
                with st.expander("Entenda os Níveis de Aprendizagem", expanded=False):
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        st.markdown("""
                        **🔴 Defasagem**
                        - Os estudantes neste nível apresentam uma aprendizagem insuficiente para o ano de escolaridade avaliado. Necessitam de práticas de recomposição e recuperação de aprendizagens para avançarem.
                        """)
                    
                    with col2:
                        st.markdown("""
                        **🟡 Aprendizado Intermediário**
                        - Os alunos ainda não consolidaram todas as aprendizagens esperadas para o período. Precisam de reforço para progredir sem dificuldades.
                        """)
                    
                    with col3:
                        st.markdown("""
                        **🟢 Aprendizado Adequado**
                        - Este é o nível de aprendizagem esperado, onde os estudantes desenvolveram as habilidades adequadas. Para estes, devem ser realizadas ações para aprofundamento e ampliação das aprendizagens.
                        """)
            else:
                st.warning("Não foi possível gerar o gráfico de distribuição. Verifique se os dados dos níveis estão disponíveis.")
    
    def _exibir_participacao(self, df_geral: pd.DataFrame):
        """Exibe gráficos de participação"""
        st.markdown("##### Participação dos Estudantes")
        
        col1, col2 = st.columns(2)
        cores = {"1º Ciclo": "#98FB98", "2º Ciclo": "#228B22"}
        
        for i, ciclo in enumerate(["1º Ciclo", "2º Ciclo"]):
            df_ciclo = df_geral[df_geral['Ciclo'] == ciclo]
            
            if not df_ciclo.empty:
                participacao = df_ciclo['TX_PARTICIPACAO'].mean()
                previstos = df_ciclo['QT_PREVISTO'].sum()
                efetivos = df_ciclo['QT_EFETIVO'].sum()
                
                with [col1, col2][i]:
                    st.markdown(f"<h5 style='text-align: center;'>{ciclo}</h5>", unsafe_allow_html=True)
                    
                    # Gauge de participação
                    fig_gauge = self.gerador_graficos.criar_gauge_participacao(participacao, cores[ciclo])
                    st.plotly_chart(fig_gauge, use_container_width=True)
                    
                    # Métricas de alunos
                    subcol1, subcol2 = st.columns(2)
                    with subcol1:
                        st.metric("Previstos", f"{previstos:.0f}")
                    with subcol2:
                        st.metric("Efetivos", f"{efetivos:.0f}")
    
    def _exibir_analise_top5(self, df_habilidades: pd.DataFrame):
        """Exibe análise das 5 melhores e piores habilidades"""
        st.divider()
        st.subheader("Top 5 Habilidades por Desempenho")
        
        for ciclo in ["1º Ciclo", "2º Ciclo"]:
            st.markdown(f"##### {ciclo}")
            df_ciclo = df_habilidades[df_habilidades['Ciclo'] == ciclo]
            
            if not df_ciclo.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("**Maiores Desempenhos**")
                    top_5 = df_ciclo.nlargest(5, 'TX_ACERTO')[['CD_HABILIDADE', 'DC_HABILIDADE', 'TX_ACERTO']]
                    top_5['TX_ACERTO'] = top_5['TX_ACERTO'].round(1).astype(str) + '%'
                    st.dataframe(top_5, hide_index=True, use_container_width=True)
                    
                with col2:
                    st.markdown("**Menores Desempenhos**")
                    bottom_5 = df_ciclo.nsmallest(5, 'TX_ACERTO')[['CD_HABILIDADE', 'DC_HABILIDADE', 'TX_ACERTO']]
                    bottom_5['TX_ACERTO'] = bottom_5['TX_ACERTO'].round(1).astype(str) + '%'
                    st.dataframe(bottom_5, hide_index=True, use_container_width=True)

# --------------------------------------------------------------------------
# 9. EXECUÇÃO PRINCIPAL
# --------------------------------------------------------------------------

def main():
    """Função principal da aplicação"""
    try:
        painel = PainelResultados()
        painel.executar()
    except Exception as e:
        st.error(f"Erro na aplicação: {e}")
        logging.error(f"Erro na aplicação: {e}")

if __name__ == "__main__":
    main()
