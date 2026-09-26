# SPEC — Quantum Route Core

**Status:** Draft v9  
**Tipo:** Serviço de otimização de rotas API-first com core Python reutilizável e módulo experimental  
**Objetivo:** Receber coordenadas de entregas e veículos disponíveis, distribuir as entregas entre os veículos, otimizar a ordem das visitas com custos viários reais e devolver rotas com traçado para mapa por API HTTP ou biblioteca Python. Preservar validação independente, limites explícitos e comparação experimental entre resolvedores clássicos e QAOA.

## 1. Resumo

Quantum Route Core é um serviço API-first para integração com sistemas de entregas. Uma biblioteca Python reutilizável contém o core de otimização, sem dependência do transporte HTTP. A API é a interface principal; a CLI apoia desenvolvimento, diagnóstico e benchmarks.

A integração de roteamento viário faz parte obrigatória do MVP: o consumidor não precisa calcular nem fornecer uma matriz para usar o fluxo principal. O serviço recebe coordenadas e frota, consulta um provedor viário, resolve a distribuição e devolve uma rota geográfica por veículo utilizado. A entrega inicial inclui um exemplo funcional de visualização dessas rotas em mapa.

Cada resolução executa exatamente um backend: `classical`, `quantum` ou `exact`. A API aplica `classical` quando o campo é omitido e registra essa escolha na configuração efetiva; `quantum` e `exact` exigem seleção explícita. Os backends recebem a mesma instância normalizada e retornam o mesmo contrato de resultado. QAOA permanece experimental e não é fallback automático.

O projeto mede qualidade, taxa de sucesso e custo computacional. Simular circuitos quânticos localmente não demonstra vantagem quântica. A ausência de ganhos também é um resultado válido.

## 2. Problema e público

Público principal: desenvolvedores de sistemas que precisam atribuir entregas a veículos e ordenar paradas. Público secundário: estudantes e pesquisadores de otimização combinatória. O MVP entrega um piloto de integração com dados sintéticos ou minimizados, sem prometer prontidão para operação logística em produção.

O serviço calcula atribuições de entregas, sequências de visitas e trajetos pelas ruas. Cabe ao integrador enviar identificadores, coordenadas, demandas e veículos; obter a matriz viária e as geometrias é responsabilidade do serviço. Navegação curva a curva, geocodificação de endereços e trânsito em tempo real permanecem fora do MVP. Matriz explícita e coordenadas euclidianas ficam disponíveis como modos avançado e experimental, respectivamente.

## 3. Metas

- Oferecer API HTTP versionada com jobs assíncronos e documentação OpenAPI.
- Entregar um fluxo completo coordenadas → matriz viária → distribuição entre veículos → ordem das visitas → traçado no mapa.
- Integrar ao menos um provedor real de matriz e direções viárias, com tratamento explícito de falhas e limites.
- Retornar identificação do veículo, paradas ordenadas, carga, distância, duração estimada de deslocamento e geometria por rota.
- Permitir uso direto do core Python sem servidor HTTP, banco de jobs ou CLI.
- Definir uma única semântica de CVRP e uma função de custo comum.
- Executar somente o backend solicitado em cada resolução.
- Validar soluções independentemente dos frameworks de solver.
- Obter referências ótimas comprovadas para casos pequenos.
- Validar a equivalência da formulação QUBO antes de integrar QAOA.
- Controlar memória, tempo e trabalho computacional antes e durante a execução.
- Reproduzir experimentos com instâncias, configurações, sementes e ambiente registrados.
- Exportar resultados brutos e agregados em JSON e CSV.

## 4. Fora do escopo do MVP

- Garantia de vantagem quântica, qualidade superior, aceleração ou SLA.
- Uso em produção logística ou decisões de despacho em tempo real.
- Trânsito em tempo real, geocodificação, navegação curva a curva ou múltiplos depósitos.
- Janelas de tempo, prioridades de entrega, balanceamento de jornadas, tempo de atendimento, coleta e entrega ou demanda estocástica. São melhorias futuras; capacidades diferentes por veículo fazem parte do MVP.
- Entregas divididas entre veículos ou múltiplas viagens do mesmo veículo.
- Combinação automática, fallback silencioso ou execução paralela dos backends.
- Painel web operacional completo, webhooks, infraestrutura distribuída de workers, hardware quântico remoto, warm-start, reparo de amostras e mixers personalizados. O exemplo de mapa para validar a integração está no escopo.

Essas extensões só serão reconsideradas após validar a formulação básica e publicar o primeiro benchmark.

## 5. Usuário e fluxo principal

1. O integrador envia `POST /v1/optimizations` com depósito, entregas em latitude/longitude, veículos e configuração viária; `classical` é o default documentado.
2. A API valida schema, coordenadas, limites de admissão e permissões, canonicaliza o pedido e persiste o job, sem aguardar chamadas ao provedor.
3. A API responde `202 Accepted` com `job_id` e URL de consulta, sem aguardar a resolução.
4. O worker obtém a matriz viária, normaliza o problema e executa preflight e somente o backend selecionado, respeitando os limites efetivos.
5. O validador comum verifica o candidato e recalcula o custo pela matriz canônica; o adaptador viário obtém o traçado das rotas na ordem fixada pelo solver.
6. O integrador consulta `GET /v1/optimizations/{job_id}` até obter estado terminal e resultado.
7. O resultado contém, por veículo, paradas ordenadas, carga, custo, distância, duração estimada e geometria para mapa, além da viabilidade e do estado de conclusão do planejamento.
8. Opcionalmente solicita cancelamento ou cria um novo job para outro backend.

A biblioteca expõe o mesmo fluxo de normalização, preflight, resolução e validação sem HTTP. A CLI permite carregar JSON, gerar exemplos e executar benchmarks sobre esse core; não é requisito para integrar a API.

A fachada `plan_deliveries(request, routing_provider, execution_context)` orquestra o fluxo viário completo usando um provedor injetado. A fachada `solve` permanece disponível para resolver instâncias com matriz já materializada. O serviço executa um único solver por planejamento; as consultas viárias não são execuções de outro backend de otimização.

A referência exata é solicitada explicitamente. Um relatório pode anexar uma referência já calculada, sem disparar outro solver durante `solve`.

## 6. Escopo funcional do MVP

### 6.1 Semântica de CVRP e validação de entrada

- Um depósito e pelo menos um cliente, com identificadores únicos.
- Frota com capacidades individuais inteiras positivas, que podem diferir entre veículos.
- Receber `vehicles: [{id, capacity}]` em todos os modos, com IDs únicos; derivar `vehicle_count` da lista. A atribuição da rota ao veículo faz parte da otimização e deve respeitar sua capacidade específica. Listar `unused_vehicle_ids`; nunca substituir capacidades individuais pela média ou atribuir veículos arbitrariamente após resolver.
- Demanda inteira positiva por cliente; demanda do depósito igual a zero.
- Cada cliente deve ser atendido integralmente e exatamente uma vez.
- Cada veículo utilizado realiza uma única rota, iniciando e terminando no depósito.
- Usar no máximo `vehicle_count` rotas; veículos ociosos são permitidos e omitidos da saída.
- Não permitir depósito no interior da rota, rota vazia ou nós desconhecidos.
- Objetivo: minimizar a soma dos custos de todos os arcos, incluindo saída e retorno ao depósito. Não incluir custo fixo por veículo ou outro objetivo implícito.

No modo viário, `objective_metric` escolhe `travel_time` (default) ou `distance`. A distribuição considera simultaneamente custo de deslocamento e capacidade; não é mera divisão pela quantidade de pontos. Não há garantia de igualar a carga/duração das rotas nem de usar todos os veículos; esses objetivos exigiriam política adicional explícita. Todos os veículos partem e retornam ao mesmo depósito no MVP.

Separar entrada malformada, inviabilidade comprovada e viabilidade ainda desconhecida. Demanda individual maior que a maior capacidade disponível ou demanda total maior que a soma das capacidades comprovam inviabilidade, mas a recíproca não vale: demandas `[6, 6, 6]` com dois veículos de capacidade 10 continuam inviáveis. Validar a carga de cada rota contra a capacidade do veículo identificado nela.

O validador de entrada não chama nenhum solver para provar viabilidade. Uma entrada bem formada pode representar um problema inviável. A prova de inviabilidade em casos não triviais cabe ao backend exato solicitado explicitamente.

Configuração inicial de testes: `max_deliveries = 15` (sem contar o depósito) e `max_vehicles = 5`. São parâmetros de implantação, expostos em capabilities, nunca constantes espalhadas pelo código. Rejeitar pedidos acima do limite efetivo sem truncar entregas ou veículos. Limites menores solicitados pelo cliente podem restringir a execução, mas não aumentar os tetos do servidor. Os backends exact e quantum mantêm limites próprios de tempo/recursos, possivelmente menores; aceitar 15 entregas na API não promete que todos os backends suportam esse tamanho.

