# Operação do piloto

Esta versão suporta um host com SQLite local e um worker. Não compartilhe o arquivo por armazenamento de rede nem inicie múltiplas réplicas de worker. O bloqueio do worker impede dois processos de assumirem o mesmo banco.

## Configuração

Copie `.env.example` para `.env`. Configure `ORS_API_KEY` localmente e tokens aleatórios distintos de pelo menos 24 caracteres:

```dotenv
QROUTE_NETWORK_MODE=true
QROUTE_AUTH_TOKENS={"integrador":"substitua-por-token-aleatorio-longo"}
QROUTE_ALLOWED_HOSTS=["api.example.com"]
QROUTE_SMOKE_TOKEN=substitua-pelo-token-de-verificacao
```

Inclua o token de verificação no mapa de integradores. Não use os textos de exemplo como segredos reais. `QROUTE_ALLOWED_HOSTS` é uma lista JSON de nomes de host explícitos usados pelo proxy; não use curingas. O Compose publica somente `127.0.0.1:8000`; configure proxy HTTPS para acesso externo. `--no-proxy-headers` evita confiar indiscriminadamente em cabeçalhos encaminhados.

O volume `quantum-route-core_qroute-data` guarda jobs, ledger/cache e backups. API e worker usam o usuário 10001. Proteja o volume e `.env`; não execute `down -v` para atualizar a aplicação.

```sh
docker compose -f deploy/compose.yaml up --build -d
docker compose -f deploy/compose.yaml exec -T api python scripts/smoke.py
# Consome quota ORS:
docker compose -f deploy/compose.yaml exec -T api python scripts/smoke.py --road
```

## GitHub Actions

`build-and-test.yml` roda somente em push para `feat/**` e `fix/**`; verifica Python 3.12 em Linux, Windows e macOS, constrói o pacote, testa instalação mínima e API/worker no Compose. Crie branches de trabalho somente com os prefixos `feat/` ou `fix/` e não faça push direto para `main`. Em push para uma branch `feat/` ou `fix/` que ainda não tem PR, o workflow pode abrir um PR de rascunho; habilite a permissão de criação de PR por Actions. Como não há execução de CI para eventos de PR nem para `main`, não configure `checks` como proteção obrigatória de PR sem outro workflow que o forneça.

`deploy.yml` é acionado por push em `main` (incluindo o push gerado pelo merge de PR). Ele confirma que o commit ainda é o topo de `main` e é o commit de merge de um PR fechado como mesclado, então repete a suíte completa de qualidade em Linux, Windows e macOS para esse SHA. A construção e o smoke test da imagem também precisam passar antes da publicação. Pushes em outras branches e builds de PR não implantam; pushes diretos para `main` também são rejeitados por não terem PR associado. Configure a proteção de revisão do environment `production`.

Para deploy, prepare explicitamente um host Linux com Docker/Compose e diretórios `/opt/quantum-route-core/{incoming,releases}`. O usuário SSH precisa escrever nesses diretórios e operar Docker. Configure `/opt/quantum-route-core/.env`, autenticação de leitura do GHCR no host e espaço para imagens/backups.

No environment `production`, configure `DEPLOY_HOST`, `DEPLOY_USER`, secrets `DEPLOY_SSH_KEY`, `DEPLOY_KNOWN_HOSTS` (chave do host conferida por canal confiável) e revisores/proteções. Habilite `DEPLOY_ENABLED=true` somente após testar o procedimento em ambiente de homologação. O workflow constrói o artefato para o próprio commit do push em `main` e implanta imagem por digest. Artefatos expiram em 14 dias; rollback depende da disponibilidade do artefato e compatibilidade de schema. Para preservar a regra de deploy somente após merge, correções emergenciais também devem entrar por PR; o rollback operacional no host continua sujeito ao procedimento de recuperação abaixo.

## Atualização e recuperação

O script pausa admissão na versão existente, aguarda fila e jobs ativos esvaziarem, para API/worker, faz backup consistente via API SQLite, aplica migração, inicia serviços e verifica cálculo e planejamento viário. Se a fila não esvaziar dentro do orçamento, ele aborta sem migrar e reabre a versão anterior. Não aumenta silenciosamente o prazo de implantação para drenar uma fila grande.

Backups ficam em `/app/var/backups` dentro do volume; copie-os para armazenamento externo protegido conforme política operacional. O backup local no mesmo disco não protege contra perda do host.

Se startup ou verificação falhar, examine logs, imagem e schema antes de reabrir admissão. Não há downgrade automático: restaurar imagem antiga sobre schema incompatível pode danificar dados. Mantenha admissão pausada, pare API/worker, faça cópia adicional do estado atual e restaure o backup escolhido com os serviços parados; remova arquivos WAL/SHM residuais apenas desse banco restaurado. Inicie a imagem compatível, execute migração/verificações e só então libere admissão. Ensaiar esse procedimento é obrigatório antes de produção.

Monitore `/health`, conclusão de jobs e erros de provedor; `/health` sozinho não testa worker ou ruas.

## Limites conhecidos

A memória é monitorada por RSS no subprocesso, com intervalo de amostragem e prazo de encerramento; isso não é isolamento rígido por cgroup. O orçamento supervisionado inclui até cinco segundos de inicialização e encerramento cooperativo antes de terminar o processo. No core em processo, configure isolamento próprio se precisar de proteção rígida de memória. Jobs não são retomados do ponto de interrupção.

Os limites padrão por integrador são 20 jobs ativos, 10 submissões por minuto e 32 MB retidos; o banco tem teto lógico de 256 MB, snapshots são limitados a 4 MB e a API suspende admissão abaixo de 256 MB livres no disco. A quota ORS diária e por minuto é compartilhada, com cada integrador limitado por padrão a 25% de cada teto. Ajuste esses valores conforme volume e acordos do provedor; não configure cotas individuais que, somadas, excedam a quota global.

A validação em Docker, GitHub e host deve ser registrada em [status.md](status.md); existência dos arquivos não comprova implantação.
