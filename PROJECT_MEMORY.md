# Memória do projeto — Editor Conquistando

## Persistência de contas e assinaturas

O código aceita `DATABASE_URL` e cria automaticamente a tabela
`editor_accounts` em PostgreSQL. Enquanto essa variável não estiver
configurada, continua usando o arquivo local temporário.

Não criar o banco gratuito do Render cedo demais: ele expira 30 dias após a
criação. Ativar próximo do início dos testes comerciais e migrar para o plano
Basic quando houver compradores.

## Licenciamento comercial por dispositivo — futuro

Decisão registrada em 28/06/2026. Não implementar agora.

Quando o aplicativo começar a ser vendido, substituir o PIN global atual por
licenças individuais vinculadas ao dispositivo:

1. O aplicativo exibe um código único do aparelho.
2. O administrador gera um PIN de ativação para esse código.
3. O PIN funciona somente no primeiro dispositivo ativado.
4. Um painel administrativo permite criar, bloquear, renovar e transferir
   licenças.
5. As ativações e o estado das licenças ficam em um banco persistente.

Para uso comercial, não armazenar licenças no sistema de arquivos do serviço
gratuito do Render, pois ele é temporário. Avaliar um banco PostgreSQL
persistente quando houver autorização para o custo mensal.

Até essa etapa ser autorizada, manter o acesso simples configurado pela
variável secreta `APP_PIN`, salva localmente pelo navegador após a confirmação.
