# Deployment no Oracle Cloud Free Tier (Linux AMD64)

Guia passo a passo para hospedar o sistema de correção de provas em uma instância gratuita da Oracle Cloud.

## Pré-requisitos

- Conta Oracle Cloud (gratuita no nível Always Free)
- Acesso administrativo ao console
- Cliente SSH (terminal no Linux/macOS, PuTTY no Windows)

## Parte 1: Configurar a Instância Free Tier

### 1. Criar a instância Cloud compute (Always Free)

1. Acesse [Oracle Cloud Console](https://cloud.oracle.com)
2. No menu lateral → **Compute** → **Instances**
3. Clique em **Create instance**
4. Configure:
   - **Name**: `correcao-cpe` (ou outro nome descritivo)
   - **Availability domain**: Escolha qualquer uma (ex.: `IAD: US-ASHBURN-1-AD-1`)
   - **Image**: `Oracle Linux 8` (ARM ou AMD64; AMD64 é mais compatível com OpenCV)
   - **Shape**: **VM.Standard.E4.Flex** (ou **VM.Standard.E3.Flex** se a primeira não estiver disponível)
   - **Number of OCPUs**: 1
   - **Memory**: 6 GB
   - **Networking**:
     - Virtual Cloud Network (VCN): `Create new VCN` (ou use um existente)
     - Public IP: **YES** (necessário para acessar via browser)
   - **SSH keys**: **Generate a key pair** ou **Paste SSH public keys**
     - Salve a chave privada (`.pem`) em um local seguro

5. Clique em **Create**

### 2. Configurar Security Lists (firewall)

Após criar a instância:

1. Na página da instância, clique no nome do **VCN**
2. Acesse **Security Lists** → clique na security list padrão (ex.: `default security list for VCN`)
3. Edite as **Inbound Rules** adicionando:
   - **Rule 1** (Dashboard Streamlit):
     - Source: `0.0.0.0/0`
     - Source Type: `CIDR`
     - IP Protocol: `TCP`
     - Source port range: (deixe em branco)
     - Destination port range: `8501` (Streamlit)
     - Description: `Streamlit Dashboard`
   - **Rule 2** (API FastAPI):
     - Source: `0.0.0.0/0`
     - Source Type: `CIDR`
     - IP Protocol: `TCP`
     - Source port range: (deixe em branco)
     - Destination port range: `8001` (API)
     - Description: `FastAPI Backend`

4. Clique em **Update Security Lists**

### 3. Acessar a instância via SSH

No seu terminal:

```bash
# Substitua `path/to/private-key.pem` pelo caminho da chave que você baixou
# e `PUBLIC_IP` pelo IP público da instância
ssh -i path/to/private-key.pem opc@PUBLIC_IP
```

Exemplo:
```bash
ssh -i ~/.ssh/oracle.pem opc@150.136.123.456
```

## Parte 2: Instalar Dependências no Servidor

### 4. Atualizar o sistema e instalar pacotes base

Pacotes base (nomes do Oracle Linux / `dnf` - **não** use nomes de Debian/Ubuntu
como `libgl1-mesa-glx`, que não existem aqui):

```bash
sudo dnf update -y
sudo dnf install -y gcc gcc-c++ make cmake git wget unzip \
    python3 python3-pip python3-devel \
    policycoreutils-python-utils
```

> **OpenCV sem bibliotecas de GUI:** o projeto usa `opencv-python-headless`
> (ver `back/requirements.txt`), que **não** depende de `libGL`, X11 ou OpenGL.
> Por isso não é preciso instalar `mesa-libGL`, `libSM`, `libXext` etc. no
> servidor. Se em algum momento você trocar para o `opencv-python` normal, aí
> sim precisará destes pacotes (nomes do Oracle Linux):
>
> ```bash
> sudo dnf install -y mesa-libGL glib2 libSM libXext libXrender libgomp
> ```

### 5. Criar um ambiente virtual e instalar dependências

```bash
# Clonar o projeto (se não estiver no repositório local)
git clone https://github.com/seu-usuario/sistema-correcao-cpe.git
cd sistema-correcao-cpe

# Backend
cd back
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
deactivate

# Frontend (venv SEPARADO - back e front não compartilham ambiente)
cd ../front
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
deactivate
cd ..
```

> O backend e o frontend têm **venvs separados** (`back/.venv` e `front/.venv`)
> porque pedem versões incompatíveis de `starlette`. Os dois serviços systemd
> apontam para o venv correspondente, então ambos precisam existir.

**Importante para Oracle Cloud ARM64/AMD64:**
- `requirements.txt` usa `opencv-python-headless`, que tem *wheels* prontos tanto
  para **AMD64** quanto para **ARM64** - o `pip install` deve funcionar direto nos
  dois, sem compilar nada.
- Se o `pip` tentar compilar OpenCV do zero numa instância ARM64 (raro com o
  headless), confira se `gcc`, `cmake` e `python3-devel` estão instalados (passo 4).

### 6. Criar o banco de dados e rodar migrações

Ainda dentro de `back/` com o venv ativado:

```bash
cd ~/sistema-correcao-cpe/back
source .venv/bin/activate

# O padrão usa SQLite em back/cpe_omr.db (criado automaticamente pela migração).
# Rode a partir de back/ para o arquivo cair no lugar certo.
alembic upgrade head
```

### 7. Configurar variáveis de ambiente (opcional, mas recomendado)

Crie um arquivo `.env` na raiz do `back/`:

```bash
cd back
cat > .env <<EOF
CPE_DATABASE_URL=sqlite:///cpe_omr.db
CPE_API_HOST=0.0.0.0
CPE_API_PORT=8001
EOF
```

## Parte 3: Configurar Serviços (Systemd)

> **Importante (SELinux + diretório home):** no Oracle Linux, um serviço systemd
> **não consegue executar binários que estão dentro de `/home`** — eles recebem o
> rótulo SELinux `user_home_t`, e a tentativa falha com
> `status=203/EXEC: Permission denied` (o serviço fica reiniciando sem parar).
> Há dois jeitos de resolver; escolha um antes de criar os serviços:
>
> **Opção A — relabel do venv (mantém o projeto em `/home/opc`):**
>
> ```bash
> sudo dnf install -y policycoreutils-python-utils   # fornece o `semanage`
> sudo semanage fcontext -a -t bin_t "/home/opc/sistema-correcao-cpe/back/.venv/bin(/.*)?"
> sudo semanage fcontext -a -t bin_t "/home/opc/sistema-correcao-cpe/front/.venv/bin(/.*)?"
> sudo restorecon -Rv /home/opc/sistema-correcao-cpe/back/.venv/bin
> sudo restorecon -Rv /home/opc/sistema-correcao-cpe/front/.venv/bin
> ```
>
> **Opção B — mover o projeto para `/opt`** (fora do home, sem a restrição):
>
> ```bash
> sudo mv /home/opc/sistema-correcao-cpe /opt/sistema-correcao-cpe
> sudo chown -R opc:opc /opt/sistema-correcao-cpe
> # recrie os venvs (os caminhos mudaram) e ajuste os caminhos nos units abaixo
> ```
>
> Os exemplos abaixo usam `/home/opc/...`. Se escolher a Opção B, troque por
> `/opt/...` em `WorkingDirectory`, `PATH` e `ExecStart`.

### 8. Criar serviço do backend (FastAPI)

Crie o arquivo `/etc/systemd/system/cpe-api.service`:

```bash
sudo tee /etc/systemd/system/cpe-api.service > /dev/null <<'EOF'
[Unit]
Description=CPE OMR API (FastAPI backend)
After=network.target

[Service]
User=opc
Group=opc
WorkingDirectory=/home/opc/sistema-correcao-cpe/back
Environment="PATH=/home/opc/sistema-correcao-cpe/back/.venv/bin"
Environment="CPE_DATABASE_URL=sqlite:///cpe_omr.db"
Environment="CPE_API_HOST=0.0.0.0"
Environment="CPE_API_PORT=8001"
ExecStart=/home/opc/sistema-correcao-cpe/back/.venv/bin/python -m uvicorn api.app:app --host 0.0.0.0 --port 8001
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Recarregar e iniciar o serviço:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cpe-api
sudo systemctl start cpe-api
sudo systemctl status cpe-api  # confirme que está "active (running)"
```

### 9. Criar serviço do frontend (Streamlit)

Crie o arquivo `/etc/systemd/system/cpe-dashboard.service`:

```bash
sudo tee /etc/systemd/system/cpe-dashboard.service > /dev/null <<'EOF'
[Unit]
Description=CPE OMR Dashboard (Streamlit frontend)
After=network.target cpe-api.service
Wants=cpe-api.service

[Service]
User=opc
Group=opc
WorkingDirectory=/home/opc/sistema-correcao-cpe/front
Environment="PATH=/home/opc/sistema-correcao-cpe/front/.venv/bin"
Environment="CPE_API_URL=http://localhost:8001"
ExecStart=/home/opc/sistema-correcao-cpe/front/.venv/bin/streamlit run app.py --server.port 8501 --server.headless true --server.enableCORS false
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
```

Recarregar e iniciar:

```bash
sudo systemctl daemon-reload
sudo systemctl enable cpe-dashboard
sudo systemctl start cpe-dashboard
sudo systemctl status cpe-dashboard
```

## Parte 4: Configurar Proxy Inverso (Nginx) + SSL (opcional, mas recomendado)

### 10. Instalar Nginx

```bash
sudo dnf install -y nginx
sudo systemctl enable nginx
sudo systemctl start nginx
```

### 11. Configurar Nginx como proxy reverso

Crie `/etc/nginx/conf.d/cpe.conf`:

```bash
sudo tee /etc/nginx/conf.d/cpe.conf > /dev/null <<'EOF'
upstream cpe_api {
    server 127.0.0.1:8001;
}

upstream cpe_dashboard {
    server 127.0.0.1:8501;
}

server {
    listen 80;
    server_name 140.238.186.202;  # troque pelo seu IP público ou domínio

    # API FastAPI em /api/ (ex.: /api/health, /api/docs, /api/results)
    # O prefixo /api é removido antes de repassar ao backend.
    location /api/ {
        rewrite ^/api/(.*)$ /$1 break;
        proxy_pass http://cpe_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Streamlit Dashboard na raiz (/)
    location / {
        proxy_pass http://cpe_dashboard;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSockets (o Streamlit depende disso para atualizar a tela)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
    }
}
EOF
```

> Com esta configuração, o **frontend** (Streamlit) atende na raiz `/` e a
> **API** em `/api/`. O frontend fala com a API internamente por
> `http://localhost:8001` (variável `CPE_API_URL` no serviço), então não depende
> do caminho `/api/` — este é só para você inspecionar a API pelo navegador.

Testar configuração e reiniciar:

```bash
sudo nginx -t
sudo systemctl restart nginx
```

### 11.1 Liberar o Nginx no SELinux (OBRIGATÓRIO no Oracle Linux)

O Oracle Linux vem com o SELinux em modo *enforcing*, que **por padrão proíbe o
Nginx de abrir conexões de rede** para o backend local. Sem este passo, você verá
**502 Bad Gateway** mesmo com o backend saudável. Habilite a permissão:

```bash
sudo setsebool -P httpd_can_network_connect 1
sudo systemctl restart nginx
```

> Esta é a causa nº 1 de 502 Bad Gateway em instâncias Oracle Linux. Se o
> `curl http://127.0.0.1:8001/health` responde na instância mas o IP público dá
> 502, é quase certo que seja isto.

### 12. Configurar Firewall (firewalld)

```bash
# Permitir HTTP e HTTPS
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

## Parte 5: Acessar e Testar

### 13. Abrir no navegador

- **Dashboard**: `http://IP_PÚBLICO_DA_INSTÂNCIA/` (Streamlit, na raiz)
- **API (Swagger UI)**: `http://IP_PÚBLICO_DA_INSTÂNCIA/api/docs`
- **Health check**: `http://IP_PÚBLICO_DA_INSTÂNCIA/api/health`

### 14. Fazer o primeiro upload de prova

1. Acesse a aba **Correção**
2. Envie o gabarito (`back/samples/demo-test/gabarito.csv`) e/ou as imagens das provas
3. Clique em **Corrigir provas**
4. Acesse a aba **Dashboard** para ver os resultados

### 15. Testar com os samples já criados

Para carregar o sample "Demo 1" sem enviar imagens:

```bash
# No terminal da instância
curl -X POST http://localhost:8001/gradings/results-csv \
  -F "results_csv=@samples/demo-test/ResultsByQuestion.csv" \
  -F "exam_name=Demo 1" \
  -F "sequence=1" \
  -F "applied_on=2026-10-02" \
  -F 'student_names={"aluno1.png":"Ana Silva","aluno2.png":"Bruno Lima","aluno3.png":"Carla Oliveira"}' \
  -F 'student_classes={"aluno1.png":"3A","aluno2.png":"3A","aluno3.png":"3A"}' \
  -F 'class_turnos={"3A":"vespertino"}'
```

## Parte 6: Manutenção

### Logs

```bash
# Backend
sudo journalctl -u cpe-api -f

# Dashboard
sudo journalctl -u cpe-dashboard -f

# Nginx
sudo journalctl -u nginx -f
```

### Reiniciar serviços

```bash
sudo systemctl restart cpe-api cpe-dashboard
```

### Atualizar o código

```bash
cd /home/opc/sistema-correcao-cpe
git pull
# Se houver mudanças nas dependências:
cd back && source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
cd ../front && source .venv/bin/activate && pip install -r requirements.txt
# Reiniciar os serviços
sudo systemctl restart cpe-api cpe-dashboard
```

### Backup do banco de dados

O SQLite fica em `back/cpe_omr.db`. Copie para segurança:

```bash
cp /home/opc/sistema-correcao-cpe/back/cpe_omr.db /home/opc/backup-cpe.db
```

Para usar PostgreSQL (recomendado para produção), substitua `CPE_DATABASE_URL` por uma URL do Oracle Autonomous Database ou PostgreSQL.

## Troubleshooting

### Service não inicia

```bash
# Verificar erros
sudo journalctl -u cpe-api -n 50
sudo journalctl -u cpe-dashboard -n 50

# Verificar permissões
ls -la /home/opc/sistema-correcao-cpe
```

### `status=203/EXEC` + `Permission denied` ao executar o python do venv

Sintoma no log:

```
Failed to locate executable /home/opc/.../.venv/bin/python: Permission denied
cpe-api.service: Main process exited, code=exited, status=203/EXEC
```

Causa: o binário existe, mas está em `/home`, onde o SELinux o rotula como
`user_home_t` — e um serviço systemd não tem permissão para executar binários com
esse rótulo. Não é um problema do app; ele nem chega a rodar.

Confirme:

```bash
ls -lZ /home/opc/sistema-correcao-cpe/back/.venv/bin/python   # mostra user_home_t
sudo ausearch -m avc -ts recent | grep -i python | tail -5
```

Corrija relabelando o venv (ou mova o projeto para `/opt`, ver a nota no início
da Parte 3):

```bash
sudo dnf install -y policycoreutils-python-utils
sudo semanage fcontext -a -t bin_t "/home/opc/sistema-correcao-cpe/back/.venv/bin(/.*)?"
sudo semanage fcontext -a -t bin_t "/home/opc/sistema-correcao-cpe/front/.venv/bin(/.*)?"
sudo restorecon -Rv /home/opc/sistema-correcao-cpe/back/.venv/bin
sudo restorecon -Rv /home/opc/sistema-correcao-cpe/front/.venv/bin
sudo systemctl restart cpe-api cpe-dashboard
```

### 502 Bad Gateway (Nginx responde, backend não)

O Nginx está no ar, mas não alcança o backend. Verifique nesta ordem:

```bash
# 1. O backend está rodando e escutando?
sudo systemctl status cpe-api
sudo ss -tlnp | grep 8001
curl -i http://127.0.0.1:8001/health      # responde localmente?

# 2. Se responde local mas o IP público dá 502 -> SELinux bloqueia o Nginx:
sudo setsebool -P httpd_can_network_connect 1
sudo systemctl restart nginx
```

### Porta 8001/8501 não responde

```bash
# Verificar se o serviço está rodando
sudo systemctl status cpe-api
sudo systemctl status cpe-dashboard

# Verificar se a porta está aberta
sudo ss -tlnp | grep ':8001'
sudo ss -tlnp | grep ':8501'
```

### Error: Cannot import name 'ServerProtocol' from 'websockets'

Isso ocorre quando há incompatibilidade de versões. Use a versão correta no backend:

```bash
cd back
source .venv/bin/activate
uv pip install "websockets>=11,<13"
sudo systemctl restart cpe-api
```

### Erro `libGL.so.1: cannot open shared object file`

O `opencv-python` (versão com GUI) exige bibliotecas de sistema do OpenGL/X11 que
não existem num servidor headless. O projeto já usa `opencv-python-headless` para
evitar isso. Se você vir este erro, está com a versão errada do OpenCV instalada:

```bash
cd ~/sistema-correcao-cpe/back && source .venv/bin/activate
pip uninstall -y opencv-python
pip install opencv-python-headless
sudo systemctl restart cpe-api
```

### Erro `No enumerators available` / `NoneType object has no attribute 'width'`

Vem do `screeninfo`, que tenta detectar monitores - não há display num servidor.
O código já trata isso (`src/utils/interaction.py` cai num monitor fictício). Se
aparecer, confirme que o `src/` está atualizado (`git pull`) e reinicie o serviço.

### `Missing optional dependency 'openpyxl'`

Acontece ao enviar um gabarito `.xlsx`. Já está em `requirements.txt`; se faltar:

```bash
cd ~/sistema-correcao-cpe/back && source .venv/bin/activate
pip install openpyxl
sudo systemctl restart cpe-api
```

## Custos

- **Compute**: AMD64/ARM64 Always Free (2 OCPU, 12 GB RAM) ✅
- **Public IP**: Gratuito enquanto a instância estiver rodando ✅
- **Bandwidth**: 10 TB/mês ✅
- **Armazenamento**: 200 GB NVMe (temporário) + Block Volume opcional

Se usar PostgreSQL ou Autonomous Database, verifique os planos gratuitos do Oracle Cloud.

---

**Dica**: com `opencv-python-headless`, tanto **AMD64** (`VM.Standard.E4.Flex`)
quanto **ARM64** (`VM.Standard.A1.Flex`, o maior Always Free) funcionam sem
complicação de OpenCV. Escolha pela capacidade: o ARM64 Always Free oferece até
4 OCPUs e 24 GB de RAM, bem mais folga que o AMD64.
