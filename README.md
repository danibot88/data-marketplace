# Datasul Market

Marketplace demonstrativo de datasets construído com Python e Django. O projeto reúne catálogo, exploração de amostras, compra unitária, painel do cliente e entrega segura de arquivos grandes em uma aplicação server-rendered.

> Projeto educacional e de portfólio. Não utiliza dados reais, não processa cobranças por padrão e não possui vínculo com provedores ou empresas citados na documentação.

## Sobre o projeto

Este repositório nasceu como um experimento prático sobre o que é possível construir com o auxílio de IA quando o problema é descrito com contexto, requisitos e critérios de qualidade claros.

A IA apoiou a estruturação e a implementação, mas o processo também incluiu decisões de produto, revisão humana, testes automatizados, validações de segurança e conferência da documentação oficial das integrações. O objetivo não é apresentar “código feito com um clique”, e sim mostrar como um bom prompt pode funcionar como uma especificação técnica inicial.

O prompt original usado como ponto de partida está disponível em [`docs/prompts/marketplace-data-prompt.md`](docs/prompts/marketplace-data-prompt.md).

## Principais recursos

- catálogo com busca e filtros por categoria, formato e preço;
- descrições em Markdown sanitizado e dicionário de dados;
- preview paginado que lê exclusivamente o arquivo de amostra;
- gráficos gerados a partir de até 100 registros da amostra;
- Strategy de pagamentos com mock local e adaptador Mercado Pago;
- webhook assinado, atômico e idempotente;
- download autorizado por usuário e token;
- `X-Accel-Redirect` em produção e streaming em chunks no desenvolvimento;
- rate limit para preview, gráficos, webhooks e downloads;
- PostgreSQL em produção e SQLite como fallback local;
- testes automatizados e workflow de integração contínua.

## Stack

- Python 3.12+
- Django 5.x e Django Templates
- HTMX, Alpine.js, Tailwind CSS e Chart.js
- PostgreSQL ou SQLite
- Polars para amostras Parquet
- Nginx e Gunicorn em produção
- Pytest e GitHub Actions

## Estrutura resumida

```text
data_marketplace/       configurações e URLs do projeto
marketplace/            domínio, pagamentos, views, serviços e testes
templates/              interface server-rendered
static/                 ativos estáticos locais
config/nginx.conf       entrega privada com X-Accel-Redirect
compose.yaml            PostgreSQL, Django/Gunicorn e Nginx
```

## Execução local

Você precisa ter Python 3.12 ou superior instalado. Os comandos abaixo preparam o projeto na primeira execução.

### Primeira instalação no Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env
.venv\Scripts\python manage.py migrate
```

No Linux ou macOS, use `python3 -m venv .venv`, ative o ambiente com `source .venv/bin/activate` e execute os demais comandos com `python`.

### Dados demonstrativos e administração (opcionais)

Para preencher o catálogo com dados sintéticos:

```powershell
.venv\Scripts\python manage.py seed_demo
```

Para acessar o painel administrativo, crie um superusuário local:

```powershell
.venv\Scripts\python manage.py createsuperuser
```

Esses dois comandos são opcionais e não precisam ser repetidos a cada execução.

### Iniciar a aplicação

```powershell
.venv\Scripts\python manage.py runserver
```

Depois da primeira instalação, normalmente esse é o único comando necessário para iniciar o projeto. Execute `migrate` novamente apenas quando houver novas migrações e reinstale as dependências somente quando os arquivos de requisitos forem alterados.

Acesse:

- catálogo: `http://localhost:8000/`
- administração: `http://localhost:8000/admin/`

`localhost` aponta exclusivamente para a própria máquina e não expõe o seu endereço IP público.

O arquivo `.env` guarda as configurações locais e pode conter credenciais de desenvolvimento. Ele está protegido pelo `.gitignore` e nunca deve ser enviado ao repositório. Use `.env.example` apenas como modelo, sem inserir nele valores secretos.

## Testes e verificações

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python manage.py check
```

O workflow em `.github/workflows/tests.yml` executa essas verificações a cada push e pull request.

## Armazenamento privado

`PRIVATE_DATA_ROOT` deve apontar para um diretório que não seja servido como mídia pública. `Dataset.file_path` aceita apenas caminhos dentro dessa raiz; a view valida novamente o caminho resolvido antes de entregar o arquivo. As amostras também usam um storage sem URL pública.

Em produção, o Nginx monta essa pasta como `/_protected_data/` com a diretiva `internal`. A view autoriza o usuário e responde com `X-Accel-Redirect`; o Nginx realiza o streaming eficiente.

## Pagamentos

O projeto inicia com `PAYMENT_GATEWAY=mock`, sem transações reais. Para preparar o Mercado Pago, configure em um ambiente seguro:

```text
PAYMENT_GATEWAY=mercadopago
MERCADOPAGO_ACCESS_TOKEN=...
MERCADOPAGO_WEBHOOK_SECRET=...
SITE_URL=https://seu-dominio.example
```

O adaptador cria preferências com chave de idempotência, valida `x-signature` e consulta a API de pagamentos antes de conceder acesso. Credenciais reais não devem ser adicionadas ao repositório.

## Docker

Copie `.env.example` para `.env`, altere as senhas locais e execute:

```text
docker compose up --build
```

O ambiente de referência inicia PostgreSQL, Gunicorn e Nginx em `http://localhost:8080`. Para uma implantação pública, configure HTTPS, segredos externos, backup, observabilidade e um cache compartilhado para rate limiting.

## Limites do exemplo

- O catálogo demonstrativo usa dados sintéticos.
- A integração do Mercado Pago precisa de credenciais e testes na conta do proprietário.
- O uso dos CDNs do frontend pressupõe conexão com a internet.
- Antes de operar comercialmente, defina termos de uso, política de privacidade, licença dos datasets e rotina de suporte.

## Metadados de esquema

`schema_metadata` utiliza uma lista de objetos:

```json
[
  {"name": "ano", "type": "integer", "description": "Ano de referência"},
  {"name": "valor", "type": "number", "description": "Valor do indicador"}
]
```

## Uso responsável de IA

Se você usar este projeto como referência, trate a IA como uma parceira de execução e revisão, não como substituta para entendimento técnico. Especifique o problema, valide as decisões, leia o código e teste os fluxos críticos antes de publicar ou implantar.