Etapa 1: município de São Paulo (capital), com área de atendimento configurada por polígono geográfico versionado de fonte oficial. Validar depósito e entregas dentro dessa área, com política explícita para pontos na fronteira; não usar apenas nome textual ou retângulo envolvente. Trajetos podem atravessar municípios vizinhos quando necessário: a área limita os pontos atendidos, não recorta artificialmente as ruas disponíveis. Todos os veículos começam no mesmo depósito e, conforme a regra atual, retornam a ele. O piloto permite capacidades diferentes, mas mantém um perfil viário comum: restrições distintas de circulação por tipo de veículo ficam para evolução futura.

Etapa 2: ampliar a área de atendimento para o estado de São Paulo após validar cobertura, trajetos intermunicipais, latência, limites de distância e custo do provedor. A expansão geográfica não aumenta automaticamente os limites de 15 entregas e 5 veículos, não adiciona depósitos nem modifica as regras de frota. Mudança de escala depende de avaliação separada.

### 6.2 Matriz canônica, coordenadas e identidade

Todos os backends e o validador usam exatamente a mesma matriz de custos inteiros, não negativa e com diagonal zero. Aceitar matrizes simétricas ou assimétricas: o custo de A para B pode diferir do custo de B para A. A matriz não precisa satisfazer desigualdade triangular. Não aceitar NaN, infinito, dimensões inconsistentes ou valores fora do intervalo numérico suportado.

Classical e exact devem suportar custos assimétricos sem simetrização. A formulação quântica declara suas capacidades: se restrita a custos simétricos, rejeitar explicitamente uma matriz assimétrica como configuração não suportada. Comparações usam somente instâncias suportadas por todos os backends envolvidos. Custos são finitos para todos os pares no MVP; arcos proibidos exigem extensão futura.

- `node_order` contém depósito e clientes exatamente uma vez e define os índices da matriz.
- No modo `road`, exigir latitude/longitude de todos os pontos e materializar a matriz via provedor. No modo `euclidean`, exigir coordenadas cartesianas `x/y` e escolha experimental explícita; nunca calcular distância euclidiana sobre latitude/longitude como substituto da rede viária.
- Gerador inicial: coordenadas euclidianas 2D com semente e versão registradas.
- Materializar distâncias usando `floor(scale * distance + 0.5)`, com escala inteira positiva registrada. A regra é aplicada uma única vez na normalização.
- Uma matriz explícita já contém custos inteiros canônicos; não aplicar nova escala. `cost_scale` apenas documenta sua conversão para unidades de apresentação.
- No modo `matrix`, a matriz fornecida é a fonte de verdade; coordenadas opcionais não ativam consultas viárias. Esse modo não promete geometria. No modo `road`, rejeitar matriz fornecida pelo cliente para evitar mistura de custos e políticas de roteamento incompatíveis.
- Relatar custo inteiro como resultado autoritativo e, opcionalmente, custo de apresentação dividido pela escala. O ótimo é relativo à matriz quantizada, não às distâncias contínuas originais.
- Validar limites para somas de custos e coeficientes antes de enviar dados a bibliotecas com inteiros limitados.

Definir serialização canônica versionada: ordenar nós por identificador, reordenar a matriz na mesma ordem, ordenar chaves e usar JSON UTF-8 compacto. Calcular SHA-256 sobre depósito, clientes e demandas, frota, matriz, unidades, escala e versão de normalização. Excluir nome de exibição, timestamps, sementes, coordenadas e metadados que não mudam o problema normalizado. Persistir também a instância normalizada, não apenas o hash.

Separar `request_hash` (inclui coordenadas, IDs dos veículos, opções viárias e configuração) do `instance_hash` matemático, disponível após a matriz. A idempotência usa o pedido canonicalizado completo; cache viário inclui coordenadas, perfil, provedor, versão dos dados quando disponível e opções. Nunca reutilizar geometrias apenas porque duas matrizes quantizadas compartilham o mesmo hash.

### 6.3 Gerador e conjunto de fixtures

Gerar instâncias viáveis construindo primeiro uma distribuição de demandas que respeite a capacidade dos veículos e depois gerar coordenadas. Guardar a atribuição testemunha no artefato de geração para auditoria, sem entregá-la aos solvers nem usá-la como warm-start.

Manter fixtures manuais separadas: capacidade excedida por um cliente, capacidade total insuficiente, inviabilidade por empacotamento, custos zero, empates, veículos ociosos, matriz não métrica e soluções com subtours desconectados.

### 6.4 Backend clássico

Usar OR-Tools Routing como baseline inicial, com custos inteiros canônicos e vetor de capacidades por veículo. Preservar a correspondência entre índice interno e ID do veículo. Registrar estratégia de solução inicial, estratégia de busca local, limites e todas as opções efetivamente aplicadas.

Somente expor sementes suportadas pela configuração escolhida; registrar opções não suportadas em vez de fingir aleatoriedade. Não tratar uma solução heurística como ótima. Distinguir ausência de incumbente, expiração de prazo e prova de inviabilidade. Não chamar QAOA nem o backend exato.

### 6.5 Formulação QUBO: entrega obrigatória antes do QAOA

Produzir um documento de formulação versionado contendo:

- Variáveis binárias, interpretação e ordenação dos bits.
- Variáveis auxiliares e folgas, domínios e contagem após conversão para binário.
- Função de custo, atendimento único, capacidade individual por veículo, atribuição de rotas, limite da frota, conectividade ao depósito e eliminação de subtours. Se a primeira formulação experimental suportar apenas capacidades iguais, declarar essa restrição em capabilities e rejeitar pedidos incompatíveis, sem alterar capacidades; isso não restringe o backend clássico do produto.
- Fórmula de cada penalidade, coeficientes e justificativa de dominância sobre ganhos de custo inválidos.
- Mapeamento QUBO/Ising, normalização, offset e relação entre energia e custo da rota.
- Regras completas de codificação e decodificação, incluindo endianness e rejeição de estados inválidos.
- Fórmula de crescimento de qubits e termos não nulos, limites numéricos e condições de equivalência.

A codificação ainda exige uma decisão técnica documentada: comparar candidatas em um estudo mínimo com três clientes e selecionar uma somente após medir a contagem real de bits e provar a equivalência. A implementação QAOA fica bloqueada até esse gate; não assumir que uma conversão automática torna o problema pequeno.

Para fixtures minúsculas dentro de um limite explícito de bits, enumerar todos os estados binários e todas as soluções CVRP relevantes independentemente. Verificar cobertura das rotas viáveis, correspondência energia/custo nos estados com auxiliares consistentes e que todos os estados fundamentais decodificam para ótimos CVRP. Verificar ainda que nenhum estado inválido empata ou supera o melhor válido nas fixtures viáveis. Estados sem penalidade devem corresponder a soluções viáveis.

As verificações exaustivas complementam a justificativa matemática da formulação; não a substituem. Para instâncias inviáveis, o decodificador não pode inventar uma rota viável. Manter `qubo_energy` e `objective_cost` separados em todos os artefatos.

### 6.6 Preflight e orçamento quântico

Não prometer uma faixa fixa de 3–8 clientes. Começar com uma fixture CVRP viável de três clientes e capacidade ativa; aumentar somente após medir os recursos da codificação aprovada. Um limite adicional de clientes é permitido como proteção, mas não substitui limites de qubits e memória.

Antes de alocar um estado quântico, informar:

- Bits de decisão, auxiliares, folgas e total de qubits após simplificações.
- Termos do Hamiltoniano, número estimado de portas e profundidade estimada.
- Método de simulação, precisão e estimativa de memória com margem para buffers e overhead.
- Profundidade QAOA `p`, limite de avaliações, shots por avaliação, shots finais e teto total de shots.
- Limites efetivos de tempo, memória e qubits.

Para statevector em precisão dupla, usar `16 * 2^qubits` bytes apenas como mínimo para o vetor: 24 qubits requerem 256 MiB, 28 requerem 4 GiB e 30 requerem 16 GiB, antes do overhead. Outros métodos exigem estimadores próprios; não usar compressão presumida para garantir execução.

Definir defaults conservadores após medir a fixture no ambiente de referência e publicá-los com a configuração da máquina. Recusar a execução antes da alocação quando exceder limites ou quando não houver estimativa segura para o método solicitado. Estimativas não equivalem a garantia de pico de memória.

### 6.7 Backend QAOA

Executar QAOA local com Qiskit e Qiskit Aer. Registrar `p`, mixer padrão, parâmetros iniciais/finais, otimizador clássico, critério de parada e sementes independentes de inicialização, otimização, simulação e transpilation quando suportadas.

No MVP, selecionar a melhor rota viável das amostras finais obtidas com os parâmetros selecionados. Amostras usadas na otimização alimentam diagnósticos e a métrica de primeira solução viável, mas não mudam silenciosamente a política de seleção. Em interrupção, permitir preservar o melhor incumbente já validado, identificando sua origem e a interrupção.

- Não reparar amostras inválidas.
- Decodificar cada bitstring distinto uma vez e preservar multiplicidades.
- Fração viável = shots de bitstrings viáveis / shots efetivamente medidos, com fase identificada; não dividir pelo número de strings distintas.
- Se não houver shots, a fração é `null`, não zero.
- Zero amostras viáveis não prova inviabilidade do CVRP.
- Separar energia penalizada, custo da rota e taxa de viabilidade.
- Registrar avaliações, circuitos executados, shots efetivos por fase e total; uma avaliação pode executar mais de um circuito.
- Reportar `p`, profundidade lógica e profundidade transpilada separadamente.

