# Etapa 1: Base da Imagem
# Usamos uma imagem Python leve (slim) baseada em Debian (Bullseye)
FROM python:3.10-slim-bullseye

# Configura o ambiente
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Etapa 2: Instalação de Dependências do Sistema
# Atualiza os pacotes e instala o FFmpeg, essencial para a conversão de áudio.
# Limpa o cache para manter a imagem pequena.
RUN apt-get update \
    && apt-get install -y ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Etapa 3: Configuração do Ambiente do Aplicativo
# Define o diretório de trabalho dentro do container
WORKDIR /app

# Cria um usuário não-root para rodar a aplicação (melhor prática de segurança)
RUN addgroup --system app && adduser --system --group app

# Etapa 4: Instalação das Dependências Python
# Copia apenas o requirements.txt primeiro para aproveitar o cache do Docker.
# A instalação só será refeita se este arquivo mudar.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Etapa 5: Copia o Código da Aplicação
# Copia os arquivos do projeto para o diretório de trabalho no container
COPY . .

# Etapa 6: Configuração Final
# Muda a propriedade dos arquivos para o usuário não-root
RUN chown -R app:app /app

# Muda para o usuário não-root
USER app

# Expõe a porta que a aplicação vai usar
EXPOSE 8000

# Comando para iniciar a aplicação quando o container for executado
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]