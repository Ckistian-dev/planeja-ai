import os
import json
import httpx
import google.generativeai as genai
import asyncio
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from dotenv import load_dotenv
import base64
from task_manager import TaskManager
import logging
from collections import defaultdict, deque
import subprocess
from datetime import datetime
from itertools import cycle

# --- Configuração de Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Carregando as Configurações ---
load_dotenv()

def load_config():
    """Carrega e valida a configuração do ambiente."""
    try:
        with open("system_prompt.txt", "r", encoding="utf-8") as f:
            system_prompt = f.read()
    except FileNotFoundError:
        logging.critical("🚨 ERRO CRÍTICO: Arquivo 'system_prompt.txt' não encontrado.")
        exit()

    api_keys_str = os.getenv("GOOGLE_API_KEYS")
    google_api_keys = [key.strip() for key in api_keys_str.split(',')] if api_keys_str else []

    config = {
        "GOOGLE_API_KEYS": google_api_keys,
        "GEMINI_MODEL_NAME": os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash"),
        "EVOLUTION_API_URL": os.getenv("EVOLUTION_API_URL"),
        "EVOLUTION_API_KEY": os.getenv("EVOLUTION_API_KEY"),
        "EVOLUTION_INSTANCE_NAME": os.getenv("EVOLUTION_INSTANCE_NAME"),
        "TARGET_GROUP_JID": os.getenv("TARGET_GROUP_JID"), # <-- MODIFICADO
        "GOOGLE_SHEET_ID": os.getenv("GOOGLE_SHEET_ID"),
        "SYSTEM_PROMPT": system_prompt,
    }

    if not config["GOOGLE_API_KEYS"]:
         logging.critical(f"🚨 ERRO CRÍTICO: Nenhuma chave foi definida em GOOGLE_API_KEYS no arquivo .env")
         exit()

    # <-- MODIFICADO: Valida a variável de grupo
    missing_vars = [key for key, value in config.items() if not value and key not in ["GOOGLE_API_KEYS"]]
    if missing_vars:
        logging.critical(f"🚨 ERRO CRÍTICO: Variáveis não definidas no .env ou prompt vazio: {', '.join(missing_vars)}")
        exit()
    return config

config = load_config()

# --- Rotacionador de Chaves de API ---
key_cycler = cycle(config['GOOGLE_API_KEYS'])
def get_next_api_key():
    return next(key_cycler)

# --- Inicialização dos Serviços ---
try:
    sheets = TaskManager(spreadsheet_id=config['GOOGLE_SHEET_ID'])
    logging.info("✅ Serviço do Google Sheets (Tarefas) inicializado com sucesso.")
except Exception as e:
    logging.critical(f"🚨 ERRO CRÍTICO durante a inicialização: {e}", exc_info=True)
    exit()

# --- Cache de Histórico de Conversa ---
conversation_history = defaultdict(lambda: deque(maxlen=20))