Reutilizar circuitos parametrizados e transpilation quando compatíveis com a API e configuração. Não reconstruir o circuito inteiro a cada avaliação sem necessidade. Invalidar cache quando mudar formulação, circuito, backend, precisão ou configuração relevante. Registrar hits, misses e o regime de cache nos tempos.

### 6.8 Referência exata

Implementar primeiro enumeração independente e auditável para fixtures minúsculas, sem depender do QUBO. Publicar limites de clientes, memória e tempo.

Se a enumeração limitar os experimentos, usar programação dinâmica por subconjuntos: calcular a rota ótima depósito–subconjunto–depósito e combinar atribuições de subconjuntos disjuntos aos veículos concretos, respeitando a capacidade de cada um. O estado da DP inclui veículos disponíveis/processados e clientes cobertos; permitir veículo ocioso. Não usar apenas uma partição em K rotas com capacidade comum. Reutilizar subproblemas e eliminar simetrias somente entre veículos equivalentes em capacidade e restrições. Conferir a implementação contra enumeração em fixtures pequenas.

Somente marcar ótimo ou inviabilidade como comprovados após concluir a busca que fundamenta a prova. No timeout, conservar incumbente validado, se existir, sem afirmar optimalidade. Recusar instâncias fora dos limites anunciados.

Uma chamada explícita `solve --backend exact` gera o artefato de referência. Cachear como referência apenas resultados ótimos comprovados, com hash canônico, custo, rotas, versão do algoritmo e evidência de conclusão. Resultados interrompidos podem ser arquivados como execuções, nunca promovidos a referências ótimas. Verificar hash e rotas ao carregar o cache.

### 6.9 Benchmark e relatórios

O runner executa resoluções separadas e sequenciais. Seu manifesto lista explicitamente backends, instâncias, configurações, sementes, orçamento por execução e referências exatas solicitadas ou fornecidas. Cada chamada `solve` continua executando um único backend.

Fixar o manifesto antes de avaliar resultados. Separar instâncias de ajuste de parâmetros das instâncias de avaliação; registrar orçamento de tuning. Não usar ótimos de avaliação para ajustar QAOA. Balancear ou alternar a ordem dos backends para reduzir efeitos de ordem.

Comparação principal: mesmo orçamento de tempo total por chamada no mesmo ambiente. Experimentos com limite fixo de avaliações são complementares e não representam trabalho equivalente entre algoritmos. Respeitar também limites de shots, qubits e memória; registrar qual limite encerrou cada execução.

Relatar, por instância e configuração:

- Proporção de execuções com incumbente viável e contagens de todas as falhas.
- Distribuição de custo e gap entre execuções viáveis, com número de casos incluídos.
- Mediana, dispersão e tamanho amostral; intervalos de confiança quando calculados, com método explícito.
- Tempo total, tempo até primeira solução viável e tempos por fase.
- Recursos quânticos, contagens efetivas de avaliações/circuitos/shots e frações viáveis por fase.
- Vitórias, empates e derrotas; publicar inclusive quando uma abordagem nunca vencer.

Não excluir silenciosamente falhas dos agregados nem comparar médias condicionais sem informar a taxa de sucesso. Se uma configuração clássica for determinística, repetições medem variação de tempo, não variabilidade de soluções causada por sementes fictícias.

Calcular `absolute_gap = objective_cost - exact_optimum` somente com solução viável e referência comprovada. Se o ótimo for positivo, `relative_gap_percent = 100 * absolute_gap / exact_optimum`. Com ótimo zero, percentual é `null` e gap absoluto permanece disponível. Sem referência, ambos são `null`. Gap negativo é erro de consistência a investigar, nunca evidência de superar o ótimo.

Tempo até primeira solução viável começa no mesmo marco do tempo total. Se o backend não expuser esse evento, usar `null` e explicar a indisponibilidade; não substituir pelo tempo final. Execuções sem solução são censuradas pelo orçamento ao analisar essa métrica.

Salvar artefatos JSON brutos; CSV contém uma linha por execução com campos escalares e referência aos detalhes. Registrar CPU/GPU, RAM, sistema operacional, versões de Python e dependências, limites de threads, método de simulação, revisão do código e configuração efetiva. Mesma semente não garante resultados idênticos entre plataformas ou versões.

### 6.10 API HTTP e ciclo de vida dos jobs

Contrato público versionado em `/v1`, documentado em OpenAPI com exemplos de submissão, consulta, cancelamento, erros e resultado sem solução viável. A API recebe `DeliveryPlanningRequest` no modo viário principal e permite `instance` com `config` nos modos avançados explicitamente discriminados. O servidor gera hashes e identificadores, sem confiar em hashes fornecidos pelo cliente.

| Operação | Contrato do MVP |
| --- | --- |
| `POST /v1/optimizations` | Validar e persistir o pedido; responder `202` e `Location` para consulta. |
| `GET /v1/optimizations/{job_id}` | Responder `200` com estado, timestamps e resultado quando disponível. |
| `POST /v1/optimizations/{job_id}/cancel` | Solicitar cancelamento idempotente; responder `202` enquanto pendente e `200` se já terminal. |
| `GET /v1/capabilities` | Informar backends habilitados, caráter experimental, suporte a custos assimétricos e limites efetivos. |
| `GET /health` | Informar disponibilidade básica sem expor configurações sensíveis. |

Estados: `queued`, `running`, `cancel_requested`, `completed`, `cancelled`, `failed`. Fluxo normal: `queued → running → completed`; cancelamento pode levar de `queued` diretamente a `cancelled` ou de `running` a `cancel_requested → cancelled`. Falhas de execução ou interrupção do serviço podem levar a `failed`. Transições são atômicas; se a conclusão já foi persistida, um cancelamento posterior não a altera.

Estado do job e resultado do solver são conceitos distintos: `completed` pode conter ausência de solução, inviabilidade comprovada ou limite de tempo/recursos atingido. `failed` indica falha de execução/infraestrutura; `cancelled` pode conter incumbente validado. Em todos os casos, o cliente consulta `SolveResult` e não infere viabilidade do HTTP `200` ou do estado do job.

Para planejamento viário, retornar também `planning_result` e `planning_status`: um `completed` sem solução tem `no_feasible_solution`; somente `ready` significa que todas as rotas viáveis possuem geometria e métricas completas. Falha no provedor após otimização produz job `failed` com resultado parcial, nunca `ready`. O endpoint de capacidades inclui modos, provedor/perfis disponíveis, limites de pontos, suporte a geometria e estado da configuração viária.

Suportar `Idempotency-Key` na submissão, por identidade do integrador. Mesma chave e mesmo pedido normalizado, incluindo configuração solicitada, retornam o job existente; mesma chave com pedido diferente retorna `409`. Deduplicação é atômica e persiste com o job; documentar sua janela de retenção. Hash de instância sozinho não deduplica execuções com configurações distintas.

Erros de admissão usam `{code, message, field_errors, request_id}`: `400` para JSON malformado, `422` para schema/opções/capacidades incompatíveis, `413` para payload excessivo, `429` para fila/quota esgotada e `503` para indisponibilidade. Jobs desconhecidos ou de outro integrador retornam `404`. Entrada bem formada mas matematicamente inviável pode gerar um job e resultado normal, não erro de schema.

### 6.11 Persistência e operação do piloto

O MVP usa uma única instância do serviço, armazenamento persistente de jobs (SQLite inicialmente) e worker em processo separado do servidor HTTP. A fila é limitada e durável; uma transação reivindica cada job antes da execução. O default é um job ativo por worker, sem infraestrutura distribuída. Requisições HTTP não aguardam nem executam o solver no processo de atendimento.

Persistir pedido canonicalizado, configuração efetiva, proprietário, chave de idempotência, estado, timestamps, resultado e erros. No modo viário, persistir também matriz normalizada, proveniência e geometrias conforme sejam obtidas e conforme a licença permita. Após reinício, jobs enfileirados continuam elegíveis; jobs em execução/interrupção são marcados `failed` com motivo `service_interrupted` e eventual incumbente preservado, sem reinício silencioso do solver. Publicar prazo de retenção e rotina de expiração de jobs, resultados e chaves de idempotência.

Modo local vinculado a loopback pode funcionar sem autenticação. Para acesso por outros sistemas na rede, exigir token por integrador e HTTPS no serviço ou proxy de entrada; restringir consulta e cancelamento ao proprietário. Tokens são configuração do adaptador HTTP, nunca do core nem dos resultados. Logs usam IDs de job/requisição e não incluem tokens ou payloads completos por padrão.

Configurar limites de payload, clientes, tamanho da fila, tempo em fila, tempo de resolução e memória no servidor; clientes não podem aumentá-los. Configurações acima dos limites são rejeitadas com motivo explícito. Habilitar backends experimentais por configuração do serviço. Documentar inicialização, persistência, autenticação e um exemplo completo de integração antes de liberar o piloto.

### 6.12 Integração viária e mapa: requisito de entrega do MVP

