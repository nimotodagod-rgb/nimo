# Memória do projeto — Editor Conquistando

## Persistência de contas e assinaturas

O código aceita `DATABASE_URL` e cria automaticamente a tabela
`editor_accounts` em PostgreSQL. Enquanto essa variável não estiver
configurada, continua usando o arquivo local temporário.

Não criar o banco gratuito do Render cedo demais: ele expira 30 dias após a
criação. Ativar próximo do início dos testes comerciais e migrar para o plano
Basic quando houver compradores.

## Administração e recuperação de senha

Implementado em 30/06/2026:

- O PIN de desenvolvedor libera um botão `Clientes` no topo do editor.
- O painel `Clientes` lista contas, permite liberar/bloquear acesso manualmente,
  alterar a razão social pelo suporte e gerar link de recuperação de senha.
- O usuário tem `Esqueci minha senha`; se SMTP estiver configurado, o link é
  enviado por e-mail. Sem SMTP, a solicitação fica registrada e o suporte gera
  o link pelo painel.
- Links de recuperação expiram em 30 minutos e funcionam uma única vez.
- O PIN tem limite de tentativas para reduzir teste por força bruta.

Variáveis opcionais para e-mail: `SMTP_HOST`, `SMTP_FROM`, `SMTP_PORT`,
`SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_STARTTLS`.

Configurar `APP_SECRET_KEY` no Render antes do uso comercial para manter as
sessões estáveis após reinício/redeploy.

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
