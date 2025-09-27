import gspread
from google.oauth2.service_account import Credentials
from thefuzz import process
import re
from datetime import datetime
import json
import logging
import os # <-- Adicionado

# --- Constantes ---
SCOPE = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file"
]
CREDENCIALS_FILE = "google-credentials.json"
WORKSHEET_NAME = "Tarefas"
SIMILARITY_THRESHOLD = 85

class TaskManager:
    """Gerencia a conexão e as operações com a planilha de Tarefas."""

    def __init__(self, spreadsheet_id: str):
        try:
            # ======================= AQUI ESTÁ A MUDANÇA =======================
            # Procura as credenciais na variável de ambiente primeiro
            creds_json_str = os.getenv("GOOGLE_CREDENTIALS_JSON")
            
            if creds_json_str:
                # Se encontrou, carrega a partir do texto (ideal para Railway/Heroku/etc)
                logging.info("✅ Carregando credenciais a partir da variável de ambiente.")
                creds_info = json.loads(creds_json_str)
                creds = Credentials.from_service_account_info(creds_info, scopes=SCOPE)
            else:
                # Se não, tenta carregar do arquivo (para desenvolvimento local)
                logging.info("✅ Carregando credenciais do arquivo 'google-credentials.json'.")
                creds = Credentials.from_service_account_file(CREDENCIALS_FILE, scopes=SCOPE)
            # ====================================================================

            client = gspread.authorize(creds)
            self.spreadsheet = client.open_by_key(spreadsheet_id)
            self.worksheet = self.spreadsheet.worksheet(WORKSHEET_NAME)
            logging.info(f"✅ Conectado com sucesso à planilha '{WORKSHEET_NAME}' (ID: {spreadsheet_id})")
        
        except FileNotFoundError:
            logging.critical(f"🚨 ERRO CRÍTICO: Arquivo '{CREDENCIALS_FILE}' não encontrado e a variável de ambiente 'GOOGLE_CREDENTIALS_JSON' não está definida.")
            raise
        except gspread.exceptions.WorksheetNotFound:
            logging.critical(f"🚨 ERRO CRÍTICO: A aba '{WORKSHEET_NAME}' não foi encontrada na planilha.")
            raise
        except Exception as e:
            logging.critical(f"🚨 ERRO CRÍTICO ao conectar com o Google Sheets: {e}", exc_info=True)
            raise

    #
    # O restante do arquivo (get_all_tasks_as_json, add_tasks, etc.) permanece o mesmo
    #

    def get_all_tasks_as_json(self) -> str:
        """Lê todos os registros da aba de tarefas e retorna como string JSON."""
        try:
            tasks_data = self.worksheet.get_all_records()
            return json.dumps(tasks_data, indent=2, ensure_ascii=False)
        except Exception as e:
            logging.error(f"🚨 ERRO ao ler as tarefas da planilha: {e}")
            return "[]"

    def _normalize_text(self, text: str) -> str:
        """Normaliza o texto para comparação (minúsculo, sem pontuação)."""
        if not isinstance(text, str): return ""
        return re.sub(r'[^\w\s]', '', text.lower().strip())

    def add_tasks(self, tasks_from_ai: list):
        """Adiciona novas tarefas à planilha."""
        if not tasks_from_ai:
            return
        
        new_rows_to_add = []
        for task in tasks_from_ai:
            new_rows_to_add.append([
                task.get("Data Hora", ""),
                task.get("Categoria", "Geral"),
                task.get("Situação", "A Fazer"),
                task.get("Descrição", "")
            ])
        
        if new_rows_to_add:
            self.worksheet.append_rows(new_rows_to_add)
            logging.info(f"✅ {len(new_rows_to_add)} nova(s) tarefa(s) adicionada(s) à planilha.")

    def update_tasks(self, updates_from_ai: list):
        """Atualiza tarefas existentes (ex: muda a situação para 'Concluído')."""
        if not updates_from_ai:
            return
            
        existing_tasks_data = self.worksheet.get_all_records()
        existing_tasks_map = {
            self._normalize_text(row.get("Descrição")): {"data": row, "row_index": i + 2}
            for i, row in enumerate(existing_tasks_data)
        }
        task_descriptions_in_sheet = list(existing_tasks_map.keys())
        
        updates_to_batch = []
        for update in updates_from_ai:
            identifier = self._normalize_text(update.get("identificador_tarefa"))
            if not identifier or not task_descriptions_in_sheet:
                continue

            match, score = process.extractOne(identifier, task_descriptions_in_sheet)
            if match and score >= SIMILARITY_THRESHOLD:
                row_idx = existing_tasks_map[match]["row_index"]
                column_map = {"Descrição": 4, "Situação": 3, "Categoria": 2, "Data Hora": 1}
                
                for key, value in update.items():
                    if key in column_map and key != "identificador_tarefa":
                         updates_to_batch.append(gspread.Cell(row_idx, column_map[key], str(value)))

        if updates_to_batch:
            self.worksheet.update_cells(updates_to_batch, value_input_option='USER_ENTERED')
            logging.info(f"✅ Tarefas atualizadas na planilha.")

    def delete_tasks(self, task_descriptions_from_ai: list):
        """Encontra e exclui tarefas da planilha com base na descrição."""
        if not task_descriptions_from_ai:
            return

        existing_tasks_data = self.worksheet.get_all_records()
        rows_to_delete_indexes = []
        normalized_names_from_ai = [self._normalize_text(name) for name in task_descriptions_from_ai]

        for i, row in enumerate(existing_tasks_data):
            row_task_desc_norm = self._normalize_text(row.get("Descrição"))
            if not row_task_desc_norm: continue

            best_match, score = process.extractOne(row_task_desc_norm, normalized_names_from_ai)
            if score >= SIMILARITY_THRESHOLD:
                rows_to_delete_indexes.append(i + 2)
                normalized_names_from_ai.remove(best_match)

        if not rows_to_delete_indexes:
            logging.warning("Nenhuma tarefa correspondente encontrada para exclusão.")
            return

        for row_index in sorted(list(set(rows_to_delete_indexes)), reverse=True):
            self.worksheet.delete_rows(row_index)
            logging.info(f"-> Linha {row_index} excluída.")
        
        logging.info(f"✅ {len(rows_to_delete_indexes)} tarefa(s) excluída(s) da planilha.")