Implementar o adaptador real do openrouteservice hospedado, plano Standard gratuito, para matriz entre todos os pontos e direções/geometria de uma sequência ordenada. Uma interface abstrata ou um mock isolado não satisfaz esse requisito. O provedor inicial está escolhido para avaliação; verificar perfil de condução, cobertura da capital, limites de pontos, quotas e termos de armazenamento/exibição antes de executar a prova de conceito.

- Receber pontos WGS84 por campos explícitos `latitude` e `longitude`, validando intervalos e valores finitos. IDs distinguem entregas mesmo quando as coordenadas coincidem.
- Ajuste de ponto à via (snapping) usa distância máxima configurada; devolver coordenadas solicitadas, coordenadas ajustadas e distância do ajuste. Rejeitar ponto não atendido ou ajuste acima do limite com erro por ponto, sem mover silenciosamente uma entrega para outra região.
- Obter custos direcionais com o mesmo provedor, perfil e opções usados nas geometrias. `travel_time` usa segundos inteiros canônicos e `distance` usa metros inteiros canônicos, aplicando arredondamento registrado. Não prometer que o caminho interno do provedor minimiza distância se a API dele não oferecer essa política; documentar a semântica suportada e rejeitar opções incompatíveis.
- Registrar provedor, perfil, opções, horário da consulta, versão do mapa quando disponível e a matriz efetivamente otimizada. Durações são estimativas de deslocamento sem trânsito ao vivo, tempo de atendimento ou horário de chegada prometido.
- Tratar limites por consulta com divisão de matriz em blocos quando suportado, preservando índices e direção. Limitar número total de pontos, chamadas, concorrência e retries; respeitar quotas e prazo do job. Cache tem validade e chave compatíveis com o provedor e suas condições de uso.
- Se faltar custo para qualquer par, encerrar no MVP com `unreachable_pairs`, identificando os pares. Isso é uma limitação do modo de matriz completa, não prova de inviabilidade CVRP. Não converter ausência de rota em custo zero, infinito, distância em linha reta ou penalidade arbitrária.
- Após otimizar, consultar direções sem permitir reordenação das paradas pelo provedor. Preservar depósito, todas as entregas e retorno; dividir consultas longas em trechos se necessário, sem omitir paradas ou duplicar métricas dos trechos.
- Devolver uma geometria GeoJSON `LineString` por rota, com posições `[longitude, latitude]`, e métricas de distância/duração por trecho e totais. Caso seja necessário concatenar trechos, verificar continuidade e fidelidade à ordem de paradas. Não substituir o traçado viário por linhas retas entre entregas.
- Custo de otimização permanece o da matriz congelada. Distância/duração retornadas por direções são campos separados; divergências acima de tolerância documentada geram diagnóstico, sem alterar silenciosamente o resultado do solver.
- Falha de matriz encerra o job sem solver; falha de geometria preserva `SolveResult` e as rotas já enriquecidas, mas marca planejamento `partial` e job `failed` com erro recuperável. Não acionar outro provedor ou solver silenciosamente. Cancelamento/timeout também preservam dados já validados.
- Chaves e endpoints autorizados são configuração do serviço; não aceitar URL arbitrária de provedor no payload. Coordenadas são enviadas ao provedor configurado, o que deve estar documentado junto à retenção e licença dos dados. Core exato e fixtures sintéticas continuam disponíveis offline.

Entregar `examples/map/` como visualizador de demonstração: carregar resultado JSON exportado, mostrar depósito e entregas, desenhar geometrias com cor por veículo, numerar as paradas e permitir consultar carga, distância e duração. Exibir estado parcial/falhas e veículos ociosos. O mapa-base deve respeitar atribuição e licença do fornecedor selecionado. Essa demonstração valida o valor integrado; o produto continua API-first e o consumidor pode usar seu próprio frontend.

### 6.13 Provedor inicial e avaliação de desempenho

Decisão: iniciar com openrouteservice hospedado no plano Standard gratuito para avaliar desempenho e qualidade no município de São Paulo. A escolha autoriza a implementação do adaptador; não representa desempenho já comprovado ou contratação paga. Google Routes API e OSRM próprio permanecem alternativas futuras caso os resultados justifiquem uma troca explícita, sem fallback automático.

Configuração do serviço: `ROUTING_PROVIDER=openrouteservice`, `ORS_API_KEY`, endpoint oficial configurável pelo operador e perfil de condução suportado. A chave fica em variável de ambiente ou secret, nunca no repositório, payload, log ou resultado. Ausência da chave bloqueia somente o modo viário real com erro de configuração; core, testes offline e exemplos sintéticos continuam funcionando. Confirmar o endpoint oficial vigente na implementação.

Aplicar limites configuráveis por endpoint, contabilizando retries e chamadas de todos os jobs e smoke tests da mesma implantação. Conferir as quotas efetivas da conta antes do primeiro teste, reservar margem para consultas de desenvolvimento e impedir ultrapassagem dos tetos locais; nenhuma atualização automática para plano pago. Em `429`, respeitar a espera informada pelo provedor dentro do prazo do job e encerrar com motivo explícito se não houver orçamento. A limitação local não cobre consumo da mesma chave por aplicações externas; preferir credencial dedicada ao piloto.

Avaliação inicial: cenários sintéticos fixos com 5, 10 e 15 entregas e de 1 a 5 veículos, incluindo capacidades diferentes. Executar sequencialmente com número de repetições configurável e orçamento pré-calculado de chamadas. Separar cache frio e quente; registrar latência p50/p95 por fase (matriz, solver, direções e total), tamanho da amostra, taxa de sucesso, erros por endpoint, consumo de quota e qualidade visual do traçado. Não confundir tempo do OR-Tools com desempenho do provedor nem interpretar percentis de poucas amostras como SLA. Definir metas de aceitação antes das medições; a primeira rodada produz uma linha de base, não uma promessa operacional.

Requisitos eliminatórios: matriz direcional de duração, trajetos preservando a ordem de paradas, geometrias exportáveis, tratamento de pontos ajustados/inalcançáveis e uso compatível com exibição, armazenamento e cache previstos no projeto. Verificar também opções de perfil, credenciais e restrições específicas de cada endpoint; não assumir que o limite geral vale para opções dinâmicas.

Usar conjunto sintético reproduzível de até 15 entregas e um depósito na capital, reutilizável em comparação futura: matriz completa de 16 × 16 = 256 elementos (240 deslocamentos não diagonais), até 5 rotas por planejamento e no máximo 17 posições em uma rota que inclua todas as entregas e ida/retorno. Contabilizar chamadas adicionais de snapping, retries e eventuais divisões em blocos. A distribuição de veículos é feita pelo OR-Tools; não utilizar o endpoint de otimização de frota do provedor como substituto do core.

Incluir cenários no centro e nas zonas norte, sul, leste e oeste, pares com sentido único, travessias de rios, pontos próximos ao limite municipal e coordenadas sem acesso adequado. Medir sucesso/falhas, latência, ajuste à via, consistência matriz/geometria e custo por planejamento. Revisar visualmente trajetos de amostra; não afirmar superioridade de cobertura apenas pela documentação comercial.

Antes das medições, registrar orçamento mensal de testes, volume esperado e tempo aceitável de resposta. Comparar custo total de matriz, direções, snapping e mapa-base; no caso de hospedagem própria, incluir servidor, preparação/atualização dos dados e operação. Documentar a decisão, limites verificados, data de consulta das condições e alternativas em `docs/routing-provider-decision.md`. Mock não constitui prova de conceito real e documentação não comprova qualidade local.

Aceitar a etapa 2 somente após repetir a validação com pontos intermunicipais no estado, incluindo interior e litoral, e confirmar a política de dados, a infraestrutura necessária e o custo. Preservar a interface do adaptador para permitir troca explícita de provedor sem mudar os contratos do core.

## 7. Requisitos não funcionais e limites de execução

### 7.1 Prazo e memória

O prazo global começa após normalização da entrada e inclui preflight, construção da formulação, construção/transpilation do circuito, busca/otimização, amostragem, decodificação e validação. Leitura/normalização, inicialização do processo e exportação são medidas separadamente. Todos os backends usam os mesmos marcos; `solver_seconds` é uma submedida definida por adaptador.

Na API, o orçamento de resolução começa quando o worker inicia essas etapas; espera em fila não o consome. Registrar `queue_seconds` e duração desde aceitação até término separadamente. Aplicar timeout de fila independente; ao expirar, marcar o job `failed` com `queue_timeout`, sem fabricar um resultado de solver que não executou.

No modo viário, `planning_time_limit_seconds` limita o pipeline completo a partir do início do worker: matriz, normalização, solver, validação e direções. O solver mantém seu suborçamento `time_limit_seconds`, limitado ao tempo restante do planejamento. Consultas e retries usam o prazo restante, com reserva configurada para a fase de direções. Registrar tempos de matriz/geometria separadamente dos tempos do solver, além de cache hits; a espera em fila continua separada. Planejamento expirado recebe erro `planning_time_limit` e estado parcial se houver incumbente, sem alegar que a rota está pronta.

Usar relógio monotônico, propagar o tempo restante e verificar cancelamento entre etapas. Um supervisor executa o backend em processo trabalhador quando for necessário interromper chamadas que não respeitam cancelamento cooperativo. Encerrar também subprocessos controlados pelo trabalhador. Publicar tolerância de encerramento e medir eventual excesso; não prometer interrupção instantânea.

