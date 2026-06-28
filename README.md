# Editor Conquistando

Editor local para preencher os templates **BR Sport** e **Actvitta**, visualizar o resultado e gerar um arquivo `.pptx`.

## Regras aplicadas automaticamente

- Ações e melhorias: Times New Roman, 20 pt, alinhado à esquerda e ao topo, espaçamento 1,0.
- Legendas das fotos: Times New Roman, 14 pt, alinhado à esquerda e ao topo, espaçamento 1,0.
- Slides de instrução são removidos do arquivo final.
- As fotos são recortadas sem distorção para os três espaços do template.

## Uso

1. Escolha `BR SPORT` ou `ACTVITTA`.
2. Cole todo o texto na área `Entrada rápida`.
3. Clique em `Selecionar as 3 fotos de uma vez`.
4. Clique em `Aplicar e gerar PowerPoint`.

O texto colado deve usar as seções `AÇÕES BEM SUCEDIDAS` e
`PONTOS DE MELHORIA`, com os itens `VENDAS`, `MKT`/`MARKETING` e
`CARTEIRA DE CLIENTES`. Código, razão, regional e microrregião também são
identificados automaticamente. Os campos detalhados continuam disponíveis
apenas no botão `Editar campos manualmente`.

As legendas podem ser incluídas na entrada rápida usando:

```text
FOTO 1
Cliente: ...
Cidade: ...
Pares: ...
```

O aplicativo usa o LibreOffice instalado no computador para preservar e renderizar os templates.
