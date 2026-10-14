# Objetivo do Projeto
Construir um marketplace de dados em Python usando Django (arquitetura clássica com Django Templates), onde atuo como único provedor/vendedor dos dados. Os clientes compram datasets pontualmente (pagamento único) e obtêm acesso a downloads seguros de arquivos em lote e visualização/exploração direta no navegador (amostras interativas e gráficos).

---

## 1. Stack e Arquitetura
* **Backend:** Python 3.12+ com Django 5.x.
* **Frontend:** Django Templates + Tailwind CSS (via CDN ou pipeline leve) + HTMX e Alpine.js para interatividade assíncrona sem SPA.
* **Visualização de Dados:** Chart.js ou Plotly.js para gráficos interativos client-side.
* **Processamento / Data Wrangling:** Pandas / Polars / PyArrow (otimizado para leitura de cabeçalhos/amostras sem carregar GBs na memória RAM).
* **Armazenamento:** Disco local do servidor com proteção rigorosa contra acesso direto.
* **Banco de Dados:** PostgreSQL (ou SQLite para desenvolvimento).

---

## 2. Modelagem de Dados (`models.py`)
Implemente os modelos necessários:
1. `Dataset`:
   - `title`, `slug`, `description` (Markdown suportado).
   - `price` (DecimalField), `currency` (BRL/USD).
   - `file_path`: caminho do arquivo completo no disco local (FORA do diretório `media/` público, em pasta restrita protegida).
   - `sample_file`: arquivo de amostra leve (ex: primeiras 500-1000 linhas em CSV/JSON) para alimentar previews e gráficos.
   - `file_format` (CSV, Parquet, JSON, SQLite).
   - `file_size_bytes` (BigIntegerField) e metadados (`row_count`, `column_count`, `schema_metadata` em JSONField).
   - `is_active`, `created_at`, `updated_at`.
2. `Order`:
   - `user` (ForeignKey para `AUTH_USER_MODEL`).
   - `total_amount`, `status` (PENDING, PAID, FAILED, REFUNDED).
   - `gateway_provider` (CharField), `gateway_order_id` (CharField para rastreio externo).
   - `idempotency_key` (UUIDField) para evitar cobrança/processamento duplo.
   - `created_at`, `updated_at`.
3. `OrderItem`:
   - `order`, `dataset`, `unit_price`.
4. `DatasetAccess`:
   - `user`, `dataset`, `order` (garantindo relação 1:1 user-dataset ativa).
   - `token` (UUID seguro para links temporários ou validação de sessão).
   - `download_count` (IntegerField), `last_downloaded_at`.
   - `is_revoked` (BooleanField).

---

## 3. Segurança e Manipulação de Arquivos Grandes (GBs)
* **Prevenção de Acesso Público:** Os arquivos brutos NUNCA devem estar sob `MEDIA_URL` ou acessíveis via rotas estáticas públicas.
* **Download Seguro via Nginx X-Accel-Redirect / Apache X-Sendfile:**
  - O download deve passar por uma view protegida do Django (`@login_required` + checagem de propriedade em `DatasetAccess`).
  - O Django não deve carregar o arquivo de vários GBs na memória Python (`FileResponse` clássico degrada sob carga). Em produção, a view deve enviar o header `X-Accel-Redirect` (Nginx) para delegar o streaming ao servidor web, mantendo fallback de `StreamingHttpResponse` para ambiente de desenvolvimento (`DEBUG=True`).
* **Proteção de Previews:**
  - A visualização no navegador deve ler EXCLUSIVAMENTE o `sample_file` ou carregar chunks delimitados via Pandas/Polars com `nrows=100`, nunca carregando o dataset integral em tempo de execução.
* **Rate Limiting & Anti-Scraping:** Rate limit em rotas de download e preview via `django-ratelimit`.

---

## 4. Pagamento e Lógica de Webhook (Design Pattern Strategy)
* Implemente uma interface abstrata para gateways de pagamento (`BasePaymentGateway`) com os métodos:
  - `create_checkout_session(order: Order) -> dict`
  - `process_webhook(request: HttpRequest) -> Tuple[bool, Order]`
* Implemente uma versão concreta simulada (`MockPaymentGateway`) para ambiente de desenvolvimento local e uma versão pronta para `Stripe` ou `Mercado Pago`.
* **Webhook Handler:**
  - View dedicada com validação de assinatura criptográfica do payload do webhook.
  - Processamento idempotente: se o webhook for reenviado, verificar se a ordem já está `PAID` antes de emitir novos `DatasetAccess`.
  - Tratamento de transações atômicas com `transaction.atomic()` ao criar acessos pós-pagamento.

---

## 5. Interface e Experiência do Usuário (Frontend)
1. **Catálogo de Datasets:** Listagem com busca, filtros por formato, categoria e faixa de preço.
2. **Página de Detalhes do Produto:**
   - Descrição, dicionário de dados (colunas, tipos e descrições).
   - **Tabela de Preview Interativo:** Renderizada via HTMX com paginação e busca simples sobre a amostra.
   - **Visualizações Gráficas:** 1 ou 2 gráficos dinâmicos usando Chart.js/Plotly.js alimentados por uma rota leve de API interna (`/datasets/<slug>/sample-data/`).
   - Botão de compra com feedback visual imediato.
3. **Painel do Usuário ("Meus Dados"):**
   - Lista de datasets adquiridos, histórico de pedidos e botões de download com validação de token e contagem de downloads.

---

## 6. Testes Automatizados e Controlados (`pytest` / `TestCase`)
Crie uma suíte de testes robusta cobrindo:
1. **Acesso não autorizado:** Testar que requisições anônimas ou de usuários sem compra confirmada recebem `403 Forbidden` ou `404 Not Found` ao tentar baixar o arquivo.
2. **Download e Headers:** Testar se o header `X-Accel-Redirect` é retornado corretamente em ambiente simulado de produção e se os chunks funcionam em dev.
3. **Webhook e Idempotência:**
   - Teste de payload válido disparando a criação de `DatasetAccess` e atualização da ordem para `PAID`.
   - Teste de assinatura de webhook inválida retornando `400 Bad Request`.
   - Teste de webhook duplicado garantindo que não cria registros repetidos.
4. **Isolamento de Memória no Preview:** Teste unitário garantindo que a view de preview lê apenas o schema/sample sem acessar o arquivo primário de grande porte.

---

## Entregáveis Esperados
1. Estrutura completa de diretórios do projeto Django.
2. Arquivo `models.py` com relacionamentos, índices e restrições.
3. Implementação da view de download seguro (`views.py`) com lógica de headers de servidor.
4. Arquivo de serviço do Gateway de Pagamento e view de Webhook com idempotência.
5. Template Django base com HTMX e Alpine.js para a tabela de preview e gráficos.
6. Suíte de testes (`tests.py`) cobrindo os cenários críticos descritos.