Entregar incumbentes validados ao supervisor durante a execução quando disponíveis, permitindo preservá-los após interrupção forçada. Aplicar limite de memória do simulador e monitoramento do processo; documentar se o limite do sistema operacional é rígido ou se o monitor apenas detecta excessos. Preflight e monitoramento não são substitutos para uma garantia rígida de memória.

### 7.2 Portabilidade e dependências

- API HTTP como interface principal, core Python instalável e CLI de apoio.
- Dependências HTTP e de persistência pertencem ao extra de serviço; importar e usar o core não inicializa servidor, banco, fila ou logging global.
- Suporte Windows, macOS e Linux condicionado à matriz de versões efetivamente testada.
- Dependências quânticas opcionais, imports tardios e extras de instalação separados.
- Domínio, normalização e validador não importam Qiskit ou OR-Tools.
- Ausência de Qiskit não impede uso clássico/exato; ausência de OR-Tools não impede uso exato.
- Fixar versões resolvidas em lockfile e documentar ambiente virtual e comandos reproduzíveis.
- Mensagens de erro devem identificar campo, causa e ação possível.
- Core e experimentos sintéticos não exigem credenciais de nuvem. Planejamento viário depende do provedor configurado e pode exigir credenciais/licença; autenticação de integradores é exigida no modo de rede da API.

### 7.3 Cache e medição

Distinguir resultados de preparação sem cache e com cache em grupos de benchmark separados. Não misturar seus tempos. Cache de referência não altera o tempo de resolução; tempo de carregamento/anexação é reportado separadamente. Não reutilizar uma solução pronta como se fosse nova execução do solver.

## 8. Arquitetura proposta

- `domain`: modelos normalizados de instância, rota e resultado.
- `normalization`: coordenadas, quantização, ordenação canônica e hash.
- `validation`: restrições e cálculo autoritativo de custo, independentes dos solvers.
- `solvers/base`: `preflight(instance, config)` e `solve(instance, config, execution_context)`.
- `solvers/classical`: adaptador OR-Tools.
- `solvers/quantum`: formulação versionada, QUBO/Ising, circuitos, amostragem e decodificação.
- `solvers/exact`: enumeração e, se necessário, programação dinâmica.
- `execution`: relógio, cancelamento, limites, processo trabalhador e incumbentes.
- `application`: casos de uso compartilhados de normalização, preflight e resolução; sem tipos HTTP ou acesso ao banco de jobs.
- `routing`: contrato de provedor viário e adaptadores de matriz, snapping e direções, cache e conversão de geometrias. Clientes externos são opcionais para uso matemático do core, obrigatórios no perfil do serviço de planejamento.
- `api`: transporte HTTP, autenticação, OpenAPI, admissão e mapeamento de erros.
- `jobs`: fila persistente, repositório, idempotência, estados e retenção; coordena workers que chamam o core.
- `experiments`: manifestos, resoluções sequenciais, referências e agregação.
- `io`: schemas versionados, JSON e CSV.
- `cli`: comandos de validação, preflight, resolução e benchmark.

A fábrica instancia e importa somente o adaptador selecionado. O contexto de execução fornece prazo restante e publicação de candidatos; a validação comum determina a validade do incumbente. O wrapper comum mede tempo e valida o resultado, sem chamar outro backend.

API/worker e CLI dependem dos mesmos casos de uso; o core não depende desses adaptadores. Expor uma fachada pública Python `normalize`, `preflight` e `solve`, com modelos e erros tipados, versionados e documentados. Clientes Python podem resolver em processo, usando o supervisor de execução quando necessário, sem criar jobs HTTP. Nenhuma regra de capacidade, custo ou decodificação deve ser duplicada nos adaptadores.

### 8.1 Stack definida

| Camada | Tecnologia | Responsabilidade |
| --- | --- | --- |
| Linguagem | Python | Core, API, workers e experimentos. |
| API HTTP | FastAPI + Uvicorn | Endpoints versionados e servidor HTTP com documentação OpenAPI. |
| Contratos | Pydantic | Validação estrutural e serialização de entrada/saída; regras de roteamento permanecem no validador comum. |
| Roteamento viário | openrouteservice Standard gratuito + adaptador HTTPX | Matriz, ajuste à via e geometrias reais; avaliar desempenho e quotas na capital. |
| Demonstração de mapa | HTML/JavaScript e biblioteca de mapa a selecionar | Exibir geometrias por veículo e sequência de entregas em `examples/map/`. |
| Solver clássico | OR-Tools Routing | Backend padrão de otimização de entregas. |
| Referência exata | Implementação própria em Python | Enumeração e, se necessário, programação dinâmica por subconjuntos. |
| Experimentos quânticos | Qiskit + Qiskit Aer | QAOA opcional em simulador local. |
| Persistência | SQLite + SQLAlchemy + Alembic | Jobs, idempotência, resultados e migrações de schema. |
| Worker | Processo Python separado | Consumo da fila persistente e execução supervisionada dos solvers. |
| CLI | Typer | Diagnóstico, exemplos e benchmarks locais. |
| Dependências | uv + `pyproject.toml` + `uv.lock` | Instalação reproduzível, extras opcionais e versões resolvidas. |
| Qualidade | pytest + HTTPX + Ruff + mypy | Testes, verificação dos contratos HTTP, lint/formatação e checagem de tipos. |
| Empacotamento e implantação | Docker + Docker Compose | Serviços API/worker e armazenamento persistente no piloto. |
| Integração contínua | GitHub Actions | Verificações automatizadas e matriz de compatibilidade. |

Fixar versões exatas de Python e dependências após smoke tests de compatibilidade, especialmente para OR-Tools e Qiskit. Não assumir suporte a uma plataforma somente pela disponibilidade do interpretador.

SQLite atende ao piloto de host único. Usar transações curtas para admissão e mudanças de estado; nunca manter uma transação aberta durante otimização. API e worker acessam o mesmo banco em armazenamento local persistente. Alembic aplica migrações explicitamente antes de iniciar os serviços. PostgreSQL é uma opção futura caso concorrência de escrita ou implantação exija mudança; essa migração não faz parte do MVP.

Docker Compose inicia API e worker como serviços separados no mesmo host, compartilhando o volume do SQLite. O solver não roda como tarefa em memória do processo HTTP. Não introduzir Redis, Celery ou outra fila distribuída no piloto; o repositório de jobs oferece a fila durável descrita na seção 6.11. Uso direto da biblioteca e desenvolvimento local não exigem Docker.

### 8.2 Organização do repositório

Usar um único repositório, um pacote Python instalável e layout `src`. A árvore abaixo é a estrutura planejada, a ser criada durante a implementação:

```text
quantum-route-core/
├── pyproject.toml
├── uv.lock
├── README.md
├── .env.example
├── .github/
│   └── workflows/
│       ├── build-and-test.yml # Qualidade, build, testes e criação de PR
│       └── deploy.yml         # Publicação e implantação em produção
├── specs/
│   └── quantum-route-core-spec.md
├── docs/
│   ├── architecture.md
│   ├── integration.md
│   ├── deployment.md
│   ├── routing-provider-decision.md
│   └── formulations/
│       └── cvrp-qubo.md
├── src/
│   └── quantum_route_core/
│       ├── __init__.py
│       ├── public.py          # Fachada pública da biblioteca
│       ├── domain/            # Instâncias, rotas, resultados e erros
│       ├── normalization/     # Matriz, normalização canônica e hash
│       ├── validation/        # Viabilidade e custo independentes dos solvers
│       ├── application/       # Casos de uso compartilhados
│       ├── routing/           # Integração viária
│       │   ├── base.py        # Contrato injetável do provedor
│       │   ├── models.py      # Matriz, pontos ajustados e geometrias
│       │   ├── cache.py
│       │   └── providers/
│       │       └── openrouteservice.py # Adaptador inicial do plano gratuito
│       ├── solvers/
│       │   ├── base.py        # Contrato e capacidades dos solvers
│       │   ├── registry.py    # Carregamento tardio do backend selecionado
│       │   ├── classical/
│       │   ├── exact/
│       │   └── quantum/
│       ├── execution/         # Prazos, recursos e cancelamento
│       ├── api/
│       │   ├── app.py
│       │   ├── routes/
│       │   ├── schemas.py
│       │   ├── auth.py
│       │   └── settings.py
│       ├── jobs/
│       │   ├── service.py     # Admissão e ciclo de vida
│       │   ├── repository.py  # Interface de persistência
│       │   ├── database.py    # Implementação SQLAlchemy
│       │   └── worker.py
│       ├── cli/
│       ├── experiments/
│       └── io/
├── migrations/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   └── fixtures/
├── examples/
│   ├── instances/
│   ├── http/
│   ├── map/                   # Demonstração das rotas por veículo
│   └── python/
├── benchmarks/
│   └── manifests/
└── deploy/
    ├── Dockerfile
    └── compose.yaml
```

