# Deployment no Oracle Cloud Free Tier com Docker Compose

Este guia é a versão Docker do deploy do projeto. Ele mantém a configuração anterior em [DEPLOYMENT-ORACLE-CLOUD.md](DEPLOYMENT-ORACLE-CLOUD.md) intacta e oferece uma alternativa mais simples e robusta para Oracle Cloud.

## Quando usar esta abordagem

Use esta opção quando você quiser:

- evitar `systemd` e `venv` separados em `/home`
- rodar backend e frontend em containers isolados
- manter o deploy mais previsível e fácil de reiniciar
- reduzir problemas de SELinux, permissões e dependências do host

## Visão geral da arquitetura

- `api` → container do backend FastAPI
- `dashboard` → container do frontend Streamlit
- `nginx` → container de proxy reverso
- `sqlite-data` → volume persistente para o banco SQLite

A estrutura fica assim:

- frontend público na raiz `/`
- API acessível só pelo dashboard, dentro da rede do Docker (não é publicada)
- banco em volume Docker persistente

---

## Parte 1: Criar a instância Oracle Cloud

### 1. Criar a VM

1. Acesse o [Oracle Cloud Console](https://cloud.oracle.com)
2. Vá em **Compute** → **Instances**
3. Clique em **Create instance**
4. Configure:
   - **Name**: `correcao-cpe-docker`
   - **Image**: `Ubuntu 22.04` ou `Ubuntu 24.04` (recomendado)
   - **Shape**: `VM.Standard.E4.Flex` ou `VM.Standard.E3.Flex`
   - **OCPUs**: 1
   - **Memory**: 6 GB
   - **Networking**: VCN com IP público
   - **SSH keys**: gere ou carregue uma chave pública

### 2. Liberar as portas no firewall da instância

No painel da instância, acesse o **VCN** e depois a **Security List** padrão.

Adicione as regras de entrada:

- `SSH`:
  - TCP
  - 22
  - origem: `0.0.0.0/0`

- `HTTP`:
  - TCP
  - 80
  - origem: `0.0.0.0/0`

- `HTTPS` (opcional, se você for usar TLS):
  - TCP
  - 443
  - origem: `0.0.0.0/0`

---

## Parte 2: Conectar na VM

```bash
ssh -i ~/.ssh/oracle.pem ubuntu@PUBLIC_IP
```

Exemplo:

```bash
ssh -i ~/.ssh/oracle.pem ubuntu@150.136.123.456
```

---

## Parte 3: Instalar Docker no Ubuntu Server

Atualize o sistema:

```bash
sudo apt update && sudo apt upgrade -y
```

Instale os pacotes necessários:

```bash
sudo apt install -y ca-certificates curl gnupg lsb-release
```

Adicione a chave GPG oficial do Docker:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
```

Adicione o repositório do Docker:

```bash
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
```

Instale o Docker Engine e o plugin do Compose:

```bash
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Ative e inicie o serviço:

```bash
sudo systemctl enable --now docker
sudo systemctl status docker
```

Adicione seu usuário ao grupo `docker`:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Confirme:

```bash
docker --version
docker compose version
```

---

## Parte 4: Clonar o projeto

```bash
cd ~
git clone https://github.com/seu-usuario/sistema-correcao-cpe.git
cd sistema-correcao-cpe
```

Se o repositório já estiver no ambiente local, pode simplesmente entrar na pasta raiz do projeto.

---

## Parte 5: Subir o ambiente com Docker Compose

Na raiz do projeto, execute:

```bash
docker compose up -d --build
```

Isso vai construir e iniciar:

- backend FastAPI
- dashboard Streamlit
- Nginx como proxy reverso

O container da API cria ou atualiza o banco sozinho ao iniciar
(`python -m db.migrate`, o equivalente a `alembic upgrade head`); não é
preciso rodar migrações à mão. O dashboard só sobe depois que a API responde em
`/health`.

Cada imagem carrega o próprio código: depois de um `git pull`, é o `--build` que
leva o código novo para os containers.

Verifique os containers:

```bash
docker compose ps
```

Verifique os logs:

```bash
docker compose logs -f
```

Se quiser ver só o backend:

```bash
docker compose logs -f api
```

Se quiser ver o dashboard:

```bash
docker compose logs -f dashboard
```

---

## Parte 6: Testar o deploy

### API

A API não é publicada no host, então o teste roda dentro do container:

```bash
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8001/health').read().decode())"
```

Resposta esperada:

```json
{"status":"ok"}
```

### Dashboard direto

```bash
curl -I http://localhost:8501/
```

### Acesso pela porta 80 via Nginx

```bash
curl -I http://localhost/
```

Ou abra no navegador:

- Dashboard: `http://IP_PUBLICO/`

---

## Parte 7: Estrutura importante do projeto

Os arquivos relevantes já foram criados para a abordagem Docker:

- [docker-compose.yml](docker-compose.yml)
- [nginx-DEPRECATED.conf](nginx-DEPRECATED.conf) — não é mais usado; o proxy reverso do servidor acessa os containers pela rede `cpe-proxy`
- [back/Dockerfile](back/Dockerfile)
- [front/Dockerfile](front/Dockerfile)
- [back/.dockerignore](back/.dockerignore) e [front/.dockerignore](front/.dockerignore)
- [back/docker-entrypoint.sh](back/docker-entrypoint.sh) — roda as migrações do banco antes de subir a API
- [docker-compose.dev.yml](docker-compose.dev.yml) — só para desenvolvimento (código montado do checkout, com reload)

Esses arquivos já deixam o projeto pronto para rodar em Docker sem depender de `systemd`.

---

## Parte 8: Reiniciar, atualizar e manter

### Reiniciar tudo

```bash
docker compose restart
```

### Atualizar o código

```bash
git pull

docker compose up -d --build
```

### Ver logs

```bash
docker compose logs -f --tail=200
```

### Parar tudo

```bash
docker compose down
```

### Remover volumes persistentes (cuidado)

```bash
docker compose down -v
```

---

## Parte 9: Persistência do SQLite

O SQLite é persistido via volume Docker:

```yaml
volumes:
  sqlite-data:
```

Isso garante que o banco continue existindo mesmo quando o container é recriado.

O volume `sqlite-data` é montado em `/var/lib/cpe` dentro do container e guarda
tudo o que precisa sobreviver a um rebuild:

```text
/var/lib/cpe/cpe_omr.db      # banco (CPE_DATABASE_URL)
/var/lib/cpe/gradings/       # ResultsByQuestion.csv e folhas marcadas de cada simulado (CPE_ARTIFACTS_DIR)
```

> Versões anteriores montavam o volume em `/app/data`, por cima do pacote Python
> `data` (modelos e migrações; hoje ele se chama `db`), o que fazia o container continuar usando a cópia
> antiga desse código depois de um `git pull`. O volume é o mesmo: o
> `cpe_omr.db` existente aparece em `/var/lib/cpe/cpe_omr.db` sem migração
> manual. Basta `docker compose up -d --build`.

---

## Parte 10: HTTPS / SSL (opcional)

Se você quiser expor a aplicação com HTTPS, há duas opções boas:

### Opção A — Cloudflare + SSL externo

- use o Cloudflare DNS para apontar o domínio
- deixe o Cloudflare fazer o TLS
- mantenha o app atrás do proxy no port 80

### Opção B — Certbot no host, com Nginx externo

Se preferir terminar TLS no host em vez do container, você pode instalar um Nginx no host e configurar proxy reverso para `localhost:8501` (a API não é publicada no host).

Mas para deploy simples e rápido em Oracle Cloud, a abordagem recomendada é:

- manter o Docker Compose
- deixar o Nginx dentro do container
- usar Cloudflare ou um load balancer com TLS

---

## Troubleshooting

### `docker: permission denied while trying to connect to the Docker daemon socket`

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### Container não sobe

```bash
docker compose logs -f
```

### Porta 80/443 não acessível

Verifique a Security List da VM e confirme que o VCN está liberando as portas.

### API não responde

```bash
docker compose logs -f api
```

### Dashboard não carrega

```bash
docker compose logs -f dashboard
```

---

## Vantagens desta abordagem em relação ao systemd

- menos problemas com SELinux
- menos risco de venv e permissões quebradas em `/home`
- processo de deploy mais repetível
- atualização fácil via `git pull` + `docker compose up -d --build`
- isolamento real entre backend e frontend

---

## Recomendação final

Para Oracle Cloud Free Tier, a opção mais simples e estável é:

- VM Oracle Linux
- Docker + Docker Compose
- Nginx em container
- SQLite em volume Docker

Essa abordagem costuma ser bem mais confiável do que manter dois `systemd` separados e lidar com venvs e SELinux.

> Esta guia é a alternativa Docker da versão anterior em [DEPLOYMENT-ORACLE-CLOUD.md](DEPLOYMENT-ORACLE-CLOUD.md). Ambas podem coexistir: a antiga serve como referência de systemd, e esta serve como caminho recomendado para deploy moderno em containers.