# --- Funções Auxiliares (sem alterações) ---
async def enviar_resposta_whatsapp(jid: str, text: str):
    url = f"{config['EVOLUTION_API_URL']}/message/sendText/{config['EVOLUTION_INSTANCE_NAME']}"
    headers = {"Content-Type": "application/json", "apikey": config['EVOLUTION_API_KEY']}
    payload = {
        "number": jid,
        "text": text,
        "options": {
            "delay": 1200,
            "presence": "composing"
        }
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
        logging.info(f"Resposta enviada para {jid}: {text}")
        # A resposta do assistente não precisa de histórico por participante, apenas o envio
    except httpx.RequestError as e:
        logging.error(f"🚨 Erro ao enviar resposta via Evolution API: {e}")

def convert_audio_to_mp3(ogg_path: str, mp3_path: str):
    try:
        command = ["ffmpeg", "-y", "-i", ogg_path, "-acodec", "libmp3lame", mp3_path]
        subprocess.run(command, check=True, capture_output=True, text=True)
        logging.info(f"Áudio convertido com sucesso para {mp3_path}")
        return True
    except FileNotFoundError:
        logging.error("🚨 ERRO: ffmpeg não está instalado ou não está no PATH do sistema.")
        return False
    except subprocess.CalledProcessError as e:
        logging.error(f"🚨 Erro do ffmpeg durante a conversão: {e.stderr}")
        return False

# --- Lógica Principal de Processamento ---
async def process_message(data: dict):
    key_info = data.get("data", {}).get("key", {})
    group_jid = key_info.get("remoteJid")
    participant_jid = key_info.get("participant") # <-- MODIFICADO: Quem enviou a mensagem no grupo
    msg_obj = data.get("data", {}).get("message", {})
    
    # <-- MODIFICADO: Usa o participante para o histórico, ou o grupo se não houver participante (ex: mensagem de serviço)
    history_jid = participant_jid or group_jid

    content_for_analysis = None
    prompt_instruction = ""

    # 1. Extrair conteúdo da mensagem (Áudio ou Texto)
    if "audioMessage" in msg_obj:
        prompt_instruction = "Transcreva o áudio a seguir e execute a ação solicitada na tarefa:"
        # ... (lógica de áudio sem alteração)
        conversation_history[history_jid].append("Usuário: [Enviou um áudio]")
    
    elif "conversation" in msg_obj or "extendedTextMessage" in msg_obj:
        text = msg_obj.get("conversation") or msg_obj.get("extendedTextMessage", {}).get("text", "")
        if text.strip():
            prompt_instruction = "Analise o texto a seguir para gerenciar as tarefas:"
            content_for_analysis = [text]
            conversation_history[history_jid].append(f"Usuário ({history_jid.split('@')[0]}): {text}")

    if not content_for_analysis:
        return

    # 2. Montar Dossiê e Chamar a IA
    try:
        api_key_to_use = get_next_api_key()
        logging.info(f"Usando chave de API terminada em: ...{api_key_to_use[-4:]}")
        genai.configure(api_key=api_key_to_use)
        model = genai.GenerativeModel(
            model_name=config['GEMINI_MODEL_NAME'],
            system_instruction=config['SYSTEM_PROMPT']
        )
        
        dados_planilha = sheets.get_all_tasks_as_json()
        historico_recente = "\n".join(list(conversation_history[history_jid]))
        current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        
        prompt_final = f"""
            Data e Hora Atual: {current_time}

            HISTÓRICO DA CONVERSA (com o usuário {history_jid.split('@')[0]}):
            {historico_recente}
            ---
            DADOS ATUAIS DA PLANILHA DE TAREFAS:
            {dados_planilha}
            ---
            NOVO COMANDO DO USUÁRIO:
            {prompt_instruction}
            """
        gemini_payload = [prompt_final] + content_for_analysis
        response = model.generate_content(gemini_payload)
        
        # 3. Processar a Resposta da IA
        cleaned_response_text = response.text.strip().replace("```json", "").replace("```", "")
        analysis = json.loads(cleaned_response_text)
        
        additions = analysis.get("tarefas_para_adicionar", [])
        updates = analysis.get("tarefas_para_atualizar", [])
        deletions = analysis.get("tarefas_para_excluir", [])
        confirmation_msg = analysis.get("mensagem_confirmacao")

        if additions: sheets.add_tasks(additions)
        if updates: sheets.update_tasks(updates)
        if deletions: sheets.delete_tasks(deletions)
        
        if confirmation_msg:
            # <-- MODIFICADO: Responde para o grupo
            await enviar_resposta_whatsapp(group_jid, confirmation_msg) 
        else:
            logging.warning("IA não gerou mensagem de confirmação.")

    except (json.JSONDecodeError, ValueError) as e:
        logging.warning(f"Resposta do Gemini não foi um JSON válido: '{response.text}'. Erro: {e}. Enviando como texto.")
        await enviar_resposta_whatsapp(group_jid, response.text)
    except Exception as e:
        logging.error(f"🚨 Erro no ciclo de análise do Gemini: {e}", exc_info=True)
        await enviar_resposta_whatsapp(group_jid, "Ocorreu um erro interno e não pude processar sua solicitação.")

# --- Aplicação FastAPI ---
app = FastAPI(title="Assistente de Tarefas com IA")

@app.get("/health")
def health_check(): return {"status": "ok"}

@app.post("/webhook")
async def webhook_receiver(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        key = data.get("data", {}).get("key", {})
        
        # <-- MODIFICADO: Verifica se a mensagem veio do grupo alvo
        is_target_group = key.get("remoteJid") == config['TARGET_GROUP_JID']
        
        if (data.get("event") == "messages.upsert" and 
            not key.get("fromMe", False) and 
            is_target_group):
            
            background_tasks.add_task(process_message, data)
        
        return {"status": "received"}
    except Exception:
        return {"status": "error_parsing_request"}

if __name__ == "__main__":
    import uvicorn
    print("🚀 Iniciando o servidor FastAPI do Assistente de Tarefas (modo Grupo)...")
    uvicorn.run(app, host="0.0.0.0", port=8000)