Os módulos de core são `domain`, `normalization`, `validation`, `application`, `execution`, `solvers` e o suporte de serialização em `io`, expostos pela fachada `public.py`. Nenhum deles importa FastAPI, SQLAlchemy ou Typer. Modelos Pydantic compartilhados podem compor o contrato da biblioteca sem depender do framework HTTP; schemas de transporte e modelos de banco permanecem nos adaptadores. Não duplicar regras de roteamento nesses modelos.

Fluxo de dependências:

```text
API HTTP → Jobs persistentes → Worker ─┐
                                      │
CLI ──────────────────────────────────┼→ Application/core → Solver selecionado
                                      │
Aplicações Python consumidoras ────────┘
```

`__init__.py` não importa adaptadores opcionais nem inicializa infraestrutura. Exemplos HTTP e Python demonstram o mesmo contrato de solução. Dados de execução, bancos SQLite, tokens e resultados locais não são versionados; fixtures sintéticas e manifestos reproduzíveis são versionados. `.env.example` contém apenas nomes e valores de exemplo sem segredos.

### 8.3 Perfis de instalação e CI

Nome de distribuição: `quantum-route-core`; nome de importação: `quantum_route_core`.

| Perfil | Conteúdo |
| --- | --- |
| `quantum-route-core` | Core reutilizável, contratos e referência exata. |
| `quantum-route-core[classical]` | Core e OR-Tools. |
| `quantum-route-core[service,classical]` | API, persistência, worker e solver clássico. |
| `quantum-route-core[cli,quantum]` | CLI e dependências de experimentação QAOA. |

Definir extras independentes `classical`, `quantum`, `service`, `routing` e `cli`. pytest, Ruff e mypy pertencem ao grupo de desenvolvimento; HTTPX é dependência de runtime de `routing` e também ferramenta de testes HTTP. O extra `service` inclui `routing` e não exige Qiskit; `quantum` não exige FastAPI nem banco. A biblioteca com extra `routing` permite o fluxo viário sem servidor. Dependências auxiliares necessárias à integração QAOA devem ser declaradas e fixadas no mesmo lockfile.

A CI verifica formatação/lint, tipos, testes unitários, contratos e integração. Incluir instalação mínima do core sem extras, perfil clássico/API e smoke tests quânticos limitados às fixtures pequenas, nas plataformas anunciadas. Testes de arquitetura impedem imports dos adaptadores pelo core. A imagem padrão do piloto instala `service,classical`; experimentação quântica usa perfil explícito. Documentar build, inicialização, migrações e persistência em `docs/deployment.md`.

Na CI de PR, testes viários usam respostas gravadas/fixtures licenciadas e não dependem de rede ou segredos do provedor. Antes de liberar o piloto e em deploy, executar smoke test viário real com pontos controlados, quota limitada e configuração do ambiente, verificando planejamento `ready`. Validar visualmente o exemplo de mapa durante a entrega inicial.

### 8.4 Workflows GitHub Actions

`.github/` é um diretório deste mesmo repositório. Definir dois workflows, com responsabilidades e permissões separadas. Esta seção especifica os arquivos a implementar; não implica que pipelines ou infraestrutura já estejam provisionados.

#### 8.4.1 `build-and-test.yml`

- Gatilhos: `push` em branches de trabalho e na branch padrão, `pull_request` direcionado à branch padrão e `workflow_dispatch`. Adicionar `merge_group` se uma merge queue for habilitada.
- Instalar a versão Python suportada e dependências via uv com lockfile congelado. Executar Ruff, mypy, pytest, testes de contrato/API, persistência, cancelamento e instalação dos extras conforme a matriz da seção 8.3.
- Construir wheel e sdist; verificar instalação do wheel em ambiente limpo. Construir a imagem Docker do perfil clássico/API e executar smoke test com API, worker e uma instância sintética. Smoke tests quânticos usam fixtures pequenas e orçamento limitado.
- Guardar relatórios e artefatos de build identificados pelo SHA testado. Uma falha de lint, tipos, testes ou build impede a etapa de criação de PR e torna o check obrigatório malsucedido.
- Após sucesso de um `push` para uma branch de trabalho do próprio repositório, criar PR em rascunho para a branch padrão caso não exista PR aberto para esse par origem/destino. Se existir, reutilizá-lo sem sobrescrever título ou descrição editados por pessoas. Não criar PR em eventos de PR, forks ou pushes na branch padrão, nem efetuar merge automático.
- Antes de criar o PR, confirmar que a branch ainda aponta para o SHA validado e contém diferenças em relação à base. Serializar a criação por branch para evitar duplicatas; uma nova atualização precisa passar suas próprias verificações.
- Isolar a criação de PR em job dependente dos checks, com `pull-requests: write` e somente permissões adicionais indispensáveis. Esse job usa metadados da API GitHub e não executa código da branch com o token de escrita. Jobs de build/test usam `contents: read`, sem segredos de produção.
- Habilitar no repositório a permissão de Actions necessária à criação de PR. Documentar o comportamento de disparo/aprovação dos checks de PR criados por `GITHUB_TOKEN`; caso necessário para disparo automático, usar token de instalação de GitHub App com escopo mínimo. Não contornar checks obrigatórios nem proteções da branch.
- Cancelar execuções de CI obsoletas da mesma branch/evento para economizar recursos. Manter checks obrigatórios para o commit/merge avaliado no PR; o sucesso de um push antigo não autoriza merge de código novo.

#### 8.4.2 `deploy.yml`

- Gatilho automático: `workflow_run` após conclusão bem-sucedida de `build-and-test.yml` originada por `push` na branch padrão do próprio repositório. PRs, forks e branches de trabalho nunca iniciam deploy de produção.
- Permitir `workflow_dispatch` para publicar novamente um SHA aprovado ou executar rollback. Verificar que o SHA pertence ao histórico da branch padrão e possui execução bem-sucedida dos checks exigidos; uma entrada manual não dispensa validação.
- Vincular o workflow ao GitHub Environment `production`, com credenciais próprias e regras de branches/proteção configuradas no repositório. Serializar implantações com grupo de concorrência de produção e `cancel-in-progress: false`, evitando interromper migrações.
- Identificar a release pelo SHA aprovado e pelo digest imutável da imagem. Recuperar artefato da execução validada, verificar origem e SHA e publicar a imagem no GitHub Container Registry (GHCR). Implantar por digest, sem reconstruir uma versão diferente nem usar `latest` como identidade da release. No rollback, reutilizar o digest previamente publicado.
- Para deploy automático, confirmar antes da implantação que o SHA ainda corresponde à versão mais recente elegível da branch padrão; ignorar execução obsoleta. Rollback manual registra explicitamente que a versão escolhida é anterior.
- Destino inicial: host único executando Docker Compose, com volume persistente local para SQLite. Provedor, host e mecanismo de acesso serão definidos antes de habilitar o workflow; não presumir credenciais ou infraestrutura existentes.
- Sequência: verificar configuração e espaço disponível; interromper admissão e drenar jobs ativos até um prazo documentado; encerrar de forma controlada os restantes preservando incumbentes; parar API/worker; criar backup consistente do SQLite; aplicar migrações Alembic uma única vez; iniciar API e worker com a mesma imagem aprovada.
- Verificar `/health`, um job sintético e um planejamento viário real com pontos controlados via API, incluindo processamento pelo worker, resultado validado e geometrias completas. Somente marcar deploy como bem-sucedido após essas verificações; registrar SHA, digest, migração aplicada e resultado dos smoke tests, respeitando a quota do provedor.
- Se falhar, interromper a promoção e seguir o procedimento de recuperação documentado. Reverter a imagem somente se compatível com o schema atual. Não executar downgrade destrutivo ou restaurar banco automaticamente sobre dados novos; migrações incompatíveis exigem plano explícito de recuperação antes da release.
- Conceder `packages: write` apenas ao job de publicação; credenciais do destino ficam no environment, nunca em PRs, logs ou artefatos. Conceder `id-token: write` somente se o provedor escolhido usar OIDC. Validar a origem do evento antes de consumir artefatos com privilégios de deploy e fixar actions externas por SHA revisado.

O nome `production` identifica o ambiente de implantação. O primeiro deploy continua sendo o piloto de integração, sem ampliar automaticamente as garantias de SLA ou a prontidão logística do MVP. Documentar gatilhos, configurações do repositório, variáveis/segredos necessários, janela de indisponibilidade, backup e rollback em `docs/deployment.md` antes de habilitar a implantação.

## 9. Contratos de dados

### 9.1 `ProblemInstance`

- `schema_version`, `normalization_version`, `instance_id`, `instance_hash`.
- `depot: {id, x?, y?, latitude?, longitude?}`.
- `customers: [{id, x?, y?, latitude?, longitude?, demand}]`.
- `node_order: [id, ...]`.
- `vehicles: [{id, capacity}]`; `vehicle_count` derivado, sem campo de capacidade comum.
- `cost_matrix`: obrigatória na forma normalizada.
- `cost_units`, `cost_scale`, `distance_rule`, `rounding_rule`.
- `metadata: {generator_seed, generator_version, ...}`: proveniência, fora do hash do problema.

