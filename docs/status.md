# Status da implementação

Atualizado em 25/09/2026. Referência: [SPEC v9](../specs/quantum-route-core-spec.md).

## Correções de segurança e CI

- Entrada euclidiana e viária verifica limites de entregas/veículos antes da normalização quadrática e da validação espacial; limites de listas também protegem o contrato.
- Host header validado por allowlist; modo local aceita apenas hosts de loopback. Falhas de armazenamento e quotas têm limites globais e por integrador para jobs, taxa, snapshots, disco livre e chamadas ORS.
- Jobs terminais expirados retornam 404 por GET e cancelamento. Distâncias cartesianas fora da faixa geram erro de entrada em vez de HTTP 500.
- `uv` fixado em 0.11.15 para incluir correções dos avisos de escrita e remoção de arquivos arbitrários.
- CI roda em push e PR para `main`; deploy automático somente após CI de commit de merge de PR na `main`, validado contra o topo da branch.
- Alterações locais de segurança ainda precisam ser validadas pelo CI hospedado e pelo procedimento de deploy antes de produção.

**Situação: base do piloto clássico implementada e verificada localmente. Aceitação viária real e operacional pendentes. O escopo integral da SPEC, incluindo a frente quântica, não está completo.**

## Implementado

- Core Python reutilizável, normalização, identidade da instância e validação independente de rotas.
- OR-Tools para distribuição e sequenciamento com capacidades diferentes; referência exata limitada a 10 entregas.
- Limites iniciais configuráveis de 15 entregas e 5 veículos, depósito único e retorno ao depósito.
- API assíncrona, persistência SQLite, migrações, worker em processo separado, autenticação, idempotência e cancelamento.
- Adaptador openrouteservice: snapping, matriz direcional, geometrias, quotas locais, cache opcional e tratamento de falhas.
- Área de atendimento por polígono oficial do município de São Paulo.
- CLI, exportação de execuções JSON/CSV e exemplo de visualização em mapa.
- Arquivos de Docker Compose e workflows de build/test/PR e deploy.

## Evidências e limites

- Verificação de 25/09/2026: **31 testes passaram** em Windows / Python 3.12.10. Ruff, formatação e mypy (27 arquivos de código) passaram. Há um aviso de depreciação do transporte HTTPX do TestClient, sem falha de teste.
- Após adicionar `uv run dev`, passaram os 12 testes focados em inicialização e jobs, incluindo API/worker reais, submissão HTTP, resolução e encerramento dos processos. Ruff e mypy passaram nos arquivos alterados. A suíte completa anterior não foi repetida nesta mudança.
- Wheel e distribuição fonte construídos; instalação mínima em ambiente separado executou a referência exata sem FastAPI ou OR-Tools instalados.
- Testes incluem limites do servidor, defaults, idempotência concorrente, autenticação, fila cheia, recuperação, cancelamento em execução, corrida com conclusão, prazo e supervisão de memória. O teste de memória injeta uma medição RSS acima do teto, sem esgotar a memória do computador.
- YAML dos dois workflows foi lido com sucesso; isso não substitui a execução no GitHub.
- Engine Docker indisponível no ambiente local (`dockerDesktopLinuxEngine` ausente). Build da imagem e ensaio de recuperação continuam sem validação.
- Os testes viários usam respostas simuladas. Eles não comprovam cobertura, desempenho ou qualidade real das ruas.
- Não há evidência de execução bem-sucedida dos workflows no GitHub ou da implantação em um host.
- O backend quântico está desabilitado explicitamente; instalar o extra não habilita QAOA.

## Concluído nesta rodada

- Inicialização local com `uv run dev`: dependências de desenvolvimento incluem API e solver; aplica migrações, inicia API/worker e encerra ambos com Ctrl+C. Os endpoints ficam disponíveis em `/docs`, sem envio automático de pedidos.
- Modo viário padrão e defaults de limites corrigidos; tetos explícitos acima do servidor continuam rejeitados.
- Validação de distância real do snapping, índices da geometria e ordem das paradas.
- Parada de implantação aguarda fila e execução; falhas das verificações de release pausam admissão. Deploy automático verifica novamente se o SHA continua atual depois da aprovação.
- Resultado de cancelamento consistente na corrida com conclusão; término forçado de matriz preserva um resultado estruturado mesmo sem incumbente.
- [README](../README.md), [integração](integration.md), [operação](deployment.md) e [decisão do provedor](routing-provider-decision.md).
- Schemas de resposta/erros OpenAPI, testes de regressão e resumo de benchmarks com falhas incluídas, amostras e percentis explícitos.
- Runner viário com execução externa opt-in e estimativa de consumo; 15 cenários fixos com 5/10/15 entregas × 1–5 veículos, validados no polígono municipal. Acesso viário ainda não verificado.

## Implementação experimental ainda pendente

A frente QUBO/QAOA não foi implementada nesta rodada. O estudo comparativo de codificações, documento matemático e prova exaustiva são trabalho técnico pendente, não mera configuração de credencial. A SPEC condiciona a integração QAOA à aprovação desse gate. Em seguida ainda serão necessários backend, preflight quântico, contadores, amostragem e benchmark comparativo. Essa frente não bloqueia o uso clássico, mas impede declarar a SPEC integralmente entregue.

## Pendências externas e decisões

| Pendência | Necessário para concluir |
| --- | --- |
| Validação real do ORS e do mapa | Credencial ORS configurada no ambiente; execução com consumo de quota e revisão dos trajetos reais |
| Aceitação de desempenho | Definir volume, concorrência, orçamento de testes e tempo aceitável; medir p50/p95 com 5, 10 e 15 entregas |
| Docker e implantação | Engine Docker disponível; host de destino, secrets, permissões GHCR e proteções do environment configurados |
| Recuperação em ambiente de implantação | Exercitar backup, migração, falhas e retorno à versão anterior antes de habilitar produção |
| Publicação | Revisão das licenças e das condições de uso, armazenamento e cache do provedor |
| Etapa 2: estado de São Paulo | Aceitação do piloto municipal e avaliação intermunicipal; não é bloqueio do piloto da capital |

## Critério de conclusão

Testes automatizados passando são necessários, mas insuficientes: a SPEC exige integração viária real, avaliação documentada e validação operacional. Registrar resultados medidos e ambiente; nunca converter ausência de evidência em suporte comprovado.
