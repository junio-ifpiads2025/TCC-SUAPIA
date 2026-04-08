🤖 SUAPIA: Gerador de Dataset Sintético (Q&A)
Este repositório contém o script de automação para a criação do Golden Dataset do projeto SUAPIA, um assistente virtual baseado em arquitetura RAG (Retrieval-Augmented Generation) focado em fornecer suporte à comunidade do IFPI sobre o sistema SUAP.

O script realiza a extração do texto dos manuais oficiais do SUAP e utiliza o modelo gpt-4o-mini da OpenAI para gerar perguntas e respostas orgânicas, simulando as dores e dúvidas reais de diferentes perfis de usuários (Alunos, Professores, Coordenadores).

✨ Funcionalidades
Web Scraping Automatizado: Extrai conteúdo textual diretamente das URLs dos manuais do IFPI.

Chunking Inteligente: Divide textos longos de forma lógica para evitar estouro de tokens e perda de contexto na LLM.

Injeção de Personas: Gera dados orgânicos (com gírias, contrações e narrativas) baseados no perfil do usuário alvo.

Saída Estruturada: Retorna os dados rigorosamente em formato JSON, prontos para a etapa de validação com o framework RAGAS.

🛠️ Pré-requisitos
Certifique-se de ter o Python (versão 3.8 ou superior) instalado em sua máquina. Além disso, você precisará de uma chave de API válida da OpenAI.

🚀 Instalação
Clone este repositório:

Bash
git clone https://github.com/seu-usuario/suapia-dataset-generator.git
cd suapia-dataset-generator
Crie um ambiente virtual (recomendado):

Bash
python -m venv venv
source venv/bin/activate  # No Windows use: venv\Scripts\activate
Instale as dependências necessárias:

Bash
pip install openai requests beautifulsoup4
💻 Como Usar
Abra o arquivo gerador_qa_suapia.py em seu editor de código.

Localize a variável de configuração da API e insira a sua chave:

Python
client = OpenAI(api_key="sk-SUA_CHAVE_AQUI")
Na lista tarefas_geracao, configure as URLs dos manuais que deseja processar e a Persona correspondente para cada um:

Python
tarefas_geracao = [
    {
        "livro": "Nome do Manual",
        "url": "https://manuais.ifpi.edu.br/...",
        "persona": "Descrição detalhada do perfil..."
    }
]
Execute o script:

Bash
python gerador_qa_suapia.py
O script irá iterar pelas tarefas, logar o progresso no terminal e, ao finalizar, salvará um arquivo dataset_suapia_personas.json na raiz do diretório.

📂 Estrutura do Dataset Gerado
O arquivo JSON de saída terá a seguinte estrutura, ideal para ser consumido por pipelines de avaliação RAG:

JSON
[
  {
    "persona": "Aluno Calouro",
    "contexto_base": "Texto extraído do manual original...",
    "pergunta_humana": "Suapia, eu sou aluno novo e não me deixaram almoçar sem reserva, o que faço?",
    "resposta_esperada": "Você precisa realizar a reserva no sistema SUAP até as 09:00h...",
    "tipo_pergunta": "Procedimental"
  }
]