Identificadores são strings únicas; coordenadas são opcionais na instância matemática quando há matriz explícita. Não confundir coordenadas cartesianas `x/y` com latitude/longitude. O modo `road` produz a instância a partir de `DeliveryPlanningRequest`; `euclidean` precisa declarar regra euclidiana e escala. Persistir entrada original e representação normalizada conforme a política de dados do modo escolhido.

### 9.2 `SolveConfig`

- `schema_version`, `backend: classical | quantum | exact`.
- `time_limit_seconds`, `memory_limit_mb`, `max_deliveries`, `max_vehicles`; a nomenclatura pública de limite de clientes é `max_deliveries` em todos os modos.
- `seeds: {optimizer?, initialization?, simulator?, transpiler?}`.
- `backend_options`: schema próprio, rejeitando opções desconhecidas.
- Para QAOA: `formulation_version`, `p`, `max_qubits`, `max_evaluations`, `shots_per_evaluation`, `final_shots`, `max_total_shots`, otimizador, precisão e método de simulação.
- `cache_policy`, `thread_limit`.

Validar valores positivos e compatibilidade das opções antes de executar. O teto total inclui shots de otimização e amostragem final. Reservar orçamento final; quando não for possível concluir a fase final, retornar interrupção e eventual incumbente com origem identificada. Registrar configuração solicitada e efetivamente aplicada.

### 9.3 `SolveResult`

- `schema_version`, `run_id`, `instance_hash`, backend e versões.
- `termination_reason: completed | time_limit | resource_limit | evaluation_limit | shot_limit | cancelled | unsupported_configuration | invalid_input | error`.
- `has_feasible_solution`, `optimality_proven`, `infeasibility_proven`.
- `routes: [{vehicle_id, stop_ids, load, objective_cost}]`: rotas não vazias depósito–clientes–depósito, ou `null` sem solução; `unused_vehicle_ids` lista os veículos ociosos.
- `objective_cost`: custo inteiro recalculado, ou `null` sem solução viável.
- `validation_errors`: violações estruturadas; não confundir com prova de inviabilidade.
- `solution_origin`: amostragem final, otimização interrompida, busca clássica ou busca exata.
- `timings`: total, solver, fases, primeira solução viável, overhead externo e excesso de prazo.
- `config_requested`, `config_effective`, `environment`, `diagnostics`.
- `reference`: hash/identificador do artefato exato, ótimo e gaps, quando anexado pelo relatório.

Invariantes: optimalidade exige incumbente viável; inviabilidade comprovada exclui incumbente viável; ausência de solução não autoriza custo zero; `completed` não significa ótimo. Candidatos inválidos e suas energias podem ser preservados em diagnósticos, nunca como solução válida. Divergência entre custo alegado e recalculado é erro explícito de validação.

### 9.4 `OptimizationJob`

- `job_id`, `status`, `request_hash`, `instance_hash`, `request_id`; `instance_hash` é `null` até materializar a matriz.
- `created_at`, `started_at`, `finished_at`: UTC; campos ainda não aplicáveis são `null`.
- `config_effective`, `queue_seconds`, `elapsed_seconds`, `expires_at`.
- `result: SolveResult | null`, `error: {code, message} | null`.
- `planning_status: pending | ready | partial | no_feasible_solution | failed | not_applicable` e `planning_result: DeliveryPlanningResult | null`.
- `links: {self, cancel}`.

Proprietário e chave de idempotência são metadados internos, não campos públicos. Jobs cancelados antes de executar ou que falharam antes de produzir resultado retornam `result: null`. Um resultado existente mantém o mesmo schema usado pela biblioteca e CLI; informações de infraestrutura ficam no envelope do job.

### 9.5 `DeliveryPlanningRequest`

- `mode: road` (default do endpoint); `schema_version`.
- `depot: {id, latitude, longitude}`.
- `deliveries: [{id, latitude, longitude, demand}]`.
- `vehicles: [{id, capacity}]`: veículos explicitamente identificados, permitindo capacidades diferentes.
- `routing: {profile, objective_metric, max_snap_distance_meters}`: somente perfis/opções suportados; provedor definido pelo serviço e informado em capabilities.
- `config`: configuração do solver com default clássico.
- `planning_time_limit_seconds`: orçamento do planejamento dentro dos limites do servidor.

Endereços textuais não substituem coordenadas no MVP. Para distribuição apenas por quantidade de entregas, usar demanda unitária e capacidade expressa em número de entregas. Demanda e capacidade devem usar a mesma unidade, documentada pelo integrador. Perfil viário é comum à frota; não pressupor suporte a restrições específicas de caminhões se o provedor/perfil não as implementar.

Modos alternativos `matrix` e `euclidean` recebem `instance` e `config`, com contratos discriminados e explícitos. Neles `planning_status` é `not_applicable`; não apresentar resultados experimentais sem geometria como planejamento viário pronto.

### 9.6 `DeliveryPlanningResult`

- `planning_status`, `request_hash`, `instance_hash`, `solve_result`.
- `vehicle_routes: [{vehicle_id, ordered_stop_ids, load, objective_cost, distance_meters, travel_duration_seconds, geometry, legs, geometry_status}]`.
- `unused_vehicle_ids`.
- `locations: [{id, requested_location, snapped_location, snap_distance_meters}]`.
- `routing_metadata`: provedor, perfil, opções, data de consulta, versão dos dados quando disponível, métrica, arredondamento, política de cache e atribuições exigidas.
- `timings`: matriz, solver, direções e total do planejamento; `warnings` e `errors` estruturados por fase/rota.

Cada rota referencia um veículo de entrada distinto, começa/termina no depósito e cobre suas entregas exatamente uma vez. `legs` seguem os pares consecutivos das paradas; a geometria usa o mesmo trajeto e ordem. Custos vêm da matriz canônica; distância e duração viárias são medidas da consulta de direções. Em resultado parcial, campos indisponíveis são `null`, com motivo explícito; não preencher com zero ou linha reta. `ready` exige solução validada e geometrias/métricas completas para todas as rotas utilizadas. `no_feasible_solution` não significa inviabilidade comprovada, salvo indicação no `solve_result`.

## 10. Critérios de aceitação

- Defaults do piloto: até 15 entregas e 5 veículos, sem contar o depósito como entrega. Alterar os parâmetros de implantação muda a admissão e capabilities sem editar código; verificar limites inferior/superior e rejeição sem truncamento.
- Com demandas `[6, 4, 3]` e veículos de capacidades `[10, 3]`, clássico/exato respeitam a atribuição por veículo e encontram uma solução viável nas fixtures com orçamento suficiente; o validador rejeita carga 4 no veículo de capacidade 3.
- A contagem de veículos é derivada da lista; IDs duplicados, capacidade não positiva, veículo desconhecido ou usado em duas rotas são rejeitados. O conjunto viário de aceitação da etapa 1 é documentado para o município de São Paulo; pontos externos são rejeitados com erro de área de atendimento. Testar fronteiras e expansão configurada para o estado na etapa 2.
- Um pedido contendo apenas depósito, entregas em latitude/longitude, frota e configurações produz atribuições e geometrias reais sem exigir matriz do consumidor.
- Ao menos um provedor real é integrado e verificado em uma região piloto; mocks são usados em testes determinísticos, mas não substituem essa verificação de ponta a ponta.
- Uma fixture viária cuja demanda total exceda a capacidade de um veículo, mas caiba na frota, exige múltiplos veículos; verificar capacidade, visita única, IDs de veículos, ordem e retorno ao depósito.
- O exemplo `examples/map/` exibe rotas pelas ruas com cores por veículo, marcadores ordenados, depósito, métricas e veículos ociosos.
- Testar snapping excessivo, pares inalcançáveis, quota/timeout de provedor, falha parcial de geometria, cache e prazo total; nenhuma falha aciona distância euclidiana silenciosamente.
- A matriz e as geometrias usam perfil/opções compatíveis; IDs e ordem não são alterados pelo provedor. Resultado sem geometria completa nunca recebe `planning_status: ready`.
- API aceita pedido, retorna `202` e permite consultar o resultado sem manter conexão HTTP aberta durante a resolução.
- Omissão de backend escolhe `classical`; nenhuma requisição escolhe QAOA ou exact implicitamente.
- OpenAPI descreve endpoints, schemas, estados, erros e exemplos completos de integração.
- Core pode ser instalado e utilizado sem dependências HTTP ou banco; API e CLI usam os mesmos casos de uso e validador.
- Perfis de instalação e limites de dependência da seção 8.3 são verificados na CI; o core não importa FastAPI, SQLAlchemy ou Typer.
- O piloto inicia via Docker Compose com API e worker separados, migrações aplicadas e banco persistente; exemplos HTTP e Python documentam integração equivalente.
- `build-and-test.yml` bloqueia falhas de qualidade/build/test e cria no máximo um PR aberto por branch elegível, somente após sucesso; atualizações e forks respeitam as regras da seção 8.4.
- `deploy.yml` rejeita origem/SHA não aprovados, implanta uma imagem identificada por digest e verifica API/worker; validar backup, migração e recuperação em ambiente de teste antes de habilitar produção.
- Submissões simultâneas com a mesma chave idempotente geram um único job; conflito de payload retorna `409`.
- Cancelamento, corrida com conclusão, timeout de fila, fila cheia e recuperação após reinício têm comportamento verificado.
- Autenticação e isolamento entre integradores são verificados no modo de rede; resultados e logs não vazam tokens.
- Classical/exact preservam custos assimétricos; quantum os suporta ou rejeita explicitamente, sem simetrizar.
- JSON e gerador produzem instâncias normalizadas reproduzíveis com depósito e índices explícitos.
- Reordenar a entrada sem mudar seu significado preserva o hash; alterar custos, demandas ou frota muda o hash.
- Todos os backends recebem a mesma matriz inteira; custo apresentado e custo otimizado têm relação documentada.
- Validador detecta omissão/repetição de clientes, capacidade excedida, excesso de rotas, depósito interno, nós desconhecidos, rota malformada e custo incorreto.
- Fixture `[6, 6, 6]`, dois veículos e capacidade 10 não é declarada viável pelo teste de capacidade total; backend exato comprova sua inviabilidade.
- Fixtures cobrem custos zero, empates, veículos ociosos e matrizes não métricas.
- `solve --backend classical`, `quantum` e `exact` não importam nem executam outro backend.
- Ausência de dependências opcionais não impede backends independentes.
- Documento de formulação e verificações exaustivas do QUBO aprovados antes da integração QAOA.
- Preflight informa bits auxiliares e recusa orçamento insuficiente antes de alocar o estado.
- Fração viável usa multiplicidades: nove shots válidos e um inválido produzem 0,9, mesmo com apenas dois bitstrings distintos.
- Zero amostras viáveis não define `infeasibility_proven`.
- Resultado de timeout pode preservar incumbente, mas não recebe prova de optimalidade sem conclusão da busca.
- Limites de tempo, memória, avaliações e shots são exercitados em verificações de integração; registrar limite acionado e overhead de encerramento.
- Referência exata só é anexada com hash correspondente e optimalidade comprovada; nenhum solver é acionado implicitamente.
- Gap percentual é `null` para ótimo zero ou desconhecido; gap absoluto permanece disponível quando aplicável.
- Benchmark exporta todas as execuções, falhas, configurações, ambiente e regimes de cache.
- Relatório publica resultados desfavoráveis e ausência de vitórias; não declara vantagem quântica a partir de simulação local.

## 11. Plano de desenvolvimento e gates

1. Criar o layout `src`, pacote e extras, lockfile e `build-and-test.yml` da seção 8; fixar semântica CVRP, schemas, normalização, hash e matriz inteira.
2. Implementar validador, gerador viável e fixtures adversariais.
3. Implementar oráculo exato por enumeração e limites; usar DP somente se necessário.
4. Implementar baseline OR-Tools e fachada pública do core com wrapper comum de execução.
5. Implementar o adaptador openrouteservice Standard gratuito e executar a avaliação da seção 6.13 para o município de São Paulo; implementar `routing`, matriz, geometrias e `plan_deliveries`. Implementar API FastAPI/Uvicorn, OpenAPI, jobs SQLite/SQLAlchemy, migrações Alembic, worker, autenticação, idempotência e cancelamento; entregar Docker Compose, exemplo HTTP de coordenadas/frota e visualizador `examples/map/`. O piloto clássico não depende de QAOA e só está completo com integração viária real.
6. Implementar CLI Typer de apoio e exportação sobre os mesmos casos de uso; verificar paridade de contratos e isolamento do core.
7. Realizar estudo da codificação em três clientes, documentar formulação e provar equivalência em fixtures minúsculas. **Gate:** não iniciar QAOA sem validação da formulação e viabilidade de recursos.
8. Integrar QAOA local, preflight, cache de circuitos, amostragem e decodificação como backend experimental opt-in.
9. Verificar interrupção, recuperação de jobs, preservação de incumbentes e contadores de trabalho.
10. Executar manifesto de benchmark fixado previamente, com referências explícitas e limites comparáveis.
11. Implementar `deploy.yml`, configurar destino e environment `production`, validar o procedimento de release/recuperação e documentar integração, implantação do piloto, resultados, limitações, ambiente testado e defaults medidos.
12. Etapa 2 geográfica: ampliar da capital para o estado de São Paulo após as verificações da seção 6.13, independentemente da entrega experimental de QAOA.

## 12. Experimentos de portfólio

- Variar clientes, veículos e dificuldade de capacidade dentro do orçamento aprovado.
- Comparar taxa de sucesso, custo/gap, tempo total e tempo até primeira solução viável.
- Variar `p`, shots e inicialização mantendo explícito o custo total.
- Medir qubits de decisão/auxiliares, tamanho do circuito, memória e tempo conforme a codificação.
- Separar preparação com e sem cache e ajuste de parâmetros da avaliação final.
- Publicar vitórias, empates, derrotas e falhas, sem selecionar apenas resultados favoráveis.

Warm-start, mixers que preservam restrições, reparo e hardware remoto pertencem a experimentos futuros e exigem nova especificação de custos e comparabilidade.

## 13. Decisões e pendências controladas

Decidido para o MVP: piloto em São Paulo (SP), limites iniciais parametrizáveis de 15 entregas e 5 veículos, capacidades diferentes por veículo e um depósito comum; planejamento viário completo a partir de coordenadas e frota, integração obrigatória a um provedor real, geometrias por veículo e exemplo de mapa; API-first HTTP versionada, jobs assíncronos persistentes, core Python reutilizável, CLI de apoio, OR-Tools Routing como default de integração, matriz canônica inteira com suporte assimétrico clássico/exato, no máximo uma rota por veículo, QAOA local experimental opt-in, dependências opcionais e referência exata independente. Horários, prioridades e balanceamento ficam para melhorias futuras.

Pendências com momento de resolução obrigatório:

- Provedor inicial definido: openrouteservice Standard gratuito. Pendentes: configurar credencial, confirmar perfil/quotas/condições de uso, preparar pontos de teste na capital e definir cache e biblioteca de visualização. Validar resultados conforme seção 6.13. Etapa 1 = capital; etapa 2 = estado. A integração real é obrigatória, não uma extensão futura.
- Tempo máximo aceitável por planejamento e demanda simultânea de testes: definir antes de validar desempenho; os limites de 15 entregas e 5 veículos não determinam SLA nem concorrência.
- Codificação QUBO: selecionar e documentar no gate anterior ao QAOA.
- Defaults de qubits/memória/shots e limites exatos: medir na fixture e publicar antes do benchmark.
- Versões exatas de Python e de toda a stack da seção 8.1: fixar no projeto e lockfile após smoke tests na matriz de ambientes, antes de anunciar suporte.
- Verificação de licenças das versões distribuídas: concluir antes da publicação.
- Quotas, timeout de fila e política de retenção: fixar e documentar antes de liberar o piloto de integração. O framework HTTP já está definido como FastAPI com Uvicorn.
- Host/provedor de produção, acesso de deploy, permissões GHCR, proteções da branch padrão/environment e configuração de criação de PR: definir antes de habilitar os workflows correspondentes.

Nenhuma pendência permite omitir restrições, esconder custos ou declarar suporte não testado.

## 14. Nome e posicionamento

Nome de trabalho: **Quantum Route Core**. Alternativa de apresentação: **QRoute Bench**, destacando a comparação experimental. A escolha do nome público não bloqueia a implementação; verificar disponibilidade antes de publicar.

Descrição sugerida: “Serviço API-first que distribui entregas entre veículos e calcula rotas pelas ruas a partir de coordenadas, com traçados para mapa, core Python reutilizável e otimização clássica, acompanhado de QAOA experimental e benchmarks reproduzíveis.”

## 15. Referências técnicas

- [Qiskit Aer — StatevectorSimulator](https://qiskit.github.io/qiskit-aer/stubs/qiskit_aer.StatevectorSimulator.html): memória do vetor e opções de simulação.
- [Qiskit Optimization — conversores](https://qiskit-community.github.io/qiskit-optimization/tutorials/02_converters_for_quadratic_programs.html): folgas, conversão de inteiros para bits e penalidades.
- [OR-Tools — TSP e escala da matriz](https://developers.google.com/optimization/routing/tsp): custos inteiros e quantização de distâncias.
- [FastAPI — funcionalidades](https://fastapi.tiangolo.com/features/): contratos Pydantic e documentação OpenAPI.
- [SQLAlchemy — SQLite](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html): integração e comportamento do banco utilizado no piloto.
- [uv — dependências](https://docs.astral.sh/uv/concepts/projects/dependencies/): extras e grupos de dependências.
- [GitHub Actions — eventos](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows): gatilhos de CI e comportamento de PRs criados por automação.
- [GitHub Actions — deployments e environments](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments): isolamento do ambiente e regras de implantação.
- [openrouteservice — restrições](https://openrouteservice.org/restrictions/): limites por endpoint e opções, a verificar para o perfil escolhido.
- [Google Routes — uso e cobrança](https://developers.google.com/maps/documentation/routes/usage-and-billing): unidades de cobrança e limites de matriz/direções.
- [OSRM — API HTTP](https://project-osrm.org/docs/v26.4.0/http): serviços de matriz, rotas e ajuste à rede viária.

As versões efetivamente usadas serão registradas no lockfile; os exemplos da documentação não substituem a prova da formulação ou os testes de compatibilidade.
